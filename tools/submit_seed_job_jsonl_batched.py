#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import requests

import submit_seed_job_jsonl as submit_lib


GET_URL_DEFAULT = "https://paas-gw.byted.org/openapi/v1/job_run/get"

TERMINAL_STATUS_KEYWORDS = (
    "SUCCESS",
    "SUCCEEDED",
    "FAILED",
    "FAIL",
    "STOPPED",
    "CANCELED",
    "CANCELLED",
    "TERMINATED",
    "EXIT",
)


def read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines(True) if line.strip()]


def write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")


def load_watch(path: Path) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return active
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        job_run_id = row.get("job_run_id")
        if isinstance(job_run_id, str) and job_run_id:
            active[job_run_id] = row
    return active


def status_is_terminal(status: str, err_msg: str) -> bool:
    normalized = status.upper()
    if any(keyword in normalized for keyword in TERMINAL_STATUS_KEYWORDS):
        return True
    return bool(err_msg) and "Failed to build task image" in err_msg


def get_job_status(session: requests.Session, xjwt: str, get_url: str, job_run_id: str) -> dict[str, Any]:
    response = session.post(
        get_url,
        headers={"Domain": "seed_job", "content-type": "application/json", "x-jwt-token": xjwt},
        json={"job_run_id": job_run_id},
        timeout=30,
    )
    if response.status_code in (401, 403):
        raise PermissionError(response.text[:500])
    if response.status_code != 200:
        return {"status": f"HTTP_{response.status_code}", "err_msg": response.text[:500]}
    data = response.json()
    job_run = data.get("job_run") or data.get("data", {}).get("job_run") or data.get("data") or data
    meta = job_run.get("meta") if isinstance(job_run, dict) else {}
    err_msg = ""
    app_output: Any = {}
    app_outputs: Any = {}
    arnold_url = ""
    trial_id = ""
    trial_status = ""
    job_def_outputs: Any = []
    run_outputs: Any = {}
    if isinstance(meta, dict):
        err_msg = str(meta.get("err_msg") or meta.get("errMsg") or "")
        app_output = meta.get("app_output") or {}
        app_outputs = meta.get("app_outputs") or {}
        arnold_url = str(meta.get("arnold_url") or "")
        trial_id = str(meta.get("arnold_trial_id") or "")
        trial_status = str(meta.get("arnold_trial_status") or "")
        job_def_version = meta.get("job_def_version") if isinstance(meta.get("job_def_version"), dict) else {}
        job_run_params = meta.get("job_run_params") if isinstance(meta.get("job_run_params"), dict) else {}
        job_def_outputs = job_def_version.get("outputs") or []
        run_outputs = job_run_params.get("outputs") or {}
    status = str(job_run.get("status") or job_run.get("jobRunStatus") or "UNKNOWN") if isinstance(job_run, dict) else "UNKNOWN"
    return {
        "status": status,
        "err_msg": err_msg,
        "app_output": app_output,
        "app_outputs": app_outputs,
        "arnold_url": arnold_url,
        "trial_id": trial_id,
        "trial_status": trial_status,
        "job_def_outputs": job_def_outputs,
        "run_outputs": run_outputs,
    }


def append_event(path: Path, obj: dict[str, Any]) -> None:
    submit_lib.append_jsonl(path, {"ts": submit_lib.now_ts(), **obj})


def submit_one(
    *,
    session: requests.Session,
    xjwt: str,
    raw_line: str,
    lineno: int,
    submit_url: str,
    watch: Path,
    events: Path,
) -> str | None:
    job = json.loads(raw_line)
    key = submit_lib.job_key(job, lineno)
    ok, result = submit_lib.submit_job(session, xjwt, job, submit_url)
    if not ok and isinstance(result, str) and ("HTTP 401" in result or "HTTP 403" in result):
        xjwt = submit_lib.get_xjwt(session)
        ok, result = submit_lib.submit_job(session, xjwt, job, submit_url)
    if not ok:
        append_event(events, {"event": "SUBMIT_ERR", "task_key": key, "lineno": lineno, "error": str(result)})
        print(f"[submit-failed] {key}: {result}")
        return None
    job_run_id = submit_lib.extract_job_run_id(result)
    append_event(
        events,
        {
            "event": "SUBMIT_OK",
            "task_key": key,
            "lineno": lineno,
            "job_run_id": job_run_id,
            "expected_outputs": submit_lib.summarize_expected_outputs(job),
            "response": result,
        },
    )
    submit_lib.append_jsonl(
        watch,
        {
            "ts": submit_lib.now_ts(),
            "type": "TASK_STATE",
            "task_key": key,
            "attempt": 1,
            "job_run_id": job_run_id,
            "status": "CREATED",
            "submit_url": submit_url,
            "expected_outputs": submit_lib.summarize_expected_outputs(job),
        },
    )
    print(f"[submitted] {key} job_run_id={job_run_id}")
    return job_run_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Submit Seed jobs with a fixed active-job cap. This is intended for "
            "one-instance-per-task BMK shards, where launching all rows at once is too aggressive."
        )
    )
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--watch", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--submit-url", default=submit_lib.SUBMIT_URL_DEFAULT)
    parser.add_argument("--get-url", default=GET_URL_DEFAULT)
    parser.add_argument("--max-active", type=int, default=32)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--submit-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-submit", type=int, default=None, help="Optional cap for a probe batch.")
    args = parser.parse_args()

    if args.max_active < 1:
        raise ValueError("--max-active must be >= 1")

    pending = read_jsonl(args.tasks)
    if not pending:
        print(f"No pending tasks in {args.tasks}")
        return 0

    session = requests.Session()
    xjwt = submit_lib.get_xjwt(session)
    active = load_watch(args.watch)
    submitted_total = 0

    while pending or active:
        # Refresh active statuses.
        still_active: dict[str, dict[str, Any]] = {}
        for job_run_id, row in list(active.items()):
            try:
                status_info = get_job_status(session, xjwt, args.get_url, job_run_id)
            except PermissionError:
                xjwt = submit_lib.get_xjwt(session)
                status_info = get_job_status(session, xjwt, args.get_url, job_run_id)
            status = str(status_info.get("status") or "UNKNOWN")
            err_msg = str(status_info.get("err_msg") or "")
            append_event(
                args.events,
                {
                    "event": "STATUS",
                    "job_run_id": job_run_id,
                    "status": status,
                    "err_msg": err_msg[:500],
                    "trial_id": status_info.get("trial_id"),
                    "trial_status": status_info.get("trial_status"),
                    "arnold_url": status_info.get("arnold_url"),
                    "app_output": status_info.get("app_output"),
                    "app_outputs": status_info.get("app_outputs"),
                    "job_def_outputs": status_info.get("job_def_outputs"),
                    "run_outputs": status_info.get("run_outputs"),
                },
            )
            if status_is_terminal(status, err_msg):
                print(f"[terminal] {job_run_id} status={status} err={err_msg[:160]}")
            else:
                row["status"] = status
                still_active[job_run_id] = row
        active = still_active

        # Fill active window.
        while pending and len(active) < args.max_active:
            if args.max_submit is not None and submitted_total >= args.max_submit:
                write_jsonl(args.tasks, pending)
                print(f"Reached --max-submit={args.max_submit}; pending={len(pending)} active={len(active)}")
                return 0
            raw = pending.pop(0)
            submitted_total += 1
            job_run_id = submit_one(
                session=session,
                xjwt=xjwt,
                raw_line=raw,
                lineno=submitted_total,
                submit_url=args.submit_url,
                watch=args.watch,
                events=args.events,
            )
            if job_run_id:
                active[job_run_id] = {"job_run_id": job_run_id, "status": "CREATED"}
            else:
                # Put failed submit back for manual inspection/retry.
                pending.insert(0, raw)
                break
            if args.submit_sleep_seconds > 0:
                time.sleep(args.submit_sleep_seconds)

        write_jsonl(args.tasks, pending)
        print(f"[loop] pending={len(pending)} active={len(active)} submitted_this_run={submitted_total}")
        if pending or active:
            time.sleep(args.poll_seconds)

    print(f"Done. submitted_this_run={submitted_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
