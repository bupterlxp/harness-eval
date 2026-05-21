#!/usr/bin/env python3
"""
Main entry point for the code intelligence harness.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any

from harness import execution, tools, context, state, lifecycle, evaluation


def main():
    parser = argparse.ArgumentParser(description="Code Intelligence Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--output-dir", default="./output/", help="Output directory for results")
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize components
    state_store = state.StateStore()
    tool_registry = tools.ToolRegistry()
    context_manager = context.ContextManager()
    lifecycle_hooks = lifecycle.LifecycleHooks()
    evaluator = evaluation.Evaluator()
    executor = execution.ExecutionLoop(state_store, tool_registry, context_manager, lifecycle_hooks, evaluator)

    # Parse task specification
    task_spec = {
        "task_type": "feature",  # Default to feature, will be auto-detected
        "description": args.prompt,
        "repo_path": "./",
        "test_command": None,
        "constraints": []
    }

    try:
        # Execute the task
        result = executor.run_task(task_spec)

        # Write result to output file
        result_file = output_dir / "result.json"
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Task completed successfully. Results written to {result_file}")
        return 0
    except Exception as e:
        print(f"Task failed: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())