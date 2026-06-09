#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FIELDS = [
    "run_id",
    "benchmark",
    "instance_id",
    "repo",
    "repo_family",
    "harness_path",
    "task_work_dir",
    "harness_invocation",
    "harness_status",
    "eval_status",
    "score",
    "harness_run_tokens",
    "elapsed_sec",
    "stdout_path",
    "stderr_path",
    "raw_result_path",
]


def iter_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("shard_result.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    row["_source"] = str(path)
                    rows.append(row)
    for path in sorted(root.rglob("shard_result.json")):
        if path.with_suffix(".jsonl").exists():
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        row["_source"] = str(path)
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge platform-native BMK shard outputs.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out-jsonl", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path, required=True)
    args = parser.parse_args()

    rows = iter_rows(args.root)
    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.out_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with args.out_csv.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = FIELDS + ["_source"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    completed = [row for row in rows if str(row.get("eval_status", "")).startswith("success")]
    scored = [row for row in rows if row.get("score") is not None]
    avg_score = None
    if scored:
        avg_score = sum(float(row["score"]) for row in scored) / len(scored)
    print(
        json.dumps(
            {
                "rows": len(rows),
                "completed": len(completed),
                "scored": len(scored),
                "avg_score": avg_score,
                "out_jsonl": str(args.out_jsonl),
                "out_csv": str(args.out_csv),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

