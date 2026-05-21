#!/usr/bin/env python3
"""
Simple example usage of the research agent harness
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from harness.execution import ExecutionLoop
from harness.tools import ToolRegistry
from harness.context import ContextManager
from harness.state import StateStore
from harness.lifecycle import LifecycleHooks
from harness.evaluation import Evaluator


class TaskSpec:
    """Task specification for research tasks"""
    def __init__(
        self,
        research_questions: list[str],
        min_sources: int = 10,
        max_words: int = 4000,
        required_sections: list[str] | None = None,
        max_hops: int = 3,
        output_dir: str = "./output",
        constraints: list[str] | None = None,
    ):
        self.research_questions = research_questions
        self.min_sources = min_sources
        self.max_words = max_words
        self.required_sections = required_sections or []
        self.max_hops = max_hops
        self.output_dir = output_dir
        self.constraints = constraints or []


def run_example_research():
    """Run an example research task"""
    print("=== Research Agent Harness Example ===\n")

    # Configure the research task
    task_spec = TaskSpec(
        research_questions=[
            "What are the latest developments in renewable energy technology?",
            "How do solar panels compare to wind turbines in terms of efficiency and cost?"
        ],
        min_sources=5,  # Lowered for example
        max_hops=2,
        output_dir="./example_output"
    )

    # Initialize components
    tool_registry = ToolRegistry()
    context_manager = ContextManager()
    state_store = StateStore(task_spec.output_dir)
    lifecycle_hooks = LifecycleHooks()
    evaluator = Evaluator()

    print(f"Research task configured:")
    print(f"  Questions: {task_spec.research_questions}")
    print(f"  Max hops: {task_spec.max_hops}")
    print(f"  Output directory: {task_spec.output_dir}\n")

    # Run the research
    print("Starting research...")
    exec_loop = ExecutionLoop(
        task_spec=task_spec,
        tool_registry=tool_registry,
        context_manager=context_manager,
        state_store=state_store,
        lifecycle_hooks=lifecycle_hooks,
        evaluator=evaluator
    )

    result = exec_loop.run()

    print("\n=== Research Complete ===")
    print(f"Status: {result['status']}")
    print(f"Sources used: {len(result['sources'])}")
    print(f"Report saved to: {result['report_path']}")
    print(f"Trajectory saved to: {result['trajectory']}")

    return result


if __name__ == "__main__":
    run_example_research()