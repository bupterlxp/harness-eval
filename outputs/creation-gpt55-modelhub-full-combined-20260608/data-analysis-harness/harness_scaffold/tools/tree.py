"""TreeTool: render a directory tree to a bounded depth.

Pure-stdlib (os.scandir). Read-only, no network, no subprocess. Ignores
noise directories (.git, node_modules, ...) and caps total entries so a huge
tree cannot blow the output budget.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, HarnessError, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool

_DEFAULT_DEPTH = 3
_MAX_DEPTH = 20
_DEFAULT_MAX_ENTRIES = 2000
_HARD_MAX_ENTRIES = 20000
_DEFAULT_IGNORE = (".git", "node_modules", "__pycache__", ".venv", "venv",
                   ".mypy_cache", ".pytest_cache", "dist", "build", ".idea")


class TreeTool(AtomicTool):
    name = "tree"
    description = (
        "Render a directory tree to a bounded depth, ignoring noise "
        "directories (.git, node_modules, ...). Capped to a maximum number "
        "of entries."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Root directory (default: workdir)."},
            "depth": {"type": "integer", "description": f"Max depth (default {_DEFAULT_DEPTH}, max {_MAX_DEPTH})."},
            "max_entries": {"type": "integer", "description": f"Max entries (default {_DEFAULT_MAX_ENTRIES})."},
            "show_hidden": {"type": "boolean", "description": "Include dotfiles (default false)."},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "tree": {"type": "string"},
            "entries": {"type": "array", "items": {"type": "string"}},
            "count": {"type": "integer"},
            "truncated": {"type": "boolean"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        start = time.monotonic()
        path_arg = args.get("path")
        root_path = Path(path_arg) if path_arg else ctx.workdir
        if not root_path.is_absolute():
            root_path = ctx.workdir / root_path
        try:
            root = ctx.check_path_read(root_path)
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=ErrorCode.PERMISSION_DENIED,
                stage="tool:tree",
            )
        if not root.exists():
            return ToolResult.fail(
                f"path does not exist: {root}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:tree",
            )
        if not root.is_dir():
            return ToolResult.fail(
                f"path is not a directory: {root}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:tree",
            )

        try:
            depth = int(args.get("depth") or _DEFAULT_DEPTH)
        except (TypeError, ValueError):
            depth = _DEFAULT_DEPTH
        depth = max(0, min(depth, _MAX_DEPTH))
        try:
            max_entries = int(args.get("max_entries") or _DEFAULT_MAX_ENTRIES)
        except (TypeError, ValueError):
            max_entries = _DEFAULT_MAX_ENTRIES
        max_entries = max(1, min(max_entries, _HARD_MAX_ENTRIES))
        show_hidden = bool(args.get("show_hidden", False))

        deadline = None
        try:
            left = ctx.budget.seconds_left()
            tool_cap = ctx.policy.max_tool_seconds
            cap = min(x for x in (left, tool_cap) if x and x > 0)
            if cap and cap > 0:
                deadline = start + cap
        except Exception:
            deadline = None

        lines = [root.name + "/"]
        entries = []
        state = {"count": 0, "truncated": False}

        try:
            self._walk(ctx, root, prefix="", depth_left=depth, lines=lines,
                       entries=entries, root=root, max_entries=max_entries,
                       show_hidden=show_hidden, state=state, deadline=deadline)
        except HarnessError as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=getattr(exc, "error_code", ErrorCode.TOOL_ERROR),
                stage="tool:tree",
            )
        except OSError as exc:
            return ToolResult.fail(
                f"tree failed: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:tree",
            )

        if state["truncated"]:
            lines.append("...[truncated]")
        tree_text = "\n".join(lines)
        preview = tree_text if len(tree_text) <= 4000 else tree_text[:4000] + "\n...[truncated]"
        return ToolResult.success(
            data={
                "tree": tree_text,
                "entries": entries,
                "count": state["count"],
                "truncated": state["truncated"],
            },
            stdout_preview=preview,
            elapsed_seconds=time.monotonic() - start,
            metadata={"root": str(root), "depth": depth},
        )

    def _walk(self, ctx, directory, *, prefix, depth_left, lines, entries,
              root, max_entries, show_hidden, state, deadline):
        if state["truncated"] or depth_left < 0:
            return
        try:
            with __import__("os").scandir(directory) as it:
                children = list(it)
        except OSError:
            return

        # Sort: directories first, then files; alphabetical within each.
        def _key(e):
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            return (0 if is_dir else 1, e.name.lower())

        children.sort(key=_key)
        # Filter
        visible = []
        for e in children:
            if not show_hidden and e.name.startswith("."):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                is_dir = False
            if is_dir and e.name in _DEFAULT_IGNORE:
                # still show the dir name but do not descend
                visible.append((e, is_dir, True))
                continue
            visible.append((e, is_dir, False))

        n = len(visible)
        for idx, (e, is_dir, pruned) in enumerate(visible):
            if state["count"] >= max_entries:
                state["truncated"] = True
                return
            if state["count"] % 200 == 0:
                ctx.check_abort(stage="tool:tree")
                if deadline is not None and time.monotonic() > deadline:
                    state["truncated"] = True
                    return
            last = idx == n - 1
            connector = "└── " if last else "├── "
            name = e.name + ("/" if is_dir else "")
            suffix = "  (not descended)" if pruned else ""
            lines.append(prefix + connector + name + suffix)
            try:
                rel = str(Path(e.path).relative_to(root))
            except ValueError:
                rel = e.path
            entries.append(rel + ("/" if is_dir else ""))
            state["count"] += 1
            if is_dir and not pruned and depth_left > 0:
                child_prefix = prefix + ("    " if last else "│   ")
                self._walk(ctx, e.path, prefix=child_prefix,
                           depth_left=depth_left - 1, lines=lines,
                           entries=entries, root=root, max_entries=max_entries,
                           show_hidden=show_hidden, state=state, deadline=deadline)


def get_tools():
    return [TreeTool()]
