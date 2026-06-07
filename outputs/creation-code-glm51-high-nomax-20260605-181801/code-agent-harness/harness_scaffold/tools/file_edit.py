"""FileEditTool: exact-string in-place edit of a text file.

Replaces ``old_string`` with ``new_string``. By default the match must be
unique (errors if not found or ambiguous). Set ``replace_all=true`` to replace
every occurrence. The edit is confined to the sandbox via the permission policy
and is marked destructive. Never prints; never raises to the caller.
"""
from __future__ import annotations

from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool


class FileEditTool(AtomicTool):
    name = "file_edit"
    description = (
        "Replace an exact string in a text file. The match must be unique "
        "unless replace_all=true. Errors if old_string is not found or is "
        "ambiguous (multiple matches without replace_all)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit."},
            "old_string": {
                "type": "string",
                "description": "Exact text to find.",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences (default false).",
            },
        },
        "required": ["path", "old_string", "new_string"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "replacements": {"type": "integer"},
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
        old_string = args.get("old_string")
        new_string = args.get("new_string")
        if old_string is None or new_string is None:
            return ToolResult.fail(
                "missing required argument 'old_string' or 'new_string'",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        old_string = str(old_string)
        new_string = str(new_string)
        if old_string == new_string:
            return ToolResult.fail(
                "old_string and new_string are identical; no edit to perform",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )

        # Need both read and write permission on the path.
        try:
            path = ctx.check_path_read(Path(raw_path))
            path = ctx.check_path_write(path)
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(), stage=f"tool:{self.name}")

        if not path.exists():
            return ToolResult.fail(
                f"file not found: {path}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )
        if path.is_dir():
            return ToolResult.fail(
                f"path is a directory, not a file: {path}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.fail(
                f"failed to read file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        count = text.count(old_string)
        if count == 0:
            return ToolResult.fail(
                "old_string not found in file",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        replace_all = bool(args.get("replace_all", False))
        if count > 1 and not replace_all:
            return ToolResult.fail(
                f"old_string is ambiguous: {count} matches found "
                "(set replace_all=true to replace all)",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path), "matches": count},
            )

        if replace_all:
            new_text = text.replace(old_string, new_string)
            replacements = count
        else:
            new_text = text.replace(old_string, new_string, 1)
            replacements = 1

        try:
            path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            return ToolResult.fail(
                f"failed to write file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        preview = f"edited {path}: {replacements} replacement(s)"
        return ToolResult.success(
            data={"path": str(path), "replacements": replacements},
            stdout_preview=preview,
            metadata={"replace_all": replace_all, "matches": count},
        )


def get_tools():
    return [FileEditTool()]
