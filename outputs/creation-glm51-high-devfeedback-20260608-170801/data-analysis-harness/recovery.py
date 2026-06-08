"""Recovery: failure recovery and fallback strategies for data analysis tasks.

Handles missing files, malformed data, failed model training,
and generates fallback baselines when modeling fails.
"""
from __future__ import annotations

import csv
import json
import traceback
from pathlib import Path
from typing import Any


def create_baseline_submission(
    sample_submission_path: Path,
    output_path: Path,
    train_path: Path | None = None,
    task_type: str | None = None,
) -> bool:
    """Create a baseline submission when modeling fails.

    Uses simple heuristics:
    - Classification: majority class from training data or most common sample value
    - Regression: mean from training data or 0
    - Unknown: majority class / 0

    Returns True if submission was created successfully.
    """
    if not sample_submission_path.exists():
        return False

    try:
        sample_cols, sample_rows = _read_csv(sample_submission_path)
    except Exception:
        return False

    if not sample_cols or not sample_rows:
        return False

    id_col = sample_cols[0]
    target_cols = sample_cols[1:]

    # Compute baseline values
    baseline_values: dict[str, str] = {}

    # Try to get training data stats
    train_data: list[dict[str, str]] = []
    if train_path and train_path.exists():
        try:
            _, train_data = _read_csv(train_path)
        except Exception:
            pass

    for col in target_cols:
        # Check sample values for boolean
        sample_vals = {
            str(r.get(col, "")).strip().lower()
            for r in sample_rows
            if str(r.get(col, "")).strip()
        }

        if sample_vals <= {"true", "false"}:
            # Boolean target: majority class
            if train_data and col in train_data[0]:
                t_vals = [str(r.get(col, "")).strip() for r in train_data if str(r.get(col, "")).strip()]
                if t_vals:
                    true_count = sum(1 for v in t_vals if v.lower() == "true")
                    baseline_values[col] = "True" if true_count >= len(t_vals) / 2 else "False"
                else:
                    baseline_values[col] = "True"
            else:
                true_count = sum(1 for v in sample_vals if v == "true")
                baseline_values[col] = "True" if true_count >= len(sample_vals) / 2 else "False"

        elif sample_vals <= {"0", "1"}:
            # Binary 0/1
            if train_data and col in train_data[0]:
                t_vals = [str(r.get(col, "")).strip() for r in train_data if str(r.get(col, "")).strip()]
                if t_vals:
                    ones = sum(1 for v in t_vals if v == "1")
                    baseline_values[col] = "1" if ones >= len(t_vals) / 2 else "0"
                else:
                    baseline_values[col] = "0"
            else:
                baseline_values[col] = "0"

        else:
            # Regression or multiclass
            if train_data and col in train_data[0]:
                t_vals = []
                for r in train_data:
                    v = str(r.get(col, "")).strip()
                    try:
                        t_vals.append(float(v))
                    except ValueError:
                        pass
                if t_vals:
                    mean_val = sum(t_vals) / len(t_vals)
                    # Check if values are integers
                    if all(v == int(v) for v in t_vals):
                        baseline_values[col] = str(int(round(mean_val)))
                    else:
                        baseline_values[col] = str(round(mean_val, 4))
                else:
                    baseline_values[col] = "0"
            else:
                # Use mode from sample values
                from collections import Counter
                val_counts = Counter(str(r.get(col, "")).strip() for r in sample_rows if str(r.get(col, "")).strip())
                if val_counts:
                    baseline_values[col] = val_counts.most_common(1)[0][0]
                else:
                    baseline_values[col] = "0"

    # Write submission
    try:
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sample_cols)
            writer.writeheader()
            for row in sample_rows:
                out_row = {id_col: row[id_col]}
                for col in target_cols:
                    out_row[col] = baseline_values.get(col, "0")
                writer.writerow(out_row)
        return True
    except Exception:
        return False


def create_fallback_report(
    output_path: Path,
    prompt: str,
    data_summary: str,
    error_info: str | None = None,
) -> bool:
    """Create a minimal but valid REPORT.md when analysis partially fails."""
    try:
        parts = [
            "# Data Analysis Report",
            "",
            "## Problem Understanding",
            "",
            prompt[:2000],
            "",
            "## Data Overview",
            "",
            data_summary[:3000],
            "",
        ]

        if error_info:
            parts.extend([
                "## Errors Encountered",
                "",
                error_info[:2000],
                "",
                "## Limitations",
                "",
                "The analysis encountered errors and could not complete fully. "
                "Results are based on available data and fallback baselines.",
                "",
            ])
        else:
            parts.extend([
                "## Limitations",
                "",
                "This is a fallback report due to incomplete analysis.",
                "",
            ])

        output_path.write_text("\n".join(parts), encoding="utf-8")
        return True
    except Exception:
        return False


def safe_json_write(path: Path, data: Any) -> bool:
    """Safely write JSON data to a file."""
    try:
        path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV file and return (columns, rows)."""
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return columns, rows
