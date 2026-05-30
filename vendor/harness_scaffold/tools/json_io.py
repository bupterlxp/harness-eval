"""JsonIOTool: structured read/write/merge of JSON files within the sandbox.

Operations:
  - read_json:  parse a JSON file and return the object.
  - write_json: serialize ``data`` to a JSON file (parents created as needed).
  - merge:      shallow-merge ``data`` into an existing JSON object file
                (or create it if absent). Lists are replaced, not concatenated.

Safe parsing returns a structured ``filesystem_error`` / ``tool_error`` instead
of raising. Never prints; never raises to the caller.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode, PermissionDenied
from ..core.schemas import ToolResult
from .base import AtomicTool

_OPERATIONS = ("read_json", "write_json", "merge")


class JsonIOTool(AtomicTool):
    name = "json_io"
    description = (
        "Read, write, or merge JSON files within the sandbox. "
        "operation=read_json|write_json|merge. write_json serializes 'data'; "
        "merge shallow-merges 'data' into an existing JSON object."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(_OPERATIONS),
                "description": "One of read_json, write_json, merge.",
            },
            "path": {"type": "string", "description": "JSON file path."},
            "data": {
                "description": "Object to write/merge (for write_json/merge).",
            },
            "indent": {
                "type": "integer",
                "description": "Indentation for serialization (default 2).",
            },
        },
        "required": ["operation", "path"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "path": {"type": "string"},
            "data": {},
            "bytes_written": {"type": "integer"},
        },
    }
    is_read_only = False
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        operation = args.get("operation")
        if operation not in _OPERATIONS:
            return ToolResult.fail(
                f"invalid operation: {operation!r}; expected one of {_OPERATIONS}",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        raw_path = args.get("path")
        if not raw_path:
            return ToolResult.fail(
                "missing required argument 'path'",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )

        if operation == "read_json":
            return self._read_json(ctx, raw_path)
        # write_json / merge both need write permission and 'data'.
        if "data" not in args:
            return ToolResult.fail(
                f"operation '{operation}' requires 'data'",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        if operation == "write_json":
            return self._write_json(ctx, raw_path, args["data"], args.get("indent", 2))
        return self._merge(ctx, raw_path, args["data"], args.get("indent", 2))

    # ----- helpers ----- #
    def _read_json(self, ctx: RuntimeContext, raw_path) -> ToolResult:
        try:
            path = ctx.check_path_read(Path(raw_path))
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(), stage=f"tool:{self.name}")
        if not path.exists():
            return ToolResult.fail(
                f"file not found: {path}",
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
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            return ToolResult.fail(
                f"invalid JSON: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )
        preview = json.dumps(obj, ensure_ascii=False)[:1000]
        return ToolResult.success(
            data={"operation": "read_json", "path": str(path), "data": obj},
            stdout_preview=preview,
        )

    def _serialize(self, obj, indent) -> str:
        try:
            ind = int(indent)
        except (TypeError, ValueError):
            ind = 2
        return json.dumps(obj, indent=ind, ensure_ascii=False, sort_keys=False)

    def _write_json(self, ctx: RuntimeContext, raw_path, data, indent) -> ToolResult:
        try:
            path = ctx.check_path_write(Path(raw_path))
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(), stage=f"tool:{self.name}")
        try:
            serialized = self._serialize(data, indent)
        except (TypeError, ValueError) as exc:
            return ToolResult.fail(
                f"data is not JSON-serializable: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
        except OSError as exc:
            return ToolResult.fail(
                f"failed to write file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )
        nbytes = len(serialized.encode("utf-8", "replace"))
        return ToolResult.success(
            data={
                "operation": "write_json",
                "path": str(path),
                "bytes_written": nbytes,
            },
            stdout_preview=f"wrote JSON to {path} ({nbytes} bytes)",
        )

    def _merge(self, ctx: RuntimeContext, raw_path, data, indent) -> ToolResult:
        if not isinstance(data, dict):
            return ToolResult.fail(
                "merge requires 'data' to be a JSON object (dict)",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        try:
            path = ctx.check_path_write(Path(raw_path))
        except PermissionDenied as exc:
            return ToolResult.fail(exc.to_dict(), stage=f"tool:{self.name}")

        existing: dict = {}
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                loaded = json.loads(text)
            except (json.JSONDecodeError, ValueError) as exc:
                return ToolResult.fail(
                    f"existing file is not valid JSON: {exc}",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage=f"tool:{self.name}",
                    details={"path": str(path)},
                )
            except OSError as exc:
                return ToolResult.fail(
                    f"failed to read file: {exc}",
                    error_code=ErrorCode.FILESYSTEM_ERROR,
                    stage=f"tool:{self.name}",
                    details={"path": str(path)},
                )
            if not isinstance(loaded, dict):
                return ToolResult.fail(
                    "existing JSON is not an object; cannot merge",
                    error_code=ErrorCode.TOOL_ERROR,
                    stage=f"tool:{self.name}",
                    details={"path": str(path)},
                )
            existing = loaded

        merged = dict(existing)
        merged.update(data)
        try:
            serialized = self._serialize(merged, indent)
        except (TypeError, ValueError) as exc:
            return ToolResult.fail(
                f"merged data is not JSON-serializable: {exc}",
                error_code=ErrorCode.TOOL_ERROR,
                stage=f"tool:{self.name}",
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
        except OSError as exc:
            return ToolResult.fail(
                f"failed to write file: {exc}",
                error_code=ErrorCode.FILESYSTEM_ERROR,
                stage=f"tool:{self.name}",
                details={"path": str(path)},
            )
        nbytes = len(serialized.encode("utf-8", "replace"))
        return ToolResult.success(
            data={
                "operation": "merge",
                "path": str(path),
                "data": merged,
                "bytes_written": nbytes,
            },
            stdout_preview=f"merged JSON into {path} ({nbytes} bytes)",
        )


def get_tools():
    return [JsonIOTool()]
