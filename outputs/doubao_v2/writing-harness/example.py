#!/usr/bin/env python3
"""Example usage of the creative writing harness"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from harness import TaskSpec
from harness.execution import ExecutionLoop
from harness.context import ContextManager
from harness.state import StateStore
from harness.evaluation import EvaluationLogger


def main():
    print("=== Creative Writing Harness Example ===\n")

    # Create output directory
    output_dir = "./example_output"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Define your writing task
    task_spec = TaskSpec(
        genre="science fiction",
        premise="A astronaut discovers an alien artifact on Mars that changes everything we know about humanity's place in the universe",
        target_words=3000,
        pov="first-person",
        style_directives=["hard sci-fi", "thought-provoking", "emotional"],
        structural_constraints=["include accurate Mars science", "explore themes of isolation", "have a hopeful but bittersweet ending"],
        output_dir=output_dir,
        max_revisions=3
    )

    print(f"📋 Task Specification:")
    print(f"   Genre: {task_spec.genre}")
    print(f"   Premise: {task_spec.premise}")
    print(f"   Target words: {task_spec.target_words}")
    print(f"   POV: {task_spec.pov}")
    print(f"   Output directory: {output_dir}\n")

    # Initialize components
    print("🔧 Initializing harness components...")
    context_manager = ContextManager(task_spec)
    state_store = StateStore(task_spec.output_dir)
    evaluation_logger = EvaluationLogger(task_spec.output_dir)

    # Create and run execution loop
    print("🚀 Starting writing workflow...\n")
    execution_loop = ExecutionLoop(
        task_spec=task_spec,
        context_manager=context_manager,
        state_store=state_store,
        evaluation_logger=evaluation_logger
    )

    try:
        # Run the full workflow
        result = execution_loop.run()

        print("\n✅ Writing workflow completed!")
        print(f"📊 Results:")
        print(f"   Status: {result['status']}")
        print(f"   Total words written: {result['word_count']}")
        print(f"   Manuscript saved to: {result['manuscript_path']}")
        print(f"   Consistency issues found: {len(result['consistency_issues'])}")
        print(f"   Trajectory log: {result['trajectory']}")

        # Show sample of the manuscript
        print("\n📖 Sample from the manuscript:")
        with open(result['manuscript_path'], 'r') as f:
            first_lines = f.read()[:500] + "..."
            print(first_lines)

        # Show consistency issues
        if result['consistency_issues']:
            print("\n⚠️  Consistency issues found:")
            for issue in result['consistency_issues']:
                print(f"   - {issue}")

        print("\n🎉 All done! Check the output directory for full results.")

    except Exception as e:
        print(f"\n❌ Error during workflow: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())