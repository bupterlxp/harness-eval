"""Entry point for the creative writing harness.

Usage:
    python -m harness -p "任务描述" --output-dir ./output/
"""

import argparse
import json
import sys
from pathlib import Path

from harness.execution import ExecutionLoop
from harness.state import StateStore
from harness.context import ContextManager
from harness.tools import ToolRegistry
from harness.lifecycle import LifecycleHooks
from harness.evaluation import TrajectoryRecorder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Creative Writing Agent Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        "--max-revisions",
        type=int,
        default=3,
        help="Maximum revisions per scene (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Timeout in seconds (default: 3600)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    state_store = StateStore(output_dir)
    context_manager = ContextManager()
    tool_registry = ToolRegistry()
    trajectory_recorder = TrajectoryRecorder(output_dir)
    lifecycle_hooks = LifecycleHooks(
        context_manager=context_manager,
        trajectory_recorder=trajectory_recorder,
    )

    execution_loop = ExecutionLoop(
        state_store=state_store,
        context_manager=context_manager,
        tool_registry=tool_registry,
        lifecycle_hooks=lifecycle_hooks,
        trajectory_recorder=trajectory_recorder,
        max_revisions=args.max_revisions,
        timeout=args.timeout,
    )

    try:
        result = execution_loop.run(args.prompt, output_dir)

        result_path = output_dir / "result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"Writing completed. Result saved to {result_path}")
        return 0 if result["status"] == "success" else 1

    except Exception as e:
        error_result = {
            "status": "failed",
            "error": str(e),
            "manuscript_path": "",
            "word_count": 0,
            "outline": {"beats": [], "scenes": []},
            "consistency_issues": [],
            "trajectory": str(trajectory_recorder.trajectory_path),
        }
        result_path = output_dir / "result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
