"""Recovery: failure recovery, baseline fallbacks, and best-effort artifacts.

When the primary analysis or modeling path fails, these functions provide
fallback strategies so the harness always produces some output.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Optional


def create_baseline_submission(
    sample_submission_path: Path,
    output_path: Path,
    strategy: str = "auto",
) -> dict[str, Any]:
    """Create a baseline submission.csv when modeling fails.

    Strategies:
      - majority: use the most frequent value per target column from training data
      - mean: use the mean of target column
      - constant: use a constant value (first non-ID value from sample)
      - auto: pick based on prediction type
    """
    if not sample_submission_path.exists():
        return {"success": False, "error": f"sample_submission not found: {sample_submission_path}"}

    try:
        with sample_submission_path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    if not columns or not rows:
        return {"success": False, "error": "empty sample_submission"}

    id_col = columns[0]
    target_cols = columns[1:]

    # Determine prediction type
    is_bool = False
    is_numeric = False
    if target_cols:
        vals = set()
        for r in rows[:100]:
            for c in target_cols:
                v = str(r.get(c, "")).strip().lower()
                if v:
                    vals.add(v)
        if vals <= {"true", "false", "0", "1"}:
            is_bool = True
        elif all(_safe_float(v) is not None for v in vals if v):
            is_numeric = True

    # Pick strategy
    if strategy == "auto":
        if is_bool:
            strategy = "majority"
        elif is_numeric:
            strategy = "mean"
        else:
            strategy = "constant"

    # Compute baseline values
    baseline_values: dict[str, str] = {}
    for col in target_cols:
        col_vals = [str(r.get(col, "")).strip() for r in rows if str(r.get(col, "")).strip()]
        if not col_vals:
            baseline_values[col] = "0"
            continue

        if strategy == "majority":
            from collections import Counter
            counts = Counter(col_vals)
            baseline_values[col] = counts.most_common(1)[0][0]
        elif strategy == "mean":
            nums = [_safe_float(v) for v in col_vals]
            nums = [n for n in nums if n is not None]
            if nums:
                baseline_values[col] = str(sum(nums) / len(nums))
            else:
                baseline_values[col] = col_vals[0]
        else:
            baseline_values[col] = col_vals[0]

    # Write baseline submission
    out_rows = []
    for row in rows:
        out_row = {id_col: row[id_col]}
        for col in target_cols:
            out_row[col] = baseline_values.get(col, "0")
        out_rows.append(out_row)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(out_rows)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "strategy": strategy,
        "rows_written": len(out_rows),
        "baseline_values": baseline_values,
    }


def create_minimal_report(
    output_path: Path,
    *,
    prompt: str = "",
    data_summary: str = "",
    error_msg: str = "",
    findings: list[str] | None = None,
) -> Path:
    """Create a minimal but valid REPORT.md with whatever info is available."""
    parts = ["# Data Analysis Report\n"]

    if prompt:
        parts.append(f"## Task\n{prompt}\n")

    if data_summary:
        parts.append(f"## Data Summary\n{data_summary}\n")

    if findings:
        parts.append("## Findings\n")
        for f in findings:
            parts.append(f"- {f}\n")
        parts.append("\n")

    if error_msg:
        parts.append(f"## Limitations\nAnalysis encountered issues: {error_msg}\n")

    parts.append("## Method\nBaseline/fallback analysis due to limited processing.\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    return output_path


def create_analysis_summary_json(
    output_path: Path,
    *,
    metrics: dict[str, Any] | None = None,
    data_info: dict[str, Any] | None = None,
    error_msg: str = "",
) -> Path:
    """Create a machine-readable analysis_summary.json."""
    summary: dict[str, Any] = {
        "status": "partial" if error_msg else "success",
        "metrics": metrics or {},
        "data_info": data_info or {},
    }
    if error_msg:
        summary["error"] = error_msg
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _safe_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None
