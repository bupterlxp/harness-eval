"""SearchTool: generic search dispatcher over glob + grep.

A thin convenience tool that combines the file-name search of GlobTool and
the content search of GrepTool behind one interface:

  - mode="files":   match file PATHS by a glob (delegates to GlobTool).
  - mode="content": match file CONTENTS by a regex (delegates to GrepTool),
                    and additionally ranks files by their match count
                    (most matches first).

Read-only, no network. All capping/timeout/permission behavior is inherited
from the underlying glob/grep implementations.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, HarnessError, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool
from .glob import GlobTool
from .grep import GrepTool

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000


class SearchTool(AtomicTool):
    name = "search"
    description = (
        "Generic search. mode='files' finds files by glob pattern; "
        "mode='content' searches file contents by regex and ranks files by "
        "match count (most matches first). Read-only, capped."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Glob pattern (mode=files) or regex (mode=content).",
            },
            "mode": {
                "type": "string",
                "enum": ["files", "content"],
                "description": "Search mode (default 'content').",
            },
            "path": {"type": "string", "description": "Base path to search (default workdir)."},
            "glob": {
                "type": "string",
                "description": "For mode=content: restrict to files matching this glob.",
            },
            "ignore_case": {"type": "boolean", "description": "Case-insensitive content match."},
            "limit": {"type": "integer", "description": f"Max results (default {_DEFAULT_LIMIT}, max {_MAX_LIMIT})."},
        },
        "required": ["query"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string"},
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "match_count": {"type": "integer"},
                    },
                },
            },
            "matches": {"type": "array"},
            "count": {"type": "integer"},
            "truncated": {"type": "boolean"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    def __init__(self, *, glob_tool: GlobTool | None = None,
                 grep_tool: GrepTool | None = None):
        self._glob = glob_tool or GlobTool()
        self._grep = grep_tool or GrepTool()

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        start = time.monotonic()
        query = args.get("query")
        if not isinstance(query, str) or query == "":
            return ToolResult.fail(
                "search requires a non-empty 'query' string",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:search",
            )
        mode = (args.get("mode") or "content").lower()
        if mode not in ("files", "content"):
            return ToolResult.fail(
                f"unknown search mode: {mode!r} (expected 'files' or 'content')",
                error_code=ErrorCode.TOOL_ERROR,
                stage="tool:search",
            )

        try:
            limit = int(args.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        try:
            if mode == "files":
                return await self._search_files(ctx, query, args, limit, start)
            return await self._search_content(ctx, query, args, limit, start)
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=ErrorCode.PERMISSION_DENIED,
                stage="tool:search",
            )
        except HarnessError as exc:
            return ToolResult.fail(
                exc.args[0] if exc.args else str(exc),
                error_code=getattr(exc, "error_code", ErrorCode.TOOL_ERROR),
                stage="tool:search",
            )

    async def _search_files(self, ctx, query, args, limit, start):
        glob_args = {"pattern": query, "limit": limit}
        if args.get("path"):
            glob_args["path"] = args["path"]
        # Delegate to GlobTool.run (not execute) so we keep one logical step.
        res = await self._glob.run(ctx, glob_args)
        if not res.ok:
            return res
        data = res.data or {}
        matches = data.get("matches", [])
        files = [{"file": m, "match_count": 1} for m in matches]
        preview = "\n".join(matches[:200])
        return ToolResult.success(
            data={
                "mode": "files",
                "files": files,
                "matches": matches,
                "count": len(matches),
                "truncated": bool(data.get("truncated")),
            },
            stdout_preview=preview,
            elapsed_seconds=time.monotonic() - start,
            metadata={"delegated_to": "glob"},
        )

    async def _search_content(self, ctx, query, args, limit, start):
        grep_args = {"pattern": query, "limit": limit}
        for k in ("path", "glob", "ignore_case"):
            if args.get(k) is not None:
                grep_args[k] = args[k]
        res = await self._grep.run(ctx, grep_args)
        if not res.ok:
            return res
        data = res.data or {}
        matches = data.get("matches", [])
        # Rank files by match count, descending; stable on first-seen order.
        counts: dict[str, int] = {}
        order: list[str] = []
        for m in matches:
            f = m.get("file", "")
            if f not in counts:
                counts[f] = 0
                order.append(f)
            counts[f] += 1
        ranked = sorted(order, key=lambda f: (-counts[f], f))
        files = [{"file": f, "match_count": counts[f]} for f in ranked]
        preview_lines = [f"{f}  ({counts[f]} matches)" for f in ranked[:100]]
        return ToolResult.success(
            data={
                "mode": "content",
                "files": files,
                "matches": matches,
                "count": len(matches),
                "truncated": bool(data.get("truncated")),
            },
            stdout_preview="\n".join(preview_lines),
            elapsed_seconds=time.monotonic() - start,
            metadata={"delegated_to": "grep", "engine": data.get("engine")},
        )


def get_tools():
    return [SearchTool()]
