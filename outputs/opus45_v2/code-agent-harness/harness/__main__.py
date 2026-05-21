"""CLI entry point for the harness."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

from harness.context import ContextManager
from harness.evaluation import TrajectoryRecorder
from harness.execution import ExecutionContext, ExecutionLoop, ExecutionState
from harness.lifecycle import LifecycleManager, create_default_hooks
from harness.state import StateStore
from harness.tools import ToolRegistry


class LLMClient:
    """Wrapper for OpenAI-compatible LLM client."""

    def __init__(self) -> None:
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model_name = os.environ.get("MODEL_NAME", "gpt-4")

        self.client = OpenAI(base_url=base_url, api_key=api_key)

    @property
    def chat(self) -> Any:
        return self.client.chat


def parse_task_spec(description: str, repo_path: str) -> dict[str, Any]:
    """Parse task specification from description."""
    task_type = "feature"
    lower_desc = description.lower()

    if any(word in lower_desc for word in ["fix", "bug", "error", "issue", "broken"]):
        task_type = "bug_fix"
    elif any(word in lower_desc for word in ["refactor", "clean", "improve", "optimize"]):
        task_type = "refactor"
    elif any(word in lower_desc for word in ["test", "spec", "coverage"]):
        task_type = "test_gen"

    test_command = None
    if Path(repo_path).exists():
        if (Path(repo_path) / "pytest.ini").exists() or (Path(repo_path) / "tests").exists():
            test_command = "pytest tests/ -v"
        elif (Path(repo_path) / "package.json").exists():
            test_command = "npm test"
        elif (Path(repo_path) / "Makefile").exists():
            test_command = "make test"

    return {
        "task_type": task_type,
        "description": description,
        "repo_path": repo_path,
        "test_command": test_command,
        "constraints": [],
    }


def run_harness(
    description: str,
    output_dir: str,
    repo_path: str | None = None,
    test_command: str | None = None,
    max_iterations: int = 10,
    max_llm_calls: int = 50,
    timeout: int = 3600,
) -> dict[str, Any]:
    """Run the harness with the given task description."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if repo_path is None:
        repo_path = str(Path.cwd())

    task_spec = parse_task_spec(description, repo_path)

    if test_command:
        task_spec["test_command"] = test_command

    tools = ToolRegistry()
    context_manager = ContextManager()
    state_store = StateStore(output_path / ".state")
    trajectory = TrajectoryRecorder(output_path)
    lifecycle = LifecycleManager(state_store, timeout=timeout)

    for event, callback in create_default_hooks():
        lifecycle.register_hook(event, callback)

    llm_client = LLMClient()

    execution_loop = ExecutionLoop(
        tools=tools,
        context_manager=context_manager,
        state_store=state_store,
        lifecycle=lifecycle,
        trajectory=trajectory,
        llm_client=llm_client,
    )

    ctx = ExecutionContext(
        task_type=task_spec["task_type"],
        description=task_spec["description"],
        repo_path=task_spec["repo_path"],
        test_command=task_spec["test_command"],
        constraints=task_spec["constraints"],
        max_iterations=max_iterations,
        max_llm_calls=max_llm_calls,
    )

    trajectory.start(ctx)

    try:
        ctx = execution_loop.run(ctx)
    except Exception as e:
        trajectory.record_error(str(e))
        ctx.last_error = str(e)
        ctx.current_state = ExecutionState.FAILED

    trajectory_path = trajectory.finish(ctx)

    if ctx.current_state == ExecutionState.SUCCESS:
        status = "success"
    elif ctx.edits:
        status = "partial"
    else:
        status = "failed"

    result = {
        "status": status,
        "edits": ctx.edits,
        "test_results": ctx.test_results,
        "trajectory": trajectory_path,
    }

    result_file = output_path / "result.json"
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2)

    return result


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Code Agent Harness - Autonomous code modification tool",
    )

    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Task description in natural language",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Output directory for results (default: ./output)",
    )

    parser.add_argument(
        "--repo-path",
        type=str,
        default=None,
        help="Repository path (default: current directory)",
    )

    parser.add_argument(
        "--test-command",
        type=str,
        default=None,
        help="Test command to verify changes",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Maximum execution iterations (default: 10)",
    )

    parser.add_argument(
        "--max-llm-calls",
        type=int,
        default=50,
        help="Maximum LLM API calls (default: 50)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Execution timeout in seconds (default: 3600)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    args = parser.parse_args()

    try:
        result = run_harness(
            description=args.prompt,
            output_dir=args.output_dir,
            repo_path=args.repo_path,
            test_command=args.test_command,
            max_iterations=args.max_iterations,
            max_llm_calls=args.max_llm_calls,
            timeout=args.timeout,
        )

        print(f"Status: {result['status']}")
        print(f"Edits: {len(result['edits'])} files modified")
        print(f"Trajectory: {result['trajectory']}")

        if result["status"] == "success":
            return 0
        elif result["status"] == "partial":
            return 1
        else:
            return 2

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
