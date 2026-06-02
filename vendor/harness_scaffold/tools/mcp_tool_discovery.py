from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool
from harness_scaffold.tools.registry import default_registry


class McpToolDiscoveryTool(AtomicTool):
    name = "mcp_tool_discovery"
    description = "List local scaffold tool specs and optional MCP-like tool manifests without invoking external services."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "manifest_path": {"type": "string"},
        },
    }
    output_schema = {"type": "object"}
    is_read_only = True

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query") or "").lower()
        specs = default_registry().specs()
        if args.get("manifest_path"):
            path = ctx.check_path_read(Path(str(args["manifest_path"])))
            extra = self._load_manifest(path)
            specs.extend(extra)
        if query:
            specs = [
                spec
                for spec in specs
                if query in str(spec.get("name", "")).lower()
                or query in str(spec.get("description", "")).lower()
            ]
        return ToolResult.success({"tools": specs, "count": len(specs)})

    @staticmethod
    def _load_manifest(path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid MCP manifest JSON: {exc}") from exc
        if isinstance(payload, dict) and isinstance(payload.get("tools"), list):
            return [dict(item) for item in payload["tools"] if isinstance(item, dict)]
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        raise ValueError("MCP manifest must be a list or an object with a tools list")


def get_tools() -> list[AtomicTool]:
    return [McpToolDiscoveryTool()]
