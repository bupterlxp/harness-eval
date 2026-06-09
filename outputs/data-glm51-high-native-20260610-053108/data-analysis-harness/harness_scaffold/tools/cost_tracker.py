"""Lightweight cost/token/tool-call accounting atom.

The scaffold cannot know every provider's exact accounting, but generated
harnesses can call this tool whenever they make an LLM/tool step. It appends
raw events and maintains a simple aggregate file for later BMK analysis.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode
from ..core.schemas import ToolResult
from .base import AtomicTool


class CostTrackerTool(AtomicTool):
    name = "cost_tracker"
    description = "Append a generation/eval/repair cost event and update aggregate cost_metrics.json."
    input_schema = {
        "type": "object",
        "properties": {
            "phase": {"type": "string", "enum": ["generation", "repair", "eval", "tool", "other"]},
            "event": {"type": "string"},
            "model": {"type": "string"},
            "prompt_tokens": {"type": "integer", "minimum": 0},
            "completion_tokens": {"type": "integer", "minimum": 0},
            "reasoning_tokens": {"type": "integer", "minimum": 0},
            "tool_calls": {"type": "integer", "minimum": 0},
            "interactions": {"type": "integer", "minimum": 0},
            "elapsed_seconds": {"type": "number", "minimum": 0},
            "metadata": {"type": "object"},
            "events_path": {"type": "string", "default": "cost_events.jsonl"},
            "summary_path": {"type": "string", "default": "cost_metrics.json"},
        },
        "required": ["phase", "event"],
    }
    is_read_only = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        phase = str(args.get("phase") or "").strip()
        event = str(args.get("event") or "").strip()
        if not phase or not event:
            return ToolResult.fail(
                "cost_tracker requires non-empty phase and event",
                error_code=ErrorCode.CONTRACT_ERROR,
                stage=self.name,
            )
        record = {
            "timestamp": time.time(),
            "phase": phase,
            "event": event,
            "model": args.get("model"),
            "prompt_tokens": _as_int(args.get("prompt_tokens")),
            "completion_tokens": _as_int(args.get("completion_tokens")),
            "reasoning_tokens": _as_int(args.get("reasoning_tokens")),
            "tool_calls": _as_int(args.get("tool_calls")),
            "interactions": _as_int(args.get("interactions")),
            "elapsed_seconds": _as_float(args.get("elapsed_seconds")),
            "metadata": args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
        }
        record["total_tokens"] = record["prompt_tokens"] + record["completion_tokens"] + record["reasoning_tokens"]

        events_path = _resolve_write_path(ctx, str(args.get("events_path") or "cost_events.jsonl"))
        summary_path = _resolve_write_path(ctx, str(args.get("summary_path") or "cost_metrics.json"))
        ctx.check_path_write(events_path)
        ctx.check_path_write(summary_path)
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        summary = _read_summary(summary_path)
        summary["events"] = int(summary.get("events") or 0) + 1
        summary["total_prompt_tokens"] = int(summary.get("total_prompt_tokens") or 0) + record["prompt_tokens"]
        summary["total_completion_tokens"] = int(summary.get("total_completion_tokens") or 0) + record["completion_tokens"]
        summary["total_reasoning_tokens"] = int(summary.get("total_reasoning_tokens") or 0) + record["reasoning_tokens"]
        summary["total_tokens"] = int(summary.get("total_tokens") or 0) + record["total_tokens"]
        summary["total_tool_calls"] = int(summary.get("total_tool_calls") or 0) + record["tool_calls"]
        summary["total_interactions"] = int(summary.get("total_interactions") or 0) + record["interactions"]
        summary["total_elapsed_seconds"] = float(summary.get("total_elapsed_seconds") or 0.0) + record["elapsed_seconds"]
        by_phase = summary.setdefault("by_phase", {})
        if not isinstance(by_phase, dict):
            by_phase = {}
            summary["by_phase"] = by_phase
        phase_summary = by_phase.setdefault(phase, {"events": 0, "tokens": 0, "tool_calls": 0, "elapsed_seconds": 0.0})
        phase_summary["events"] = int(phase_summary.get("events") or 0) + 1
        phase_summary["tokens"] = int(phase_summary.get("tokens") or 0) + record["total_tokens"]
        phase_summary["tool_calls"] = int(phase_summary.get("tool_calls") or 0) + record["tool_calls"]
        phase_summary["elapsed_seconds"] = float(phase_summary.get("elapsed_seconds") or 0.0) + record["elapsed_seconds"]
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        return ToolResult.success(
            data={"event": record, "summary": summary},
            artifacts={"events": events_path, "summary": summary_path},
        )


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _read_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def get_tools() -> list[AtomicTool]:
    return [CostTrackerTool()]


def _resolve_write_path(ctx: RuntimeContext, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return ctx.out_dir / path
