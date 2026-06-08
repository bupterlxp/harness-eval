#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import requests


SUBMIT_URL_DEFAULT = "https://paas-gw.byted.org/openapi/v1/job_run/launch_by_def"


def now_ts() -> int:
    return int(time.time())


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")


def get_xjwt(session: requests.Session) -> str:
    env_token = os.environ.get("SEED_X_JWT")
    if env_token:
        return env_token
    sec_token_path = os.environ.get("SEC_TOKEN_PATH")
    if not sec_token_path or not Path(sec_token_path).exists():
        raise FileNotFoundError(f"SEC_TOKEN_PATH is invalid: {sec_token_path}")
    zti_token = Path(sec_token_path).read_text(encoding="utf-8").strip()
    if not zti_token:
        raise RuntimeError("SEC_TOKEN file is empty")
    response = session.get(
        "https://cloud.bytedance.net/auth/api/v1/jwt",
        headers={"X-ZTI-Token": zti_token},
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f"JWT request failed: {response.status_code}, {response.text[:1000]}")
    token = response.headers.get("x-jwt-token")
    if not token:
        raise RuntimeError("JWT request succeeded but x-jwt-token header is missing")
    return token


def submit_job(session: requests.Session, xjwt: str, job_body: dict[str, Any], submit_url: str) -> tuple[bool, Any]:
    response = session.post(
        submit_url,
        headers={
            "Domain": "seed_job",
            "content-type": "application/json",
            "x-jwt-token": xjwt,
        },
        json=job_body,
        timeout=60,
    )
    if response.status_code == 200:
        try:
            return True, response.json()
        except json.JSONDecodeError:
            return True, response.text
    return False, f"HTTP {response.status_code}: {response.text[:1000]}"


def iter_jsonl_lines(path: Path) -> Iterable[tuple[int, str]]:
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            yield lineno, line


def job_key(job_body: dict[str, Any], lineno: int) -> str:
    caption = job_body.get("caption")
    if isinstance(caption, str) and caption.strip():
        return f"{caption.strip()}#L{lineno}"
    name = (((job_body.get("jobDefVersion") or {}).get("name")) or "").strip()
    if name:
        return f"{name}#L{lineno}"
    return f"task#L{lineno}"


def extract_job_run_id(response: Any) -> str | None:
    if isinstance(response, dict):
        value = response.get("job_run_id") or response.get("jobRunId")
        if isinstance(value, str) and value:
            return value
        data = response.get("data")
        if isinstance(data, dict):
            value = data.get("job_run_id") or data.get("jobRunId")
            if isinstance(value, str) and value:
                return value
    return None


def summarize_expected_outputs(job_body: dict[str, Any]) -> dict[str, Any]:
    job_def = job_body.get("jobDefVersion") if isinstance(job_body.get("jobDefVersion"), dict) else {}
    run_params = job_body.get("jobRunParams") if isinstance(job_body.get("jobRunParams"), dict) else {}
    return {
        "job_def_outputs": job_def.get("outputs") or [],
        "run_outputs": run_params.get("outputs") or {},
    }


def rewrite_jsonl(path: Path, kept_lines: list[str]) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        if backup.exists():
            backup.unlink()
        path.rename(backup)
    with path.open("w", encoding="utf-8") as handle:
        for line in kept_lines:
            handle.write(line)
    print(f"Updated pending file: {path}")
    print(f"Backup: {backup}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit Seed job JSONL and remove successfully submitted lines.")
    parser.add_argument("--tasks", type=Path, default=Path("output.jsonl"))
    parser.add_argument("--watch", type=Path, default=Path("watch_tasks.jsonl"))
    parser.add_argument("--events", type=Path, default=Path("events.jsonl"))
    parser.add_argument("--submit-url", default=SUBMIT_URL_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Sleep after each real submit attempt to avoid platform rate limits.",
    )
    args = parser.parse_args()

    if not args.tasks.exists():
        raise FileNotFoundError(args.tasks)

    session = requests.Session()
    xjwt = "" if args.dry_run else get_xjwt(session)
    kept_lines: list[str] = []
    total = success = failed = 0

    for lineno, raw_line in iter_jsonl_lines(args.tasks):
        if not raw_line.strip():
            continue
        total += 1
        try:
            job = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            failed += 1
            kept_lines.append(raw_line)
            append_jsonl(args.events, {"ts": now_ts(), "event": "PARSE_ERR", "lineno": lineno, "error": str(exc)})
            continue

        key = job_key(job, lineno)
        if args.dry_run:
            print(f"[dry-run] would submit {key}")
            kept_lines.append(raw_line)
            continue

        ok, result = submit_job(session, xjwt, job, args.submit_url)
        if not ok and isinstance(result, str) and ("HTTP 401" in result or "HTTP 403" in result):
            xjwt = get_xjwt(session)
            ok, result = submit_job(session, xjwt, job, args.submit_url)

        if ok:
            success += 1
            job_run_id = extract_job_run_id(result)
            append_jsonl(
                args.events,
                {
                    "ts": now_ts(),
                    "event": "SUBMIT_OK",
                    "task_key": key,
                    "lineno": lineno,
                    "job_run_id": job_run_id,
                    "expected_outputs": summarize_expected_outputs(job),
                    "response": result,
                },
            )
            append_jsonl(
                args.watch,
                {
                    "ts": now_ts(),
                    "type": "TASK_STATE",
                    "task_key": key,
                    "attempt": 1,
                    "job_run_id": job_run_id,
                    "status": "CREATED",
                    "submit_url": args.submit_url,
                    "expected_outputs": summarize_expected_outputs(job),
                },
            )
            print(f"[submitted] {key} job_run_id={job_run_id}")
        else:
            failed += 1
            kept_lines.append(raw_line)
            append_jsonl(
                args.events,
                {
                    "ts": now_ts(),
                    "event": "SUBMIT_ERR",
                    "task_key": key,
                    "lineno": lineno,
                    "error": str(result),
                },
            )
            print(f"[failed] {key}: {result}")

        if not args.dry_run and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    if not args.dry_run:
        rewrite_jsonl(args.tasks, kept_lines)
    print(f"total={total} success={success} failed={failed} pending={len(kept_lines)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
