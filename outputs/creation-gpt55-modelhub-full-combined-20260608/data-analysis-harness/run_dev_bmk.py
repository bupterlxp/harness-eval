#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "dev_bmk_config.json").read_text(encoding="utf-8"))


def ensure_meta() -> None:
    meta_path = ROOT / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    else:
        meta = {}
    meta.setdefault("task_id", CONFIG.get("task_id") or ROOT.name)
    meta.setdefault("status", "success")
    meta.setdefault("creation_profile", "claude_code_scaffold_native")
    meta["dev_bmk_feedback_enabled"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_index(record: dict) -> None:
    index_path = ROOT / "dev_bmk_runs" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run public/dev BMK feedback for the current generated harness.")
    parser.add_argument("--bench", default="auto", help="BMK id(s), comma-separated, or auto.")
    parser.add_argument("--max-tasks", type=int, default=int(CONFIG.get("default_max_tasks_per_bmk") or 3))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("DEV_BMK_TIMEOUT_SECONDS", "3600")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--eval-model-name", default=os.environ.get("EVAL_MODEL_NAME") or os.environ.get("MODEL_NAME") or "")
    parser.add_argument("--eval-base-url", default=os.environ.get("EVAL_BASE_URL") or os.environ.get("BASE_URL") or "")
    args = parser.parse_args()

    ensure_meta()
    harness_eval_root = Path(os.environ.get("HARNESS_EVAL_ROOT") or CONFIG.get("harness_eval_root") or "/harness-eval")
    harness_evolve_root = Path(os.environ.get("HARNESS_EVOLVE_ROOT") or CONFIG.get("harness_evolve_root") or "/harness-evolve")
    bench = CONFIG.get("default_benches") if args.bench == "auto" else args.bench
    run_id = "dev-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = ROOT / str(CONFIG.get("output_root") or "dev_bmk_runs")
    output_root.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(harness_eval_root / "run_creation_eval.py"),
        "--generation-output",
        str(ROOT),
        "--matrix",
        str(harness_eval_root / "eval_matrix.yaml"),
        "--bench",
        str(bench),
        "--run-id",
        run_id,
        "--eval-output-root",
        str(output_root),
        "--harness-evolve-root",
        str(harness_evolve_root),
        "--python-bin",
        sys.executable,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--max-tasks-per-bmk",
        str(max(1, args.max_tasks)),
    ]
    if args.eval_model_name:
        command.extend(["--eval-model-name", args.eval_model_name])
    if args.eval_base_url:
        command.extend(["--eval-base-url", args.eval_base_url])
    if args.dry_run:
        command.append("--dry-run")

    env = os.environ.copy()
    if not env.get("EVAL_API_KEY"):
        env["EVAL_API_KEY"] = env.get("API_KEY", "")
    if not env.get("EVAL_BASE_URL"):
        env["EVAL_BASE_URL"] = env.get("BASE_URL", "")
    if not env.get("EVAL_MODEL_NAME"):
        env["EVAL_MODEL_NAME"] = env.get("MODEL_NAME", "")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")

    print("Running public/dev BMK feedback:")
    print(" ".join(command))
    # Run downstream dev feedback from a writable directory. Some benchmark
    # dependencies create local caches relative to cwd; /harness-eval is mounted
    # read-only inside creation containers.
    result = subprocess.run(command, cwd=output_root, env=env)
    output_dir = output_root / run_id
    record = {
        "run_id": run_id,
        "bench": bench,
        "max_tasks": args.max_tasks,
        "returncode": result.returncode,
        "output_dir": str(output_dir),
        "summary_csv": str(output_dir / "summary.csv"),
        "summary_jsonl": str(output_dir / "summary.jsonl"),
    }
    append_index(record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
