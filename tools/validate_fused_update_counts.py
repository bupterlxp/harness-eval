#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def strip_markdown_link(value: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value).strip()


def parse_summary_table(path: Path) -> list[dict[str, str | int]]:
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, str | int]] = []
    in_summary = False
    headers: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## 汇总") or line.lower().startswith("## summary"):
            in_summary = True
            continue
        if in_summary and line.startswith("## ") and not line.startswith("## 汇总"):
            break
        if not in_summary or not line.startswith("|"):
            continue
        cells = [strip_markdown_link(cell.strip()) for cell in line.strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if not headers:
            headers = [cell.strip().lower().replace(" ", "_") for cell in cells]
            continue
        data = dict(zip(headers, cells))
        if "harness" not in data or "fused_updates" not in data:
            continue
        try:
            fused_updates = int(str(data["fused_updates"]).strip())
        except ValueError as exc:
            raise SystemExit(f"Invalid fused_updates value in {path}: {data!r}") from exc
        rows.append(
            {
                "domain": str(data.get("domain", "")),
                "harness": str(data.get("harness", "")),
                "repo": str(data.get("repo", "")),
                "fused_updates": fused_updates,
            }
        )
    if not rows:
        raise SystemExit(f"No summary rows found in {path}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate per-harness fused update counts in five_domain_pr_fused_updates.md.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-per-harness", type=int, default=10)
    parser.add_argument("--format", choices=["table", "csv", "jsonl"], default="table")
    args = parser.parse_args()

    rows = parse_summary_table(args.path)
    violations = [row for row in rows if int(row["fused_updates"]) > args.max_per_harness]

    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=["domain", "harness", "repo", "fused_updates"])
        writer.writeheader()
        writer.writerows(rows)
    elif args.format == "jsonl":
        import json

        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(f"{'domain':<32} {'harness':<24} fused_updates")
        print("-" * 72)
        for row in rows:
            print(f"{str(row['domain'])[:32]:<32} {str(row['harness'])[:24]:<24} {row['fused_updates']}")

    if violations:
        print("\nViolations:", file=sys.stderr)
        for row in violations:
            print(f"- {row['domain']} / {row['harness']}: {row['fused_updates']} > {args.max_per_harness}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
