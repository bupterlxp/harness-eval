"""Custom tools for data analysis tasks.

Registers domain-specific tools with the scaffold ToolRegistry.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool


class DataInspectTool(AtomicTool):
    """Inspect a data file and return compact schema/stats summary."""
    name = "data_inspect"
    description = (
        "Inspect a data file (CSV, JSON, Parquet, SQLite, Excel) and return "
        "column names, dtypes, row count, missing values, and a small preview. "
        "Use this to understand data before processing."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the data file (relative to workdir or absolute).",
            },
            "max_preview_rows": {
                "type": "integer",
                "description": "Max rows to preview (default 3).",
                "default": 3,
            },
        },
        "required": ["path"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "columns": {"type": "array"},
            "row_count": {"type": "integer"},
            "dtypes": {"type": "object"},
            "missing_counts": {"type": "object"},
            "preview": {"type": "array"},
        },
    }
    is_read_only = True
    is_destructive = False
    requires_network = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        from context_manager import infer_schema
        path_str = args.get("path", "")
        max_rows = int(args.get("max_preview_rows", 3))
        try:
            path = Path(path_str)
            if not path.is_absolute():
                path = ctx.workdir / path
            ctx.check_path_read(path)
            schema = infer_schema(path, max_rows)
            return ToolResult.success(data=schema)
        except Exception as exc:
            return ToolResult.fail(str(exc), error_code="tool_error", stage=self.name)


def register_custom_tools(registry: Any) -> None:
    """Register all custom data analysis tools with the scaffold registry."""
    custom_tools = [
        DataInspectTool(),
    ]
    for tool in custom_tools:
        if not registry.has(tool.name):
            registry.register(tool, override=False)
