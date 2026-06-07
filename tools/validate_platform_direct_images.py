#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"ak=[A-Za-z0-9_-]{16,}"),
    re.compile(r'"(?:GLM_API_KEY|EVAL_API_KEY|api_key|API_KEY)"\s*:\s*"[^"$][^"]{8,}"'),
]


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: invalid JSONL: {exc}") from exc
    return rows


def image_meta(row: dict[str, Any]) -> dict[str, Any]:
    job_def = row.get("jobDefVersion")
    if isinstance(job_def, dict) and isinstance(job_def.get("imageMeta"), dict):
        return job_def["imageMeta"]
    explicit = row.get("imageMeta") or row.get("image_meta")
    if isinstance(explicit, dict):
        return explicit
    return {
        "imageSource": row.get("imageSource") or row.get("image_source") or "",
        "imageVid": row.get("imageVid") or row.get("image_vid") or row.get("image") or "",
        "needBuild": row.get("needBuild") or row.get("need_build") or False,
        "icmName": row.get("icmName") or row.get("icm_name") or "",
        "icmVersion": row.get("icmVersion") or row.get("icm_version") or "",
    }


def find_secret_hits(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append(pattern.pattern)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate platform-native manifest/job JSONL uses direct imageVid images.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--expected-count", type=int, default=None)
    parser.add_argument("--check-direct-image", action="store_true")
    parser.add_argument("--check-no-secrets", action="store_true")
    args = parser.parse_args()

    rows = iter_jsonl(args.path)
    errors: list[str] = []
    if args.expected_count is not None and len(rows) != args.expected_count:
        errors.append(f"expected {args.expected_count} rows, found {len(rows)}")
    if args.check_direct_image:
        for idx, row in enumerate(rows, 1):
            meta = image_meta(row)
            if meta.get("imageSource") != "vid":
                errors.append(f"row {idx}: imageSource={meta.get('imageSource')!r}, expected 'vid'")
            if not str(meta.get("imageVid") or "").strip():
                errors.append(f"row {idx}: imageVid is empty")
            if meta.get("needBuild") is True:
                errors.append(f"row {idx}: needBuild must be false")
            if str(meta.get("icmName") or "").strip() or str(meta.get("icmVersion") or "").strip():
                errors.append(f"row {idx}: icmName/icmVersion must be empty for direct-image mode")
    if args.check_no_secrets:
        hits = find_secret_hits(args.path)
        for hit in hits:
            errors.append(f"secret-like pattern found: {hit}")
    if errors:
        print(f"FAILED {args.path}")
        for err in errors[:50]:
            print(f"- {err}")
        if len(errors) > 50:
            print(f"... {len(errors) - 50} more")
        return 2
    print(f"OK {args.path}: rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
