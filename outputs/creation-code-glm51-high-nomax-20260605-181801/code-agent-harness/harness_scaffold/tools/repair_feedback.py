"""Turn public validation failures into stable repair feedback.

This is a small utility atom for generated harnesses that want to run their own
public-contract repair loop. It does not know hidden labels or benchmark scores;
it only normalizes static/CLI/toy/artifact-contract failures into concrete
next-step hints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.context import RuntimeContext
from ..core.errors import ErrorCode
from ..core.schemas import ToolResult
from .base import AtomicTool


class RepairFeedbackTool(AtomicTool):
    name = "repair_feedback"
    description = (
        "Normalize public validator failures into a stable JSON repair plan. "
        "Accepts an inline report or a report_path and writes repair_feedback.json."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "report": {"type": "object"},
            "report_path": {"type": "string"},
            "out_path": {"type": "string", "default": "repair_feedback.json"},
        },
    }
    is_read_only = False

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        report = args.get("report")
        if report is None and args.get("report_path"):
            report_path = _resolve_read_path(ctx, str(args["report_path"]))
            ctx.check_path_read(report_path)
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return ToolResult.fail(
                    f"invalid JSON report: {exc}",
                    error_code=ErrorCode.ARTIFACT_ERROR,
                    stage=self.name,
                )
        if not isinstance(report, dict):
            return ToolResult.fail(
                "repair_feedback requires report object or report_path",
                error_code=ErrorCode.CONTRACT_ERROR,
                stage=self.name,
            )

        feedback = build_repair_feedback(report)
        out_path = _resolve_write_path(ctx, str(args.get("out_path") or "repair_feedback.json"))
        ctx.check_path_write(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")
        return ToolResult.success(
            data=feedback,
            artifacts={"repair_feedback": out_path},
        )


def build_repair_feedback(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    hints: list[str] = []

    def add_failure(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list):
            for item in value:
                add_failure(item)
            return
        text = str(value).strip()
        if text and text not in failures:
            failures.append(text)

    add_failure(report.get("gate_failure_reason"))
    add_failure(report.get("errors"))
    add_failure(report.get("missing_dependencies"))

    toy = report.get("toy")
    if isinstance(toy, dict):
        add_failure(toy.get("failure_reasons"))
        contract = toy.get("artifact_contract")
        if isinstance(contract, dict):
            add_failure(contract.get("failures"))
            for hint in contract.get("repair_hints") or []:
                text = str(hint).strip()
                if text and text not in hints:
                    hints.append(text)

    text_blob = "\n".join(failures).lower()
    if "submission.csv" in text_blob:
        hints.append("Generate a submission.csv matching the public sample_submission.csv exactly: same columns, row count, id order, and label dtype.")
    if "true/false" in text_blob or "bool" in text_blob:
        hints.append("Use literal boolean labels such as True/False when the sample submission uses boolean labels; do not output probabilities.")
    if "changed" in text_blob or "diff" in text_blob or "patch" in text_blob:
        hints.append("For code tasks, perform a real file edit or patch and log changed_files plus commands_run/test/verifier evidence.")
    if "template" in text_blob or "numeric" in text_blob or "report" in text_blob:
        hints.append("For data tasks, read the input data and output structured numeric decisions, tables, and a non-template report.")
    if "evidence" in text_blob or "citation" in text_blob:
        hints.append("For research tasks, include answer text plus source/evidence trace with citation markers.")
    if "action" in text_blob or "browser" in text_blob:
        hints.append("For browser tasks, record action_trace and final state/result evidence.")
    if "final text" in text_blob or "writing" in text_blob:
        hints.append("For writing tasks, write the final user-facing prose artifact, not just runtime logs or metadata.")

    deduped_hints: list[str] = []
    for hint in hints:
        if hint not in deduped_hints:
            deduped_hints.append(hint)

    return {
        "passed": not failures,
        "failures": failures,
        "repair_hints": deduped_hints,
        "repair_prompt": build_repair_prompt(failures, deduped_hints),
    }


def build_repair_prompt(failures: list[str], hints: list[str]) -> str:
    return "\n".join(
        [
            "Repair the generated harness using only the public validation feedback.",
            "Do not use hidden benchmark answers, hidden labels, or hidden scores.",
            "",
            "Failures:",
            *[f"- {failure}" for failure in failures],
            "",
            "Repair hints:",
            *[f"- {hint}" for hint in hints],
            "",
            "Implement the fix in the runnable harness files and keep the public CLI/result/trajectory contract intact.",
        ]
    )


def get_tools() -> list[AtomicTool]:
    return [RepairFeedbackTool()]


def _resolve_read_path(ctx: RuntimeContext, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    work_candidate = ctx.workdir / path
    if work_candidate.exists():
        return work_candidate
    return ctx.out_dir / path


def _resolve_write_path(ctx: RuntimeContext, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return ctx.out_dir / path
