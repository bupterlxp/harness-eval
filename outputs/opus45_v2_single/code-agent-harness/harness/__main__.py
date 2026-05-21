"""
Harness CLI entry point.

Usage:
    python -m harness -p "task description" --output-dir ./output/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from harness.context import ContextManager
from harness.evaluation import TrajectoryLogger
from harness.execution import ExecutionLoop
from harness.lifecycle import LifecycleManager
from harness.state import StateStore, AgentPhase
from harness.tools import ToolRegistry


def parse_task_spec(prompt: str) -> dict[str, Any]:
    """Parse a natural language prompt into a TaskSpec."""
    prompt_lower = prompt.lower()

    # Detect task type
    if any(w in prompt_lower for w in ["fix", "bug", "error", "issue", "broken"]):
        task_type = "bug_fix"
    elif any(w in prompt_lower for w in ["refactor", "clean", "reorganize", "restructure"]):
        task_type = "refactor"
    elif any(w in prompt_lower for w in ["test", "spec", "coverage"]):
        task_type = "test_gen"
    else:
        task_type = "feature"

    # Extract test command if mentioned
    test_command = None
    test_patterns = [
        r"test\s+(?:command|with|using)[:\s]+['\"]?([^'\"]+)['\"]?",
        r"run[:\s]+['\"]?([^'\"]+test[^'\"]*)['\"]?",
        r"pytest\s+\S+",
    ]
    for pattern in test_patterns:
        match = re.search(pattern, prompt, re.IGNORECASE)
        if match:
            test_command = match.group(1) if match.lastindex else match.group(0)
            break

    # Extract constraints
    constraints = []
    if "without" in prompt_lower:
        constraint_match = re.search(r"without\s+(.+?)(?:\.|$)", prompt, re.IGNORECASE)
        if constraint_match:
            constraints.append(f"Avoid: {constraint_match.group(1)}")

    return {
        "task_type": task_type,
        "description": prompt,
        "test_command": test_command,
        "constraints": constraints,
    }


def find_repo_path(start_dir: str = ".") -> str:
    """Find the repository root from start_dir."""
    current = Path(start_dir).resolve()

    # Look for git directory
    while current != current.parent:
        if (current / ".git").exists():
            return str(current)
        current = current.parent

    # No git repo found, use start dir
    return str(Path(start_dir).resolve())


def run_harness(
    prompt: str,
    output_dir: str,
    repo_path: str | None = None,
    test_command: str | None = None,
    max_retries: int = 5,
    max_llm_calls: int = 50,
) -> dict[str, Any]:
    """Run the code agent harness."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Parse task
    task_spec = parse_task_spec(prompt)
    if test_command:
        task_spec["test_command"] = test_command

    # Find repo path
    repo = repo_path or find_repo_path()

    # Initialize components
    state_store = StateStore(output_dir)
    state_store.state.task_description = task_spec["description"]
    state_store.state.repo_path = repo
    state_store.state.test_command = task_spec.get("test_command")
    state_store.state.constraints = task_spec.get("constraints", [])
    state_store.state.max_retries = max_retries
    state_store.state.max_llm_calls = max_llm_calls

    tool_registry = ToolRegistry()
    context_manager = ContextManager()
    lifecycle = LifecycleManager(state_store)
    trajectory = TrajectoryLogger(output_dir)

    # Run execution loop
    execution = ExecutionLoop(
        state_store=state_store,
        tool_registry=tool_registry,
        context_manager=context_manager,
        lifecycle=lifecycle,
        trajectory=trajectory,
    )

    result = execution.run()

    # Write result.json
    result_path = output_path / "result.json"
    result_path.write_text(json.dumps(result, indent=2))

    return result


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Code Agent Harness - Autonomous code modification agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m harness -p "Fix the bug in login.py where users can't log in"
    python -m harness -p "Add input validation to the API endpoints" --output-dir ./results/
    python -m harness -p "Refactor the database module" --test-command "pytest tests/"
        """,
    )

    parser.add_argument(
        "-p", "--prompt",
        required=True,
        help="Natural language task description",
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Output directory for results (default: ./output)",
    )
    parser.add_argument(
        "--repo-path",
        help="Path to the repository (default: auto-detect)",
    )
    parser.add_argument(
        "--test-command",
        help="Command to run tests (e.g., 'pytest tests/')",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Maximum retry attempts (default: 5)",
    )
    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=50,
        help="Maximum LLM API calls (default: 50)",
    )

    args = parser.parse_args()

    # Check for required environment variables
    if not os.environ.get("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY not set", file=sys.stderr)

    try:
        result = run_harness(
            prompt=args.prompt,
            output_dir=args.output_dir,
            repo_path=args.repo_path,
            test_command=args.test_command,
            max_retries=args.max_retries,
            max_llm_calls=args.max_llm_calls,
        )

        print(f"Status: {result['status']}")
        print(f"Edits: {len(result['edits'])} files modified")
        print(f"Trajectory: {result['trajectory']}")
        print(f"Results written to: {args.output_dir}/result.json")

        return 0 if result["status"] == "success" else 1

    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
