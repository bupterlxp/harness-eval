"""Context manager: data summarization, schema inference, and prompt packing.

Prevents raw huge DataFrames from being dumped into LLM prompts. Produces
compact summaries that fit within a token budget.
"""
from __future__ import annotations

import json
import csv
from pathlib import Path
from typing import Any, Optional


def summarize_csv(path: Path, max_rows: int = 5, max_cols: int = 30) -> dict[str, Any]:
    """Produce a compact summary of a CSV file: shape, dtypes, head, nulls."""
    if not path.exists():
        return {"error": f"file not found: {path}"}
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row)
            total_rows = i + 1 if rows else 0
            # Count total rows
            for _ in reader:
                total_rows += 1
    except Exception as exc:
        return {"error": str(exc)}

    # Limit columns shown
    shown_cols = columns[:max_cols]
    truncated_cols = len(columns) - max_cols if len(columns) > max_cols else 0

    head: list[dict[str, str]] = []
    for row in rows:
        filtered = {c: row.get(c, "") for c in shown_cols}
        head.append(filtered)

    return {
        "path": str(path.name),
        "shape": {"rows": total_rows, "columns": len(columns)},
        "columns": columns,
        "shown_columns": shown_cols,
        "truncated_columns": truncated_cols,
        "head": head,
    }


def summarize_json(path: Path, max_items: int = 5) -> dict[str, Any]:
    """Summarize a JSON file: type, keys/length, sample."""
    if not path.exists():
        return {"error": f"file not found: {path}"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        obj = json.loads(text)
    except Exception as exc:
        return {"error": str(exc)}

    if isinstance(obj, list):
        sample = obj[:max_items]
        return {
            "path": str(path.name),
            "type": "array",
            "length": len(obj),
            "sample": sample,
        }
    if isinstance(obj, dict):
        keys = list(obj.keys())[:50]
        sample = {k: obj[k] for k in keys[:max_items]}
        return {
            "path": str(path.name),
            "type": "object",
            "keys": keys,
            "num_keys": len(obj),
            "sample": sample,
        }
    return {"path": str(path.name), "type": type(obj).__name__, "value": str(obj)[:500]}


def summarize_file(path: Path) -> dict[str, Any]:
    """Auto-detect file type and summarize."""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        return summarize_csv(path)
    if suffix == ".json":
        return summarize_json(path)
    if suffix in (".parquet", ".xlsx"):
        return {"path": str(path.name), "note": "binary format; use python_exec to read"}
    if suffix in (".sqlite", ".db"):
        return {"path": str(path.name), "note": "database; use python_exec with sqlite3 to query"}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return {
            "path": str(path.name),
            "type": "text",
            "lines": len(lines),
            "preview": "\n".join(lines[:20]),
        }
    except Exception:
        return {"path": str(path.name), "type": "binary"}


def build_data_context(
    data_files: dict[str, list[Path]],
    *,
    max_summary_bytes: int = 20_000,
) -> str:
    """Build a compact text summary of all discovered data files for the LLM."""
    parts: list[str] = []
    budget = max_summary_bytes

    for category in ("train", "test", "sample_submission", "data", "readme", "instructions", "other"):
        files = data_files.get(category, [])
        if not files:
            continue
        parts.append(f"\n## {category.upper()} FILES ({len(files)})")
        for f in files:
            if budget <= 0:
                parts.append("... [context budget exceeded]")
                break
            summary = summarize_file(f)
            text = json.dumps(summary, ensure_ascii=False, indent=2)
            if len(text) > budget:
                text = text[:budget] + "\n... [truncated]"
            parts.append(text)
            budget -= len(text)

    return "\n".join(parts)


def parse_sample_submission(path: Path) -> dict[str, Any]:
    """Extract schema details from a sample_submission.csv."""
    if not path.exists():
        return {"error": f"sample submission not found: {path}"}
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except Exception as exc:
        return {"error": str(exc)}

    id_col = columns[0] if columns else ""
    target_cols = columns[1:] if len(columns) > 1 else []

    # Infer prediction type from target values
    prediction_type = "unknown"
    if target_cols and rows:
        vals = {str(rows[0].get(c, "")).strip().lower() for c in target_cols}
        if vals <= {"true", "false", "0", "1"}:
            prediction_type = "classification_binary"
        elif all(_is_float(rows[0].get(c, "")) for c in target_cols if rows[0].get(c, "")):
            prediction_type = "regression"
        else:
            prediction_type = "classification_multiclass"

    return {
        "columns": columns,
        "id_column": id_col,
        "target_columns": target_cols,
        "row_count": len(rows),
        "prediction_type": prediction_type,
        "sample_ids": [rows[i].get(id_col, "") for i in range(min(5, len(rows)))],
        "sample_values": [{c: rows[i].get(c, "") for c in target_cols} for i in range(min(3, len(rows)))],
    }


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
