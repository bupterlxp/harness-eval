#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from creation_eval.agent_cli import read_harness_response, run_agent_cli
from creation_eval.utils import best_python_bin


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a generated Harness-Evolve agent through its standard CLI.")
    parser.add_argument("prompt", nargs="*", help="Task prompt text.")
    parser.add_argument("--harness-path", default=os.environ.get("GENERATED_HARNESS_PATH", ""))
    parser.add_argument("--domain", default=os.environ.get("GENERATED_HARNESS_DOMAIN", "unknown"))
    parser.add_argument("--work-dir", "--workdir", dest="work_dir", default=os.environ.get("TASK_WORK_DIR", os.getcwd()))
    parser.add_argument("--output-dir", default=os.environ.get("GENERATED_HARNESS_OUTPUT_DIR", ""))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("GENERATED_HARNESS_TIMEOUT", "3600")))
    parser.add_argument("--python-bin", default=os.environ.get("HARNESS_EVAL_PYTHON"))
    args = parser.parse_args()

    harness_path = Path(args.harness_path).expanduser().resolve()
    if not harness_path.exists():
        print(f"generated harness path not found: {harness_path}", file=sys.stderr)
        return 2
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path(
        tempfile.mkdtemp(prefix="generated_harness_cli_")
    )
    prompt = " ".join(args.prompt).strip()
    result = run_agent_cli(
        harness_path,
        args.domain,
        prompt,
        output_dir,
        task_work_dir=Path(args.work_dir).expanduser().resolve(),
        python_bin=best_python_bin(args.python_bin),
        timeout=args.timeout,
    )
    response = read_harness_response(result)
    if response:
        print(response)
    if result.status != "success":
        print(result.error or f"generated harness failed: {result.status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
