#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_TEMPLATE = "docker.io/jefzda/sweap-images:{dockerhub_tag}"
DEFAULT_TARGET_REPO = "hub.byted.org/harness_evolve/swepro_direct"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("ok") and row.get("instance_id"):
            done.add(str(row["instance_id"]))
    return done


def slug(value: str, max_len: int = 64) -> str:
    text = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-")
    return (text or "unknown")[:max_len]


def target_tag(row: dict[str, Any], index: int) -> str:
    instance_id = str(row.get("instance_id") or f"row-{index}")
    digest = hashlib.sha1(instance_id.encode("utf-8")).hexdigest()[:12]
    family = slug(str(row.get("repo_family") or row.get("repo") or instance_id), 36)
    return f"swepro-{index:04d}-{family}-{digest}"[:96]


def source_image(row: dict[str, Any], template: str) -> str:
    if "{dockerhub_tag}" in template:
        tag = str(row.get("dockerhub_tag") or "").strip()
        if not tag:
            raise ValueError(f"missing dockerhub_tag for {row.get('instance_id')}")
        return template.format(dockerhub_tag=tag)
    return str(row.get("source_image") or "").strip()


def run(cmd: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror SWE Pro official per-instance images into an internal registry. "
            "The official source is jefzda/sweap-images:<dockerhub_tag>; older "
            "docker.io/swebench/* rows are not used by default because they are not "
            "publicly pullable."
        )
    )
    parser.add_argument("--input", type=Path, default=Path("configs/swepro_external_images.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("logs/platform_jobs/swepro_internal_images.jsonl"))
    parser.add_argument("--target-repo", default=DEFAULT_TARGET_REPO)
    parser.add_argument("--source-template", default=DEFAULT_SOURCE_TEMPLATE)
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-index", type=int, default=1, help="1-based source row index to start from.")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pull-timeout", type=int, default=1800)
    parser.add_argument("--push-timeout", type=int, default=1800)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--remove-local", action="store_true", help="Remove local source/target image tags after a successful push.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    indexed_rows = [(i, row) for i, row in enumerate(rows, 1) if i >= args.start_index]
    if args.limit is not None:
        indexed_rows = indexed_rows[: args.limit]
    done = load_done(args.output) if args.resume else set()

    for index, row in indexed_rows:
        instance_id = str(row.get("instance_id") or f"row-{index}")
        if instance_id in done:
            print(f"[skip] {index}/{len(rows)} {instance_id}", flush=True)
            continue
        try:
            src = source_image(row, args.source_template)
        except ValueError as exc:
            append_jsonl(args.output, {"ok": False, "instance_id": instance_id, "error": str(exc)})
            print(f"[fail] {instance_id}: {exc}", flush=True)
            continue
        tag = target_tag(row, index)
        dst = f"{args.target_repo}:{tag}"
        result: dict[str, Any] = {
            "ok": False,
            "instance_id": instance_id,
            "repo": row.get("repo"),
            "repo_family": row.get("repo_family"),
            "dockerhub_tag": row.get("dockerhub_tag"),
            "source_image": src,
            "internal_image_url": dst,
            "target_tag": tag,
        }
        print(f"[mirror] {index}/{len(rows)} {instance_id}", flush=True)
        print(f"  src={src}", flush=True)
        print(f"  dst={dst}", flush=True)
        if args.dry_run:
            result["ok"] = True
            result["dry_run"] = True
            append_jsonl(args.output, result)
            continue

        pull = run(["docker", "pull", "--platform", args.platform, src], timeout=args.pull_timeout)
        result["pull_returncode"] = pull.returncode
        if pull.returncode != 0:
            result["pull_stderr"] = pull.stderr[-4000:]
            append_jsonl(args.output, result)
            print(f"[pull-fail] {instance_id}", flush=True)
            continue

        tag_proc = run(["docker", "tag", src, dst])
        result["tag_returncode"] = tag_proc.returncode
        if tag_proc.returncode != 0:
            result["tag_stderr"] = tag_proc.stderr[-4000:]
            append_jsonl(args.output, result)
            print(f"[tag-fail] {instance_id}", flush=True)
            continue

        push = run(["docker", "push", dst], timeout=args.push_timeout)
        result["push_returncode"] = push.returncode
        if push.returncode != 0:
            result["push_stderr"] = push.stderr[-4000:]
            append_jsonl(args.output, result)
            print(f"[push-fail] {instance_id}", flush=True)
            continue
        result["push_stdout_tail"] = push.stdout[-2000:]
        result["ok"] = True
        if args.remove_local:
            rm = run(["docker", "image", "rm", dst, src])
            result["remove_local_returncode"] = rm.returncode
            if rm.returncode != 0:
                result["remove_local_stderr"] = rm.stderr[-2000:]
        append_jsonl(args.output, result)
        print(f"[ok] {instance_id}", flush=True)
        if args.sleep:
            time.sleep(args.sleep)

    return 0


if __name__ == "__main__":
    sys.exit(main())
