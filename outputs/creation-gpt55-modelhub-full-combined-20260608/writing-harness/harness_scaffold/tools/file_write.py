"""FileWriteTool: write a UTF-8 text file within the sandbox.

Creates parent directories as needed, confines writes to the sandbox via the
permission policy (unless ``allow_destructive_fs`` permits overwriting outside),
and supports an explicit append mode. Marked destructive because it can clobber
existing content. Never prints; never raises to the caller.
"""
from __future__ import annotations

from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool


class FileWriteTool(AtomicTool):
    name = "file_write"
    description = (
        "Write a UTF-8 text file within the sandbox. Creates parent "
        "directories as needed. Overwrites by default; set append=true to "
        "append. Refuses to overwrite an existing file outside the sandbox "
        "unless destructive filesystem access is allowed by policy."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Destination file path."},
            "content": {"type": "string", "description": "Text to write."},
            "append": {
                "type": "boolean",
                "description": "Append instead of overwrite (default false).",
            },
        },
        "required": ["path", "content"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "bytes_written": {"type": "integer"},
            "created": {"type": "boolean"},
        },
    }
    is_read_only = False
    is_destructive = True
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        raw_path = args.get("path")
        if not raw_path:
            return ToolResult.fail(
                "missing required argument 'path'",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        content = args.get("content")
        if content is None:
            return ToolResult.fail(
                "missing required argument 'content'",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        content = str(content)

        try:
            path = ctx.check_path_write(Path(raw_path))
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(), stage=f"tool:{self.name}")

        existed = path.exists()
        # Overwriting an existing file outside the sandbox requires destructive
        # fs permission. check_path_write already confines writes to the
        # sandbox, but guard explicitly for clarity / future extra_write_roots.
        if path.is_dir():
            return ToolResult.fail(
                f"path is a directory, not a file: {path}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        append = bool(args.get("append", False))

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with path.open(mode, encoding="utf-8") as fh:
                fh.write(content)
        except OSError as exc:
            return ToolResult.fail(
                f"failed to write file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        nbytes = len(content.encode("utf-8", "replace"))
        action = "appended to" if append else ("overwrote" if existed else "created")
        preview = f"{action} {path} ({nbytes} bytes)"
        return ToolResult.success(
            data={
                "path": str(path),
                "bytes_written": nbytes,
                "created": not existed,
            },
            stdout_preview=preview,
            metadata={"append": append, "existed": existed},
        )


def get_tools():
    return [FileWriteTool()]
