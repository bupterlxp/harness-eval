"""Custom domain tools for data analysis: data discovery, summarization,
and submission generation helpers.

These are registered with the scaffold ToolRegistry so the program can
dispatch them like any other atomic tool.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool


class DataDiscoveryTool(AtomicTool):
    """Discover data files in the workdir and return a categorized listing."""
    name = "data_discovery"
    description = "Discover and categorize data files (train, test, sample_submission, etc.) in the workdir."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Base directory (default: workdir)"},
        },
    }
    output_schema = {"type": "object"}
    is_read_only = True
    is_destructive = False
    requires_network = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        from planner import discover_data_files
        base = Path(args.get("path", "")) if args.get("path") else ctx.workdir
        if not base.is_absolute():
            base = ctx.workdir / base
        try:
            base = ctx.check_path_read(base)
        except Exception as exc:
            return ToolResult.fail(str(exc), error_code=ErrorCode.PERMISSION_DENIED)
        files = discover_data_files(base)
        summary = {k: [str(p.relative_to(base)) for p in v] for k, v in files.items()}
        return ToolResult.success(data=summary, stdout_preview=json.dumps(summary, indent=2)[:2000])


class DataSummarizeTool(AtomicTool):
    """Summarize a data file and return compact schema/stats."""
    name = "data_summarize"
    description = "Summarize a CSV/JSON data file: schema, head rows, shape, nulls."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the data file"},
            "max_rows": {"type": "integer", "description": "Max preview rows (default 5)"},
        },
        "required": ["path"],
    }
    output_schema = {"type": "object"}
    is_read_only = True
    is_destructive = False
    requires_network = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        from context_manager import summarize_csv, summarize_json, summarize_file
        raw_path = args.get("path", "")
        path = Path(raw_path)
        if not path.is_absolute():
            path = ctx.workdir / path
        try:
            path = ctx.check_path_read(path)
        except Exception as exc:
            return ToolResult.fail(str(exc), error_code=ErrorCode.PERMISSION_DENIED)
        if not path.exists():
            return ToolResult.fail(f"file not found: {path}", error_code=ErrorCode.FILESYSTEM_ERROR)
        summary = summarize_file(path)
        return ToolResult.success(data=summary, stdout_preview=json.dumps(summary, indent=2)[:2000])


class SubmissionGenTool(AtomicTool):
    """Generate a submission.csv, either from predictions or as a baseline."""
    name = "submission_gen"
    description = "Generate a submission.csv file. If predictions are provided, use them; otherwise create a baseline."
    input_schema = {
        "type": "object",
        "properties": {
            "sample_path": {"type": "string", "description": "Path to sample_submission.csv"},
            "output_path": {"type": "string", "description": "Path for the output submission.csv"},
            "predictions_path": {"type": "string", "description": "Optional path to predictions CSV"},
            "strategy": {"type": "string", "description": "Baseline strategy: auto, majority, mean, constant"},
        },
        "required": ["sample_path", "output_path"],
    }
    output_schema = {"type": "object"}
    is_read_only = False
    is_destructive = False
    requires_network = False

    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        from recovery import create_baseline_submission
        sample_path = Path(args["sample_path"])
        output_path = Path(args["output_path"])
        if not output_path.is_absolute():
            output_path = ctx.out_dir / output_path
        try:
            output_path = ctx.check_path_write(output_path)
        except Exception as exc:
            return ToolResult.fail(str(exc), error_code=ErrorCode.PERMISSION_DENIED)
        strategy = args.get("strategy", "auto")
        result = create_baseline_submission(sample_path, output_path, strategy=strategy)
        if result.get("success"):
            return ToolResult.success(
                data=result,
                stdout_preview=f"Generated submission with strategy '{strategy}': {result.get('rows_written')} rows",
                artifacts={"submission.csv": output_path},
            )
        return ToolResult.fail(
            result.get("error", "submission generation failed"),
            error_code=ErrorCode.ARTIFACT_ERROR,
        )


def get_custom_tools() -> list[AtomicTool]:
    return [DataDiscoveryTool(), DataSummarizeTool(), SubmissionGenTool()]
