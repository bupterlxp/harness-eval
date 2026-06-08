"""GlobTool: list files matching a glob pattern within the sandbox.

Pure-stdlib (pathlib). Read-only, no network, no subprocess. Results are
capped and sorted (by modification time, newest first, like Claude Code's
glob) so callers get the most-recently-touched matches when truncated.
"""
from __future__ import annotations

import fnmatch
import time
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, HarnessError, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool

# Hard caps so a runaway pattern (e.g. "**/*") cannot exhaust memory/time.
_DEFAULT_LIMIT = 1000
_MAX_LIMIT = 10000
_DEFAULT_IGNORE = (".git", "node_modules", "__pycache__", ".venv", "venv",
                   ".mypy_cache", ".pytest_cache", "dist", "build")


def _is_ignored(path: Path, base: Path, ignore: tuple) -> bool:
    try:
        rel_parts = path.relative_to(base).parts
    except ValueError:
        rel_parts = path.parts
    for part in rel_parts:
        for pat in ignore:
            if part == pat or fnmatch.fnmatch(part, pat):
                return True
    return False


class GlobTool(AtomicTool):
    name = "glob"
    description = (
        "List files matching a glob pattern (e.g. '**/*.py', 'src/*.txt') "
        "within the sandbox. Returns relative paths sorted by modification "
        "time (newest first), capped to a limit."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern. Use '**' for recursive matching.",
            },
            "path": {
                "type": "string",
                "description": "Base directory to search from (default: workdir).",
            },
            "limit": {
                "type": "integer",
                "description": f"Max results (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT}).",
            },
            "include_dirs": {
                "type": "boolean",
                "description": "Include directories in results (default false).",
            },
        },
        "required": ["pattern"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "matches": {"type": "array", "items": {"type": "string"}},
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
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.fail(
                "glob requires a non-empty 'pattern' string",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:glob",
            )

        base_arg = args.get("path")
        base_path = Path(base_arg) if base_arg else ctx.workdir
        if not base_path.is_absolute():
            base_path = ctx.workdir / base_path
        try:
            base = ctx.check_path_read(base_path)
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=ErrorCode.PERMISSION_DENIED,
                stage="tool:glob",
            )

        if not base.exists():
            return ToolResult.fail(
                f"base path does not exist: {base}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:glob",
            )
        if not base.is_dir():
            return ToolResult.fail(
                f"base path is not a directory: {base}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:glob",
            )

        try:
            limit = int(args.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))
        include_dirs = bool(args.get("include_dirs", False))

        # Deadline: stay within remaining budget / per-tool timeout.
        deadline = None
        try:
            left = ctx.budget.seconds_left()
            tool_cap = ctx.policy.max_tool_seconds
            cap = min(x for x in (left, tool_cap) if x and x > 0)
            if cap and cap > 0:
                deadline = start + cap
        except Exception:
            deadline = None

        results = []
        truncated = False
        scanned = 0
        try:
            # pathlib.glob handles '**' recursion when present in pattern.
            iterator = base.glob(pattern)
            for p in iterator:
                scanned += 1
                # Periodically honor abort + deadline without checking every item.
                if scanned % 500 == 0:
                    try:
                        ctx.check_abort(stage="tool:glob")
                    except HarnessError:
                        raise
                    if deadline is not None and time.monotonic() > deadline:
                        truncated = True
                        break
                if _is_ignored(p, base, _DEFAULT_IGNORE):
                    continue
                if p.is_dir() and not include_dirs:
                    continue
                results.append(p)
                if len(results) > limit * 4:
                    # Collected plenty more than we'll return; stop scanning.
                    truncated = True
                    break
        except HarnessError as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=getattr(exc, "error_code", ErrorCode.TOOL_ERROR),
                stage="tool:glob",
            )
        except (OSError, ValueError) as exc:
            return ToolResult.fail(
                f"glob failed: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:glob",
            )

        # Sort newest-first by mtime (stat failures sort last).
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return -1.0

        results.sort(key=_mtime, reverse=True)
        if len(results) > limit:
            results = results[:limit]
            truncated = True

        rels = []
        for p in results:
            try:
                rels.append(str(p.relative_to(base)))
            except ValueError:
                rels.append(str(p))

        preview = "\n".join(rels[:200])
        return ToolResult.success(
            data={"matches": rels, "count": len(rels), "truncated": truncated},
            stdout_preview=preview,
            elapsed_seconds=time.monotonic() - start,
            metadata={"base": str(base), "pattern": pattern, "scanned": scanned},
        )


def get_tools():
    return [GlobTool()]
