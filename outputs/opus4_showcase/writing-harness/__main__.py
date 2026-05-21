"""CLI entry point for the Creative Writing Agent Harness.

Usage:
    python -m harness -p "task description" --output-dir ./output/
"""

import argparse
import json
import os
import sys
from pathlib import Path

from harness.execution import ExecutionLoop, WritingTask
from harness.state import StateStore
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryRecorder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Creative Writing Agent Harness",
    )
    parser.add_argument(
        "-p", "--prompt",
        required=True,
        help="Task description / writing prompt",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/",
        help="Directory for output artifacts",
    )
    parser.add_argument(
        "--mode",
        choices=["longform", "shortform"],
        default=None,
        help="Writing mode (auto-detected if omitted)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Maximum execution loop iterations",
    )
    parser.add_argument(
        "--max-revisions",
        type=int,
        default=5,
        help="Maximum critique-revise iterations",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Path to checkpoint file to resume from",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=120000,
        help="Token budget for context window",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trajectory_path = output_dir / "trajectory.jsonl"
    result_path = output_dir / "result.json"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Validate environment
    if not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable is required.", file=sys.stderr)
        return 1

    # Build task
    task = WritingTask(
        prompt=args.prompt,
        mode=args.mode,
        max_iterations=args.max_iterations,
        max_revisions=args.max_revisions,
        token_budget=args.token_budget,
    )

    # Initialize components
    recorder = TrajectoryRecorder(trajectory_path)
    state_store = StateStore(checkpoint_dir)
    lifecycle_mgr = LifecycleManager(recorder=recorder)

    # Resume from checkpoint if provided
    if args.checkpoint:
        checkpoint_path = Path(args.checkpoint)
        if checkpoint_path.exists():
            state_store.load_checkpoint(checkpoint_path)
            print(f"Resumed from checkpoint: {checkpoint_path}")

    # Run execution loop
    loop = ExecutionLoop(
        task=task,
        state_store=state_store,
        lifecycle=lifecycle_mgr,
        recorder=recorder,
        output_dir=output_dir,
    )

    try:
        status = loop.run()
    except KeyboardInterrupt:
        status = "partial"
        state_store.save_checkpoint("interrupted")
    except Exception as e:
        status = "failed"
        recorder.record_error(str(e))
        print(f"ERROR: {e}", file=sys.stderr)

    # Write result
    result = {
        "status": status,
        "trajectory": str(trajectory_path),
    }
    result_path.write_text(json.dumps(result, indent=2))
    print(f"Result: {result_path}")

    return 0 if status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
