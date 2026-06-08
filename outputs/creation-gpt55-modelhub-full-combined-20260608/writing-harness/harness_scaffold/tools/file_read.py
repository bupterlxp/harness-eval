"""FileReadTool: read a UTF-8 text file within the sandbox.

Supports offset/limit (1-based line slicing), optional line numbers, a
large-file guard via ``max_output_bytes`` truncation, and a binary-content
guard that returns a structured note instead of garbage. All filesystem paths
go through the permission policy. Never prints; never raises to the caller.
"""
from __future__ import annotations

from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, FilesystemError, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool

# Heuristic: if a sample contains a NUL byte (or too many non-text bytes) we
# treat the file as binary.
_BINARY_SAMPLE_BYTES = 8192


def _looks_binary(sample: bytes) -> bool:
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    # Count bytes that are not printable/whitespace text.
    text_chars = bytes(range(0x20, 0x7F)) + b"\t\n\r\f\b"
    nontext = sum(1 for b in sample if b not in text_chars)
    return (nontext / len(sample)) > 0.30


class FileReadTool(AtomicTool):
    name = "file_read"
    description = (
        "Read a UTF-8 text file within the sandbox. Supports offset/limit "
        "(1-based line numbers), optional line numbering, and guards against "
        "binary or oversized files."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to read."},
            "offset": {
                "type": "integer",
                "description": "1-based line number to start from (default 1).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read.",
            },
            "line_numbers": {
                "type": "boolean",
                "description": "Prefix each line with its 1-based line number.",
            },
        },
        "required": ["path"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "path": {"type": "string"},
            "num_lines": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "binary": {"type": "boolean"},
        },
    }
    is_read_only = True
    is_destructive = False
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

        try:
            path = ctx.check_path_read(Path(raw_path))
        except PermissionDenied as exc:
            return ToolResult.fail(
                exc.to_dict(), stage=f"tool:{self.name}"
            )

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

        # Binary guard: sample the first chunk.
        try:
            with path.open("rb") as fh:
                sample = fh.read(_BINARY_SAMPLE_BYTES)
        except OSError as exc:
            return ToolResult.fail(
                f"failed to read file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        if _looks_binary(sample):
            try:
                size = path.stat().st_size
            except OSError:
                size = len(sample)
            note = (
                f"[binary file not shown: {path.name}, {size} bytes]"
            )
            return ToolResult.success(
                data={
                    "content": note,
                    "path": str(path),
                    "num_lines": 0,
                    "truncated": False,
                    "binary": True,
                },
                stdout_preview=note,
                metadata={"binary": True, "size_bytes": size},
            )

        # Read as text (replace undecodable bytes so we never raise).
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult.fail(
                f"failed to read file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )

        lines = text.splitlines()
        total_lines = len(lines)

        # Apply offset/limit (1-based offset).
        offset = args.get("offset")
        limit = args.get("limit")
        start = 0
        if offset is not None:
            try:
                start = max(0, int(offset) - 1)
            except (TypeError, ValueError):
                return ToolResult.fail(
                    "'offset' must be an integer",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage=f"tool:{self.name}",
                )
        end = total_lines
        if limit is not None:
            try:
                end = start + max(0, int(limit))
            except (TypeError, ValueError):
                return ToolResult.fail(
                    "'limit' must be an integer",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage=f"tool:{self.name}",
                )
        selected = lines[start:end]

        line_numbers = bool(args.get("line_numbers", False))
        if line_numbers:
            rendered = "\n".join(
                f"{start + i + 1}\t{ln}" for i, ln in enumerate(selected)
            )
        else:
            rendered = "\n".join(selected)

        # Large-file guard: truncate to max_output_bytes.
        max_bytes = ctx.policy.max_output_bytes
        truncated = False
        if max_bytes and max_bytes > 0:
            encoded = rendered.encode("utf-8", "replace")
            if len(encoded) > max_bytes:
                rendered = encoded[:max_bytes].decode("utf-8", "replace")
                rendered += "\n...[truncated]"
                truncated = True

        preview = rendered[:1000]
        return ToolResult.success(
            data={
                "content": rendered,
                "path": str(path),
                "num_lines": len(selected),
                "truncated": truncated,
                "binary": False,
            },
            stdout_preview=preview,
            metadata={
                "total_lines": total_lines,
                "returned_lines": len(selected),
                "truncated": truncated,
            },
        )


def get_tools():
    return [FileReadTool()]
