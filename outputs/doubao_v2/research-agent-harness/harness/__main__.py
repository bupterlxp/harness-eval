#!/usr/bin/env python3
"""
Research Agent Harness - Main entry point
"""

import argparse
import json
import os
import sys
from typing import List, Dict, Any, Optional
from pathlib import Path

# Import core components
sys.path.insert(0, str(Path(__file__).parent.parent))
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


def parse_task_spec(prompt: str) -> TaskSpec:
    """
    Parse natural language prompt into TaskSpec
    TODO: Implement LLM-based parsing
    """
    # Simple default parsing - in real implementation, use LLM to extract parameters
    return TaskSpec(
        research_questions=[prompt],
        min_sources=10,
        max_words=4000,
        max_hops=3,
        output_dir="./output"
    )


def main():
    parser = argparse.ArgumentParser(description="Research Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory")
    parser.add_argument("--min-sources", type=int, default=10, help="Minimum number of sources required")
    parser.add_argument("--max-words", type=int, default=4000, help="Maximum words in report")
    parser.add_argument("--max-hops", type=int, default=3, help="Maximum research hops")
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)

    # Parse task specification
    task_spec = TaskSpec(
        research_questions=[args.prompt],
        min_sources=args.min_sources,
        max_words=args.max_words,
        max_hops=args.max_hops,
        output_dir=args.output_dir
    )

    print(f"Starting research agent with task:")
    print(f"  Questions: {task_spec.research_questions}")
    print(f"  Min sources: {task_spec.min_sources}")
    print(f"  Max hops: {task_spec.max_hops}")
    print(f"  Output directory: {task_spec.output_dir}")

    # Initialize components
    tool_registry = ToolRegistry()
    context_manager = ContextManager()
    state_store = StateStore(args.output_dir)
    lifecycle_hooks = LifecycleHooks()
    evaluator = Evaluator()

    # Initialize execution loop
    exec_loop = ExecutionLoop(
        task_spec=task_spec,
        tool_registry=tool_registry,
        context_manager=context_manager,
        state_store=state_store,
        lifecycle_hooks=lifecycle_hooks,
        evaluator=evaluator
    )

    # Run the research
    try:
        result = exec_loop.run()

        # Save result
        result_path = os.path.join(args.output_dir, "result.json")
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)

        print(f"\n✅ Research completed successfully!")
        print(f"📊 Status: {result['status']}")
        print(f"📁 Report saved to: {result['report_path']}")
        print(f"📚 Sources used: {len(result['sources'])}")
        print(f"📈 Citation integrity: {result['citation_integrity']['total_citations']} total citations")
        if result['citation_integrity']['orphaned'] > 0:
            print(f"⚠️  Orphaned citations: {result['citation_integrity']['orphaned']}")
        if result['citation_integrity']['unused'] > 0:
            print(f"⚠️  Unused sources: {result['citation_integrity']['unused']}")

    except Exception as e:
        print(f"\n❌ Research failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()