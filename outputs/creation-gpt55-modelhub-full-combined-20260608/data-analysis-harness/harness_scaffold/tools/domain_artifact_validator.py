from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool


class DomainArtifactValidatorTool(AtomicTool):
    name = "domain_artifact_validator"
    description = "Validate public domain artifact contracts before finalizing a generated harness run."
    input_schema = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "enum": ["code", "data_analysis", "writing", "research", "browser"]},
            "workdir": {"type": "string"},
            "out_dir": {"type": "string"},
        },
        "required": ["domain"],
    }
    output_schema = {"type": "object"}
    is_read_only = True

    async def run(self, ctx: RuntimeContext, args: dict[str, Any]) -> ToolResult:
        domain = str(args.get("domain") or ctx.task.domain or "")
        workdir = Path(str(args.get("workdir") or ctx.workdir))
        out_dir = Path(str(args.get("out_dir") or ctx.out_dir))
        result = validate_public_contract(domain, workdir, out_dir)
        artifact = ctx.artifact_store.put_json("domain_artifact_validation.json", result, kind="validation")
        return ToolResult.success(result, artifacts={"domain_artifact_validation": artifact})


def validate_public_contract(domain: str, workdir: Path, out_dir: Path) -> dict[str, Any]:
    files = [p for root in (workdir, out_dir) if root.exists() for p in root.rglob("*") if p.is_file()]
    names = {p.name.lower(): p for p in files}
    failures: list[str] = []
    hints: list[str] = []
    evidence: dict[str, Any] = {"file_count": len(files)}
    if domain == "data_analysis":
        reports = [p for p in files if p.name.lower() in {"report.md", "analysis.md", "analysis_summary.json"}]
        text = "\n".join(_read(p) for p in reports)
        if not reports:
            failures.append("missing data analysis report")
            hints.append("Write REPORT.md or analysis_summary.json with computed values.")
        elif len(re.findall(r"[-+]?\d+(?:\.\d+)?%?", text)) < 2:
            failures.append("data report has too few concrete numbers")
            hints.append("Include computed metrics, tables, or quantitative decisions.")
        if "sample_submission.csv" in names:
            sample = names["sample_submission.csv"]
            submission = names.get("submission.csv")
            if submission is None:
                failures.append("missing submission.csv for sample_submission.csv")
                hints.append("Create submission.csv with identical columns and ids.")
            else:
                failures.extend(_check_submission(sample, submission, hints, evidence))
    elif domain == "writing":
        text_files = [p for p in files if p.name.lower() in {"story.md", "final.md", "response.md", "final_answer.md"}]
        text = "\n".join(_read(p) for p in text_files)
        words = re.findall(r"\b[\w'-]+\b", text)
        if len(words) < 150:
            failures.append("writing final artifact is missing or too short")
            hints.append("Write the final user-facing prose to a markdown artifact.")
    elif domain == "research":
        text = "\n".join(_read(p) for p in files if p.name.lower() in {"report.md", "response.md", "answer.md", "evidence.json"})
        if not re.search(r"https?://|source|citation|\\[[0-9]+\\]", text.lower()):
            failures.append("research artifact lacks source/citation evidence")
            hints.append("Record evidence snippets, source URLs, or citation ids.")
    elif domain == "browser":
        text = "\n".join(_read(p) for p in files if p.suffix.lower() in {".json", ".jsonl", ".md"})
        if not re.search(r"navigate|click|type|fill|extract|state", text.lower()):
            failures.append("browser artifact lacks action/state trace")
            hints.append("Record browser actions and final extracted result.")
    elif domain == "code":
        text = "\n".join(_read(p) for p in files if p.name.lower() in {"result.json", "metadata.json", "commands.log", "test.log"} or p.suffix.lower() in {".diff", ".patch"})
        if not re.search(r"diff|patch|changed_files", text.lower()):
            failures.append("code artifact lacks diff/changed_files evidence")
            hints.append("Record changed_files and a patch/diff artifact.")
        if not re.search(r"pytest|test|verifier|commands_run", text.lower()):
            failures.append("code artifact lacks verifier/test evidence")
            hints.append("Run or record a real verifier command when possible.")
    else:
        failures.append(f"unsupported domain: {domain}")
    return {"passed": not failures, "failures": failures, "repair_hints": hints, "evidence": evidence}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:200_000]
    except Exception:
        return ""


def _check_submission(sample: Path, submission: Path, hints: list[str], evidence: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    with sample.open(newline="", encoding="utf-8", errors="replace") as handle:
        sample_reader = csv.DictReader(handle)
        sample_cols = list(sample_reader.fieldnames or [])
        sample_rows = [dict(row) for row in sample_reader]
    with submission.open(newline="", encoding="utf-8", errors="replace") as handle:
        sub_reader = csv.DictReader(handle)
        sub_cols = list(sub_reader.fieldnames or [])
        sub_rows = [dict(row) for row in sub_reader]
    evidence.update({"sample_columns": sample_cols, "submission_columns": sub_cols, "sample_rows": len(sample_rows), "submission_rows": len(sub_rows)})
    if sample_cols != sub_cols:
        failures.append("submission.csv columns do not match sample_submission.csv")
        hints.append("Use exactly the public sample_submission columns in order.")
    if len(sample_rows) != len(sub_rows):
        failures.append("submission.csv row count does not match sample_submission.csv")
        hints.append("Preserve every sample row.")
    if sample_cols and sample_rows and sub_rows and [r.get(sample_cols[0], "") for r in sample_rows] != [r.get(sample_cols[0], "") for r in sub_rows]:
        failures.append("submission.csv id column order/content differs from sample_submission.csv")
        hints.append("Keep the identifier column unchanged.")
    for col in sample_cols[1:]:
        sample_values = {str(row.get(col, "")).strip().lower() for row in sample_rows if str(row.get(col, "")).strip()}
        if sample_values and sample_values.issubset({"true", "false"}):
            bad = [str(row.get(col, "")).strip() for row in sub_rows if str(row.get(col, "")).strip().lower() not in {"true", "false"}]
            if bad:
                failures.append(f"column {col} must use True/False labels, not values like {bad[:3]}")
                hints.append(f"Output literal True/False values for {col}.")
    return failures


def get_tools() -> list[AtomicTool]:
    return [DomainArtifactValidatorTool()]
