"""CLI entry point for the Data Analysis Agent Harness.

Usage:
    python -m harness -p "task description" --output-dir ./output/
"""

import argparse
import json
import os
import sys
from pathlib import Path

from harness.execution import ExecutionEngine
from harness.state import StateStore
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryRecorder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Data Analysis Agent Harness",
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Natural language task description",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/",
        help="Output directory for results",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum execution rounds (default: 20)",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=120000,
        help="Token budget for context window (default: 120000)",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="Path to a checkpoint file to resume from",
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help="Working directory containing data files (default: current directory)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    work_dir = Path(args.work_dir).resolve() if args.work_dir else Path.cwd()

    trajectory_path = output_dir / "trajectory.jsonl"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Initialize components
    recorder = TrajectoryRecorder(trajectory_path)
    state_store = StateStore(checkpoint_dir)
    lifecycle_mgr = LifecycleManager()

    # Build and run the execution engine
    engine = ExecutionEngine(
        prompt=args.prompt,
        output_dir=output_dir,
        work_dir=work_dir,
        max_steps=args.max_steps,
        token_budget=args.token_budget,
        recorder=recorder,
        state_store=state_store,
        lifecycle=lifecycle_mgr,
        resume_from=args.resume_from,
    )

    try:
        result = engine.run()
    except KeyboardInterrupt:
        # Save checkpoint on interrupt
        state_store.save_checkpoint(engine.get_snapshot())
        result = {"status": "partial", "trajectory": str(trajectory_path)}
    except Exception as e:
        lifecycle_mgr.on_failure(error=e)
        result = {"status": "failed", "trajectory": str(trajectory_path)}

    # Write result.json
    result_path = output_dir / "result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n[harness] Done. Result written to {result_path}")
    print(f"[harness] Status: {result['status']}")

    if result["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
