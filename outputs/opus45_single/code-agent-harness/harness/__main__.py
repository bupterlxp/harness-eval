"""
CLI entry point for the code agent harness.

Usage:
    python -m harness run --task task_spec.json --output result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.execution import ExecutionLoop


def run_task(task_file: Path, output_file: Path) -> int:
    """
    Run a task from a specification file.

    Args:
        task_file: Path to task_spec.json
        output_file: Path to write result.json

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    if not task_file.exists():
        print(f"Error: Task file not found: {task_file}", file=sys.stderr)
        return 1

    try:
        task_spec = json.loads(task_file.read_text())
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in task file: {e}", file=sys.stderr)
        return 1

    required_fields = ["task_type", "description", "repo_path"]
    for field in required_fields:
        if field not in task_spec:
            print(f"Error: Missing required field '{field}' in task spec", file=sys.stderr)
            return 1

    repo_path = Path(task_spec["repo_path"]).resolve()
    if not repo_path.exists():
        print(f"Error: Repository path not found: {repo_path}", file=sys.stderr)
        return 1

    print(f"Running task: {task_spec['task_type']}")
    print(f"Repository: {repo_path}")
    print(f"Description: {task_spec['description'][:100]}...")

    try:
        loop = ExecutionLoop(
            repo_path=repo_path,
            task_spec=task_spec,
            output_dir=repo_path / ".harness_output"
        )

        result = loop.run()

        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(result, indent=2))

        print(f"\nResult: {result['status']}")
        print(f"Edits: {len(result['edits'])} files modified")
        print(f"Tests: {result['test_results']['passed']} passed, {result['test_results']['failed']} failed")
        print(f"Trajectory: {result['trajectory']}")
        print(f"Output written to: {output_file}")

        return 0 if result["status"] == "success" else 1

    except Exception as e:
        print(f"Error during execution: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Code Agent Harness - Autonomous code modification agent"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    run_parser = subparsers.add_parser("run", help="Run a task from specification")
    run_parser.add_argument(
        "--task", "-t",
        type=Path,
        required=True,
        help="Path to task specification JSON file"
    )
    run_parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Path to write result JSON file"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "run":
        return run_task(args.task, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
