#!/usr/bin/env python3
"""Compare creation quality across prompt/scaffold/repair runs.

The script accepts generation output directories, downstream eval result
directories, or a mix. It intentionally reports both conditional BMK score and
end-to-end yield indicators so repair/scaffold changes do not look better by
filtering out failed harnesses.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


FIELDS = [
    "run_label",
    "source_path",
    "source_type",
    "rows",
    "harnesses",
    "generation_success_rate",
    "syntax_pass_rate",
    "import_pass_rate",
    "cli_probe_pass_rate",
    "gate_pass_before_repair_rate",
    "gate_pass_after_repair_rate",
    "gate_yield",
    "downstream_success_rate",
    "adapter_failure_rate",
    "avg_score",
    "avg_end_to_end_score",
    "transfer_score",
    "avg_generation_tokens",
    "avg_harness_run_tokens",
    "avg_total_tokens",
    "avg_repair_rounds",
    "top_failure_modes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze creation quality across local runs.")
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Run spec as label=/path/to/run. Can point to generation output or eval_results/<run_id>.",
    )
    parser.add_argument("--output-dir", default="analysis_outputs/creation_quality")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = args.run or auto_specs()
    if not specs:
        raise SystemExit("No runs provided and no local summary files found.")

    summaries = []
    details: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        label, path = split_spec(spec)
        rows, source_type = load_rows(path)
        summary = summarize_rows(label, path, source_type, rows)
        summaries.append(summary)
        details[label] = rows

    csv_path = out_dir / "creation_quality_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in summaries:
            writer.writerow(row)

    report_path = out_dir / "creation_quality_report.md"
    report_path.write_text(render_report(summaries), encoding="utf-8")
    print(f"Wrote {csv_path}")
    print(f"Wrote {report_path}")


def auto_specs() -> list[str]:
    specs: list[str] = []
    for root in (Path("eval_results"), Path("outputs")):
        if not root.exists():
            continue
        for summary in root.rglob("summary.csv"):
            specs.append(f"{summary.parent.name}={summary.parent}")
    return specs[:12]


def split_spec(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        label, path = spec.split("=", 1)
        return label.strip() or Path(path).name, Path(path).expanduser()
    path = Path(spec).expanduser()
    return path.name, path


def load_rows(path: Path) -> tuple[list[dict[str, Any]], str]:
    if (path / "summary.csv").is_file():
        return read_csv(path / "summary.csv"), "eval_summary"
    generation_rows = load_generation_rows(path)
    if generation_rows:
        return generation_rows, "generation_output"
    summaries = list(path.rglob("summary.csv"))
    if summaries:
        rows: list[dict[str, Any]] = []
        for summary in summaries:
            rows.extend(read_csv(summary))
        return rows, "eval_summary_tree"
    return [], "unknown"


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_generation_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for meta_path in path.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            {
                "harness_task_id": meta.get("task_id") or meta_path.parent.name,
                "generation_status": meta.get("status"),
                "generation_model": meta.get("generation_model"),
                "creation_profile": meta.get("creation_profile"),
                "creation_attempts": meta.get("creation_attempts"),
                "repair_rounds": meta.get("repair_rounds"),
                "gate_pass_before_repair": meta.get("gate_pass_before_repair"),
                "gate_pass_after_repair": meta.get("gate_pass_after_repair"),
                "repair_failure_reasons": json.dumps(meta.get("repair_failure_reasons") or [], ensure_ascii=False),
                "selected_attempt_path": meta.get("selected_attempt_path"),
                "harness_path": str(meta_path.parent),
            }
        )
    return rows


def summarize_rows(label: str, path: Path, source_type: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    harnesses = len({str(row.get("harness_task_id") or row.get("harness_path") or i) for i, row in enumerate(rows)})
    adapter_failures = sum(1 for row in rows if str(row.get("adapter_status") or "").lower() == "adapter_failed")
    eval_success = sum(1 for row in rows if str(row.get("eval_status") or "").lower() == "success")
    repair_rounds = [to_float(row.get("repair_rounds")) for row in rows]
    repair_rounds = [x for x in repair_rounds if x is not None]
    transfer_scores = [
        to_float(row.get("end_to_end_score") or row.get("score"))
        for row in rows
        if str(row.get("generation_model") or "")
        and str(row.get("eval_model") or "")
        and str(row.get("generation_model") or "") != str(row.get("eval_model") or "")
    ]
    transfer_scores = [x for x in transfer_scores if x is not None]
    generation_tokens = [to_float(row.get("generation_tokens")) for row in rows]
    generation_tokens = [x for x in generation_tokens if x is not None]
    harness_tokens = [to_float(row.get("harness_run_tokens")) for row in rows]
    harness_tokens = [x for x in harness_tokens if x is not None]
    failure_modes = collect_failure_modes(rows)
    return {
        "run_label": label,
        "source_path": str(path),
        "source_type": source_type,
        "rows": total,
        "harnesses": harnesses,
        "generation_success_rate": rate(sum(1 for row in rows if str(row.get("generation_status") or "").lower() == "success"), total),
        "syntax_pass_rate": bool_rate(rows, "syntax_ok"),
        "import_pass_rate": bool_rate(rows, "import_ok"),
        "cli_probe_pass_rate": bool_rate(rows, "cli_probe_ok"),
        "gate_pass_before_repair_rate": bool_rate(rows, "gate_pass_before_repair"),
        "gate_pass_after_repair_rate": bool_rate(rows, "gate_pass_after_repair") or bool_rate(rows, "gate_pass"),
        "gate_yield": bool_rate(rows, "gate_pass"),
        "downstream_success_rate": rate(eval_success, total),
        "adapter_failure_rate": rate(adapter_failures, total),
        "avg_score": avg_float(row.get("score") for row in rows),
        "avg_end_to_end_score": avg_float(row.get("end_to_end_score") for row in rows),
        "transfer_score": round(statistics.mean(transfer_scores), 4) if transfer_scores else "",
        "avg_generation_tokens": round(statistics.mean(generation_tokens), 2) if generation_tokens else "",
        "avg_harness_run_tokens": round(statistics.mean(harness_tokens), 2) if harness_tokens else "",
        "avg_total_tokens": round(statistics.mean(generation_tokens + harness_tokens), 2)
        if generation_tokens or harness_tokens
        else "",
        "avg_repair_rounds": round(statistics.mean(repair_rounds), 4) if repair_rounds else "",
        "top_failure_modes": "; ".join(f"{key}={value}" for key, value in failure_modes.most_common(8)),
    }


def bool_rate(rows: list[dict[str, Any]], key: str) -> str:
    known = [parse_bool(row.get(key)) for row in rows if row.get(key) not in ("", None)]
    known = [value for value in known if value is not None]
    if not known:
        return ""
    return f"{sum(1 for value in known if value) / len(known):.4f}"


def rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return ""
    return f"{numerator / denominator:.4f}"


def avg_float(values: Any) -> str:
    floats = [value for value in (to_float(value) for value in values) if value is not None]
    if not floats:
        return ""
    return f"{statistics.mean(floats):.6g}"


def to_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in ("", None):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def collect_failure_modes(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    fields = [
        "gate_failure_reason",
        "repair_failure_reasons",
        "missing_dependencies",
        "eval_status",
        "adapter_status",
    ]
    for row in rows:
        for field in fields:
            text = str(row.get(field) or "").strip()
            if not text or text.lower() in {"success", "ready", "[]"}:
                continue
            for mode in normalize_failure_text(text):
                counter[mode] += 1
    return counter


def normalize_failure_text(text: str) -> list[str]:
    lowered = text.lower()
    patterns = [
        ("missing_dependency", r"missing|dependency|env:|path:|executable:"),
        ("adapter_failed", r"adapter_failed|unsupported_adapter"),
        ("invalid_submission", r"submission\.csv|sample_submission|true/false|boolean"),
        ("no_real_code_change", r"no patch|no diff|changed_files|verifier/test"),
        ("template_data_report", r"template|too few concrete numbers|numeric"),
        ("missing_writing_artifact", r"writing artifact|final writing|too short"),
        ("missing_evidence", r"evidence|citation|source"),
        ("missing_browser_trace", r"browser|action trace|final state"),
        ("cli_or_import_failure", r"cli|import|syntax"),
        ("eval_failed", r"\bfailed\b"),
    ]
    found = [name for name, pattern in patterns if re.search(pattern, lowered)]
    return found or [lowered[:80]]


def render_report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Creation Quality 对比报告",
        "",
        "说明：`score` 是 downstream BMK 条件分数；`end_to_end_score` 会把 gate 失败样本计入端到端收益，避免只看通过 gate 的少数样本。",
        "",
        "| Run | Source | Rows | Harnesses | Gen Success | Gate Before | Gate After | Eval Success | Avg Score | Avg E2E | Transfer | Gen tokens | Harness tokens | Failures |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {run_label} | {source_type} | {rows} | {harnesses} | {generation_success_rate} | "
            "{gate_pass_before_repair_rate} | {gate_pass_after_repair_rate} | {downstream_success_rate} | "
            "{avg_score} | {avg_end_to_end_score} | {transfer_score} | {avg_generation_tokens} | "
            "{avg_harness_run_tokens} | {top_failure_modes} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## 使用建议",
            "",
            "- 比较 prompt-only / scaffold / scaffold+repair 时，保持 meta harness、generation LLM、eval LLM、BMK subset 完全一致。",
            "- 先看 `Gate After` 和 `Eval Success`，再看 `Avg Score`；只看平均分会掩盖不可运行 harness 的失败率。",
            "- 若 `invalid_submission`、`no_real_code_change`、`template_data_report` 仍高，优先改 public contract 和 toy validator，而不是直接调 BMK 分数。",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
