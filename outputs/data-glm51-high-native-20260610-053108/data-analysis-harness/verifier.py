"""Verifier: validate artifacts against domain contracts.

Checks submission.csv schema, report quality, and required artifacts.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Optional


def validate_submission(
    sample_path: Path,
    submission_path: Path,
) -> dict[str, Any]:
    """Validate submission.csv matches sample_submission.csv schema."""
    failures: list[str] = []
    hints: list[str] = []
    details: dict[str, Any] = {}

    if not submission_path.exists():
        return {"passed": False, "failures": ["submission.csv not found"], "hints": ["Generate submission.csv"]}

    try:
        sample_cols, sample_rows = _read_csv(sample_path)
        sub_cols, sub_rows = _read_csv(submission_path)
    except Exception as exc:
        return {"passed": False, "failures": [f"error reading CSVs: {exc}"], "hints": []}

    details["sample_columns"] = sample_cols
    details["submission_columns"] = sub_cols
    details["sample_rows"] = len(sample_rows)
    details["submission_rows"] = len(sub_rows)

    if sample_cols != sub_cols:
        failures.append("submission columns do not match sample columns")
        hints.append(f"Expected columns: {sample_cols}, got: {sub_cols}")

    if len(sample_rows) != len(sub_rows):
        failures.append(f"row count mismatch: sample={len(sample_rows)}, submission={len(sub_rows)}")
        hints.append("Ensure submission has the same number of rows as the sample")

    if sample_cols and sample_rows and sub_rows:
        id_col = sample_cols[0]
        sample_ids = [r.get(id_col, "") for r in sample_rows]
        sub_ids = [r.get(id_col, "") for r in sub_rows]
        if sample_ids != sub_ids:
            failures.append("ID column values/order do not match sample")
            hints.append("Keep the identifier column unchanged from the sample")

    # Check boolean columns
    for col in sample_cols[1:]:
        sample_vals = {str(r.get(col, "")).strip().lower() for r in sample_rows if str(r.get(col, "")).strip()}
        if sample_vals and sample_vals.issubset({"true", "false"}):
            bad = [str(r.get(col, "")) for r in sub_rows
                   if str(r.get(col, "")).strip().lower() not in {"true", "false", ""}]
            if bad:
                failures.append(f"column '{col}' should be True/False, found: {bad[:3]}")
                hints.append(f"Output literal True/False for column '{col}'")

    return {"passed": not failures, "failures": failures, "hints": hints, "details": details}


def validate_report(report_path: Path, *, min_numbers: int = 2) -> dict[str, Any]:
    """Validate that a REPORT.md has real content, not just templates."""
    failures: list[str] = []
    hints: list[str] = []

    if not report_path.exists():
        return {"passed": False, "failures": ["REPORT.md not found"], "hints": ["Write REPORT.md"]}

    try:
        text = report_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"passed": False, "failures": [f"cannot read report: {exc}"], "hints": []}

    words = re.findall(r"\b[\w'-]+\b", text)
    if len(words) < 50:
        failures.append("report is too short")
        hints.append("Write substantive content with analysis findings")

    numbers = re.findall(r"[-+]?\d+(?:\.\d+)?%?", text)
    if len(numbers) < min_numbers:
        failures.append("report lacks concrete numeric results")
        hints.append("Include computed metrics, tables, or quantitative decisions")

    # Check for template-only content
    template_markers = ["step 1", "step 2", "placeholder", "todo", "tbd", "not implemented"]
    text_lower = text.lower()
    template_count = sum(1 for m in template_markers if m in text_lower)
    if template_count >= 3:
        failures.append("report appears to be a template, not real analysis")
        hints.append("Replace template steps with actual analysis and findings")

    # Check for tables (entity-level data)
    has_table = "|" in text or "-|" in text
    has_list = bool(re.search(r"^\s*[-*]\s", text, re.MULTILINE))
    if not has_table and not has_list and len(words) > 100:
        # Long text without any structured content might be lacking
        pass

    return {"passed": not failures, "failures": failures, "hints": hints}


def validate_artifacts(
    out_dir: Path,
    *,
    needs_submission: bool = False,
    sample_submission_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Run all artifact validations and return a combined result."""
    all_failures: list[str] = []
    all_hints: list[str] = []
    results: dict[str, Any] = {}

    report_path = out_dir / "REPORT.md"
    report_result = validate_report(report_path)
    results["report"] = report_result
    all_failures.extend(report_result["failures"])
    all_hints.extend(report_result["hints"])

    if needs_submission and sample_submission_path and sample_submission_path.exists():
        sub_path = out_dir / "submission.csv"
        sub_result = validate_submission(sample_submission_path, sub_path)
        results["submission"] = sub_result
        all_failures.extend(sub_result["failures"])
        all_hints.extend(sub_result["hints"])

    return {
        "passed": not all_failures,
        "failures": all_failures,
        "hints": all_hints,
        "results": results,
    }


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return columns, rows
