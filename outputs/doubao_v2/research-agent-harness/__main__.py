#!/usr/bin/env python3
"""
Research Agent Harness

A general-purpose deep research harness that accepts research questions, autonomously
performs information retrieval, source evaluation, evidence organization, and structured
report generation.
"""

import argparse
import json
import os
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path

# Import core components
from harness import execution, tools, context, state, lifecycle, evaluation


class TaskSpec:
    """Task specification for research tasks"""
    research_questions: List[str]
    min_sources: int
    max_words: int
    required_sections: List[str]
    max_hops: int
    output_dir: str
    constraints: List[str]

    def __init__(
        self,
        research_questions: List[str],
        min_sources: int = 10,
        max_words: int = 4000,
        required_sections: Optional[List[str]] = None,
        max_hops: int = 3,
        output_dir: str = "./output",
        constraints: Optional[List[str]] = None,
    ):
        self.research_questions = research_questions
        self.min_sources = min_sources
        self.max_words = max_words
        self.required_sections = required_sections or []
        self.max_hops = max_hops
        self.output_dir = output_dir
        self.constraints = constraints or []


def main():
    parser = argparse.ArgumentParser(description="Research Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # TODO: Parse prompt into TaskSpec using LLM
    # For now, use default values
    task_spec = TaskSpec(
        research_questions=[args.prompt],
        output_dir=args.output_dir
    )

    # Initialize components
    tool_registry = tools.ToolRegistry()
    context_manager = context.ContextManager()
    state_store = state.StateStore(args.output_dir)
    lifecycle_hooks = lifecycle.LifecycleHooks()
    evaluator = evaluation.Evaluator()

    # Initialize execution loop
    exec_loop = execution.ExecutionLoop(
        task_spec=task_spec,
        tool_registry=tool_registry,
        context_manager=context_manager,
        state_store=state_store,
        lifecycle_hooks=lifecycle_hooks,
        evaluator=evaluator
    )

    # Run the research
    result = exec_loop.run()

    # Save result
    result_path = os.path.join(args.output_dir, "result.json")
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Research completed successfully!")
    print(f"Report saved to: {result['report_path']}")
    print(f"Sources used: {len(result['sources'])}")
    print(f"Status: {result['status']}")


if __name__ == "__main__":
    main()