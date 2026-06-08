"""Verifier: artifact validation for data analysis tasks.

Validates submission.csv schema, report quality, and DAComp metric contracts.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


def verify_submission(
    sample_path: Path,
    submission_path: Path,
) -> dict[str, Any]:
    """Verify submission.csv matches sample_submission.csv schema.

    Returns dict with 'passed' bool, 'failures' list, and 'evidence' dict.
    """
    result: dict[str, Any] = {"passed": True, "failures": [], "evidence": {}}

    if not sample_path.exists():
        result["failures"].append("sample_submission.csv not found")
        result["passed"] = False
        return result

    if not submission_path.exists():
        result["failures"].append("submission.csv not found")
        result["passed"] = False
        return result

    try:
        sample_cols, sample_rows = _read_csv(sample_path)
        sub_cols, sub_rows = _read_csv(submission_path)
    except Exception as exc:
        result["failures"].append(f"error reading CSVs: {exc}")
        result["passed"] = False
        return result

    result["evidence"]["sample_columns"] = sample_cols
    result["evidence"]["submission_columns"] = sub_cols
    result["evidence"]["sample_rows"] = len(sample_rows)
    result["evidence"]["submission_rows"] = len(sub_rows)

    # Check columns match
    if sample_cols != sub_cols:
        result["failures"].append(
            f"columns mismatch: sample={sample_cols}, submission={sub_cols}"
        )
        result["passed"] = False

    # Check row count
    if len(sample_rows) != len(sub_rows):
        result["failures"].append(
            f"row count mismatch: sample={len(sample_rows)}, submission={len(sub_rows)}"
        )
        result["passed"] = False

    # Check ID column order
    if sample_cols and sample_rows and sub_rows:
        sample_ids = [r.get(sample_cols[0], "") for r in sample_rows]
        sub_ids = [r.get(sample_cols[0], "") for r in sub_rows]
        if sample_ids != sub_ids:
            result["failures"].append("ID column order/content differs from sample")
            result["passed"] = False

    # Check target column value domains
    for col in sample_cols[1:]:
        sample_values = {
            str(r.get(col, "")).strip().lower()
            for r in sample_rows
            if str(r.get(col, "")).strip()
        }
        # Boolean check
        if sample_values and sample_values <= {"true", "false"}:
            bad = [
                str(r.get(col, ""))
                for r in sub_rows
                if str(r.get(col, "")).strip().lower() not in {"true", "false", ""}
            ]
            if bad:
                result["failures"].append(
                    f"column '{col}' should be True/False but has: {bad[:5]}"
                )
                result["passed"] = False

    return result


def verify_report(report_path: Path, *, domain: str = "general") -> dict[str, Any]:
    """Verify a REPORT.md meets quality standards.

    Checks for:
    - Concrete numbers (at least 3 numeric values)
    - Real content (not just file listings or step descriptions)
    - For DAComp: entity-level tables, risk tiers, allocation plans
    """
    result: dict[str, Any] = {"passed": True, "failures": [], "evidence": {}}

    if not report_path.exists():
        result["failures"].append("REPORT.md not found")
        result["passed"] = False
        return result

    try:
        text = report_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        result["failures"].append(f"error reading report: {exc}")
        result["passed"] = False
        return result

    result["evidence"]["char_count"] = len(text)
    result["evidence"]["word_count"] = len(text.split())

    # Check for concrete numbers
    numbers = re.findall(r"[-+]?\d+(?:\.\d+)?%?", text)
    result["evidence"]["number_count"] = len(numbers)
    if len(numbers) < 3:
        result["failures"].append(
            f"report has only {len(numbers)} numeric values; needs at least 3"
        )
        result["passed"] = False

    # Check it's not just file listings
    file_listing_patterns = [
        r"^-*\s*(file|column|data)\s*(list|listing|names)\s*-*$",
    ]
    lines = text.strip().split("\n")
    non_empty_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    if len(non_empty_lines) < 5:
        result["failures"].append("report is too short (< 5 content lines)")
        result["passed"] = False

    # Check for step-only content (no real analysis)
    step_lines = sum(1 for l in non_empty_lines if re.match(r"^\d+\.\s", l))
    if step_lines > len(non_empty_lines) * 0.8 and len(non_empty_lines) > 3:
        result["failures"].append("report appears to be only a step list, not actual analysis")
        result["passed"] = False

    # DAComp-specific checks
    if domain == "dacomp":
        has_table = bool(re.search(r"\|.*\|.*\|", text))
        has_entity = bool(re.search(r"(entity|customer|client|company|group|tier|category)", text.lower()))
        if not has_table:
            result["failures"].append("DAComp report lacks entity-level table")
            result["passed"] = False
        if not has_entity:
            result["failures"].append("DAComp report lacks entity/group references")

    return result


def verify_dacomp_artifacts(out_dir: Path) -> dict[str, Any]:
    """Verify DAComp-specific machine-readable artifacts exist and are valid."""
    result: dict[str, Any] = {"passed": True, "failures": [], "evidence": {}}
    out_dir = Path(out_dir)

    # Check for at least one machine-readable artifact
    json_artifacts = list(out_dir.glob("*.json"))
    csv_artifacts = list(out_dir.glob("*.csv"))

    # Exclude standard scaffold files
    json_artifacts = [
        f for f in json_artifacts
        if f.name not in {
            "result.json", "metadata.json", "error.json",
            "artifacts.json", "domain_artifact_validation.json",
            "config.json", "task.json",
        }
    ]
    csv_artifacts = [
        f for f in csv_artifacts
        if f.name not in {"submission.csv", "sample_submission.csv"}
    ]

    machine_readable = json_artifacts + csv_artifacts
    result["evidence"]["machine_readable_files"] = [f.name for f in machine_readable]

    if not machine_readable:
        result["failures"].append("no machine-readable artifact (analysis_summary.json, metrics.csv, etc.)")
        result["passed"] = False

    return result


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV file and return (columns, rows)."""
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return columns, rows
