"""CLI entry point for the Code Agent harness."""

import argparse
import json
import os
import sys
from pathlib import Path

from harness.execution import ExecutionEngine
from harness.tools import ToolRegistry, register_default_tools
from harness.context import ContextManager
from harness.state import StateStore
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryRecorder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Code Agent Harness - autonomous code modification agent",
    )
    parser.add_argument(
        "-p", "--prompt", required=True, help="Task description for the agent"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Directory for output artifacts",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Maximum number of execution steps",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("."),
        help="Working directory for code modifications",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Path to a checkpoint file to resume from",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name override (defaults to MODEL_NAME env var)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Ensure output directory exists
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve workspace
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(f"Error: workspace '{workspace}' is not a directory", file=sys.stderr)
        sys.exit(1)

    # Model configuration
    model_name = args.model or os.environ.get("MODEL_NAME", "gpt-4o")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is required", file=sys.stderr)
        sys.exit(1)

    # Initialize components
    trajectory_path = args.output_dir / "trajectory.jsonl"
    recorder = TrajectoryRecorder(trajectory_path)

    lifecycle = LifecycleManager()

    state_store = StateStore(
        checkpoint_dir=args.output_dir / "checkpoints",
    )

    context_manager = ContextManager(
        model_name=model_name,
        max_token_budget=128000,
        preserve_recent_steps=5,
    )

    tool_registry = ToolRegistry(workspace=workspace)
    register_default_tools(tool_registry, workspace=workspace)

    engine = ExecutionEngine(
        prompt=args.prompt,
        workspace=workspace,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        max_steps=args.max_steps,
        tool_registry=tool_registry,
        context_manager=context_manager,
        state_store=state_store,
        lifecycle=lifecycle,
        recorder=recorder,
    )

    # Resume from checkpoint if specified
    if args.resume and args.resume.exists():
        engine.restore_from_checkpoint(args.resume)

    # Run the agent
    result = engine.run()

    # Write result.json
    result_path = args.output_dir / "result.json"
    result_data = {
        "status": result.status.value,
        "trajectory": str(trajectory_path),
    }
    with open(result_path, "w") as f:
        json.dump(result_data, f, indent=2)

    print(f"Agent finished with status: {result.status.value}")
    print(f"Result written to: {result_path}")
    print(f"Trajectory written to: {trajectory_path}")


if __name__ == "__main__":
    main()
