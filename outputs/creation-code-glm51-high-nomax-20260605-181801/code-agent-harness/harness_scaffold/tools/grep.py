"""GrepTool: regex search across files within the sandbox.

Uses ripgrep (``rg``) via the shared subprocess helper when it is on PATH
(fast, with built-in timeout + process-group cleanup), and falls back to a
pure-Python ``re`` scan otherwise. Read-only, no network. Results are
``file:line:text`` matches, capped.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import time
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import (
    ErrorCode,
    HarnessError,
    PermissionDenied,
    ShellError,
    TimeoutErrorH,
)
from ..core.schemas import ToolResult
from .base import AtomicTool, _run_subprocess

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000
_MAX_LINE_LEN = 2000
_DEFAULT_IGNORE_DIRS = (".git", "node_modules", "__pycache__", ".venv", "venv",
                        ".mypy_cache", ".pytest_cache", "dist", "build")
# Skip files larger than this in the pure-python path (bytes).
_MAX_FILE_BYTES = 5_000_000


def _ripgrep_path() -> str | None:
    return shutil.which("rg")


class GrepTool(AtomicTool):
    name = "grep"
    description = (
        "Search file contents with a regular expression. Returns "
        "'file:line:text' matches within the sandbox, capped to a limit. "
        "Uses ripgrep when available, otherwise a pure-Python scan."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for."},
            "path": {"type": "string", "description": "File or directory to search (default workdir)."},
            "glob": {"type": "string", "description": "Only search files matching this glob (e.g. '*.py')."},
            "ignore_case": {"type": "boolean", "description": "Case-insensitive match (default false)."},
            "limit": {"type": "integer", "description": f"Max matches (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT})."},
            "fixed_string": {"type": "boolean", "description": "Treat pattern as a literal string, not regex."},
        },
        "required": ["pattern"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                },
            },
            "count": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "engine": {"type": "string"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        start = time.monotonic()
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or pattern == "":
            return ToolResult.fail(
                "grep requires a non-empty 'pattern' string",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:grep",
            )

        path_arg = args.get("path")
        base_path = Path(path_arg) if path_arg else ctx.workdir
        if not base_path.is_absolute():
            base_path = ctx.workdir / base_path
        try:
            base = ctx.check_path_read(base_path)
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=ErrorCode.PERMISSION_DENIED,
                stage="tool:grep",
            )
        if not base.exists():
            return ToolResult.fail(
                f"path does not exist: {base}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:grep",
            )

        try:
            limit = int(args.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))
        ignore_case = bool(args.get("ignore_case", False))
        fixed_string = bool(args.get("fixed_string", False))
        glob_filter = args.get("glob") or None

        rg = _ripgrep_path()
        try:
            if rg:
                matches, truncated, engine = self._run_ripgrep(
                    ctx, rg, base, pattern, limit, ignore_case, fixed_string, glob_filter
                )
            else:
                matches, truncated, engine = self._run_python(
                    ctx, base, pattern, limit, ignore_case, fixed_string, glob_filter, start
                )
        except HarnessError as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=getattr(exc, "error_code", ErrorCode.TOOL_ERROR),
                stage="tool:grep",
            )
        except re.error as exc:
            return ToolResult.fail(
                f"invalid regex: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:grep",
            )
        except (OSError, ValueError) as exc:
            return ToolResult.fail(
                f"grep failed: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage="tool:grep",
            )

        preview_lines = [f"{m['file']}:{m['line']}:{m['text']}" for m in matches[:100]]
        return ToolResult.success(
            data={
                "matches": matches,
                "count": len(matches),
                "truncated": truncated,
                "engine": engine,
            },
            stdout_preview="\n".join(preview_lines),
            elapsed_seconds=time.monotonic() - start,
            metadata={"base": str(base), "pattern": pattern, "engine": engine},
        )

    # ------------------------------------------------------------------ rg
    def _run_ripgrep(self, ctx, rg, base, pattern, limit, ignore_case,
                     fixed_string, glob_filter):
        cmd = [rg, "--line-number", "--no-heading", "--with-filename",
               "--color", "never", "--max-count", str(limit)]
        # cap matches per file and overall via line limit handled below
        if ignore_case:
            cmd.append("--ignore-case")
        if fixed_string:
            cmd.append("--fixed-strings")
        if glob_filter:
            cmd.extend(["--glob", glob_filter])
        for d in _DEFAULT_IGNORE_DIRS:
            cmd.extend(["--glob", f"!{d}/"])
        cmd.append("--")
        cmd.append(pattern)
        cmd.append(str(base))

        try:
            res = _run_subprocess(cmd, ctx=ctx, cwd=base if base.is_dir() else base.parent)
        except TimeoutErrorH:
            raise
        except ShellError:
            # rg disappeared / failed to spawn -> fall back to python engine
            return self._run_python(ctx, base, pattern, limit, ignore_case,
                                    fixed_string, glob_filter, time.monotonic())
        # rg exit codes: 0 matches found, 1 no matches, 2 error
        if res.returncode not in (0, 1):
            raise ShellError(
                f"ripgrep error (exit {res.returncode}): {res.stderr.strip()[:500]}"
            )
        matches = []
        truncated = res.truncated
        for raw in res.stdout.splitlines():
            if len(matches) >= limit:
                truncated = True
                break
            parsed = self._parse_rg_line(raw, base)
            if parsed is not None:
                matches.append(parsed)
        return matches, truncated, "ripgrep"

    @staticmethod
    def _parse_rg_line(raw, base):
        # format: path:line:text  (path may contain ':' so split carefully)
        # rg always emits path first, then line number, then text.
        # Find "<num>:" after a ":".
        parts = raw.split(":", 2)
        if len(parts) < 3:
            return None
        fpath, lineno, text = parts[0], parts[1], parts[2]
        try:
            line = int(lineno)
        except ValueError:
            return None
        try:
            rel = str(Path(fpath).resolve().relative_to(base if base.is_dir() else base.parent))
        except (ValueError, OSError):
            rel = fpath
        if len(text) > _MAX_LINE_LEN:
            text = text[:_MAX_LINE_LEN] + "...[truncated]"
        return {"file": rel, "line": line, "text": text}

    # -------------------------------------------------------------- python
    def _run_python(self, ctx, base, pattern, limit, ignore_case,
                    fixed_string, glob_filter, start):
        flags = re.MULTILINE
        if ignore_case:
            flags |= re.IGNORECASE
        if fixed_string:
            rx = re.compile(re.escape(pattern), flags)
        else:
            rx = re.compile(pattern, flags)  # may raise re.error -> handled by caller

        deadline = None
        try:
            left = ctx.budget.seconds_left()
            tool_cap = ctx.policy.max_tool_seconds
            cap = min(x for x in (left, tool_cap) if x and x > 0)
            if cap and cap > 0:
                deadline = start + cap
        except Exception:
            deadline = None

        if base.is_file():
            files = [base]
            root = base.parent
        else:
            files = self._iter_files(base, glob_filter)
            root = base

        matches = []
        truncated = False
        scanned = 0
        for fpath in files:
            if len(matches) >= limit:
                truncated = True
                break
            scanned += 1
            if scanned % 50 == 0:
                ctx.check_abort(stage="tool:grep")
                if deadline is not None and time.monotonic() > deadline:
                    truncated = True
                    break
            if glob_filter and base.is_file() is False:
                pass  # already filtered in _iter_files
            try:
                if fpath.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            try:
                with fpath.open("r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, start=1):
                        if rx.search(line):
                            text = line.rstrip("\n")
                            if len(text) > _MAX_LINE_LEN:
                                text = text[:_MAX_LINE_LEN] + "...[truncated]"
                            try:
                                rel = str(fpath.relative_to(root))
                            except ValueError:
                                rel = str(fpath)
                            matches.append({"file": rel, "line": i, "text": text})
                            if len(matches) >= limit:
                                truncated = True
                                break
            except (OSError, UnicodeError):
                continue
        return matches, truncated, "python"

    def _iter_files(self, base, glob_filter):
        for dirpath, dirnames, filenames in os.walk(base):
            # prune ignored dirs in place
            dirnames[:] = [d for d in dirnames if d not in _DEFAULT_IGNORE_DIRS]
            for fn in filenames:
                if glob_filter and not fnmatch.fnmatch(fn, glob_filter):
                    continue
                yield Path(dirpath) / fn


def get_tools():
    return [GrepTool()]
