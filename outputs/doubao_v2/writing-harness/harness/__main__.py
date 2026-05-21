#!/usr/bin/env python3
"""Creative Writing Agent Harness"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from harness.execution import ExecutionLoop
from harness.context import ContextManager
from harness.state import StateStore
from harness.evaluation import EvaluationLogger


class TaskSpec:
    """Task specification schema"""
    def __init__(
        self,
        genre: str,
        premise: str,
        target_words: int,
        pov: str,
        style_directives: list[str],
        structural_constraints: list[str],
        output_dir: str,
        max_revisions: int = 3
    ):
        self.genre = genre
        self.premise = premise
        self.target_words = target_words
        self.pov = pov
        self.style_directives = style_directives
        self.structural_constraints = structural_constraints
        self.max_revisions = max_revisions
        self.output_dir = output_dir


def load_task_spec(task_description: str) -> TaskSpec:
    """Load task spec from natural language description (placeholder)

    In a real implementation, this would use an LLM to parse the natural language
    into the structured TaskSpec format. For now, we'll return a default spec."""
    # This is a simplified parser - in a real implementation, this would use LLM
    # to parse the natural language into the structured TaskSpec
    import re

    # Simple keyword-based extraction
    genre_match = re.search(r'genre\s*:\s*([a-zA-Z\s]+)', task_description, re.IGNORECASE)
    premise = task_description
    target_words_match = re.search(r'(\d+)\s*words', task_description, re.IGNORECASE)
    pov_match = re.search(r'point\s*of\s*view|pov\s*:\s*([a-zA-Z\s]+)', task_description, re.IGNORECASE)

    return TaskSpec(
        genre=genre_match.group(1).strip() if genre_match else "generic",
        premise=premise,
        target_words=int(target_words_match.group(1)) if target_words_match else 1000,
        pov=pov_match.group(1).strip() if pov_match else "third-person limited",
        style_directives=["clear", "engaging"],
        structural_constraints=["have a clear beginning, middle, end"],
        output_dir="./output/",
        max_revisions=3
    )


def main():
    parser = argparse.ArgumentParser(description="Creative Writing Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--output-dir", default="./output/", help="Output directory")
    parser.add_argument("--target-words", type=int, help="Target word count")
    parser.add_argument("--pov", help="Narrative perspective")
    parser.add_argument("--genre", help="Writing genre")
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    # Load task specification
    task_spec = load_task_spec(args.prompt)

    # Override with command line args if provided
    if args.target_words:
        task_spec.target_words = args.target_words
    if args.pov:
        task_spec.pov = args.pov
    if args.genre:
        task_spec.genre = args.genre

    # Initialize components
    context_manager = ContextManager(task_spec)
    state_store = StateStore(task_spec.output_dir)
    evaluation_logger = EvaluationLogger(task_spec.output_dir)

    # Run execution loop
    execution_loop = ExecutionLoop(
        task_spec=task_spec,
        context_manager=context_manager,
        state_store=state_store,
        evaluation_logger=evaluation_logger
    )

    try:
        result = execution_loop.run()

        # Write result.json
        result_file = Path(args.output_dir) / "result.json"
        with open(result_file, "w") as f:
            json.dump(result, f, indent=2)

        print(f"Writing result to {result_file}")
        print(f"Task completed successfully!")

    except Exception as e:
        print(f"Error during execution: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()