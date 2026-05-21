#!/usr/bin/env python3
"""Test script for the creative writing harness"""

import json
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from harness import TaskSpec
from harness.execution import ExecutionLoop
from harness.context import ContextManager
from harness.state import StateStore
from harness.evaluation import EvaluationLogger


def test_basic_harness():
    """Test basic harness functionality"""
    print("=== Testing Creative Writing Harness ===")

    # Create temporary output directory
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n1. Creating test output directory: {tmpdir}")

        # Create task specification
        task_spec = TaskSpec(
            genre="psychological thriller",
            premise="A detective investigates a mysterious disappearance in a small coastal town",
            target_words=2000,
            pov="third-person limited",
            style_directives=["tense", "atmospheric", "character-driven"],
            structural_constraints=["must have a twist ending", "include red herrings"],
            output_dir=tmpdir,
            max_revisions=2
        )

        print("\n2. Initializing components...")
        # Initialize components
        context_manager = ContextManager(task_spec)
        state_store = StateStore(task_spec.output_dir)
        evaluation_logger = EvaluationLogger(task_spec.output_dir)

        print("3. Creating execution loop...")
        execution_loop = ExecutionLoop(
            task_spec=task_spec,
            context_manager=context_manager,
            state_store=state_store,
            evaluation_logger=evaluation_logger
        )

        print("\n4. Running test execution...")
        try:
            # Run a simplified version of the workflow
            result = execution_loop.run()

            print(f"\n5. Execution completed!")
            print(f"   Status: {result['status']}")
            print(f"   Total words: {result['word_count']}")
            print(f"   Manuscript path: {result['manuscript_path']}")
            print(f"   Consistency issues: {len(result['consistency_issues'])}")

            # Verify output files
            print("\n6. Verifying output files...")
            output_dir = Path(tmpdir)
            assert (output_dir / "result.json").exists(), "result.json not found"
            assert (output_dir / "manuscript.txt").exists(), "manuscript.txt not found"
            assert (output_dir / "trajectory.jsonl").exists(), "trajectory.jsonl not found"
            assert (output_dir / "scenes").exists(), "scenes directory not found"

            print("   ✓ All output files created successfully")

            # Check result structure
            print("\n7. Validating result structure...")
            assert "status" in result
            assert "manuscript_path" in result
            assert "word_count" in result
            assert "outline" in result
            assert "consistency_issues" in result
            assert "trajectory" in result

            assert isinstance(result["outline"], dict)
            assert "beats" in result["outline"]
            assert "scenes" in result["outline"]
            assert isinstance(result["consistency_issues"], list)

            print("   ✓ Result structure is valid")

            # Check scenes directory
            scenes = state_store.get_all_scenes()
            print(f"   ✓ Found {len(scenes)} scenes in state store")

            print("\n✅ All tests passed!")
            return True

        except Exception as e:
            print(f"\n❌ Test failed with error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


def test_component_imports():
    """Test that all components can be imported"""
    print("\n=== Testing Component Imports ===")

    try:
        from harness import execution
        from harness import tools
        from harness import context
        from harness import state
        from harness import lifecycle
        from harness import evaluation

        print("✓ All modules imported successfully")

        # Test specific imports
        from harness.execution import ExecutionLoop
        from harness.tools import ToolRegistry
        from harness.context import ContextManager
        from harness.state import StateStore
        from harness.lifecycle import LifecycleHooks
        from harness.evaluation import EvaluationLogger

        print("✓ All core classes imported successfully")
        return True

    except Exception as e:
        print(f"✗ Import failed: {str(e)}")
        return False


if __name__ == "__main__":
    # Run tests
    import argparse
    parser = argparse.ArgumentParser(description="Test creative writing harness")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    all_passed = True

    if args.all:
        # Run all tests
        all_passed &= test_component_imports()
        all_passed &= test_basic_harness()
    else:
        # Just run component imports test by default
        all_passed &= test_component_imports()

    print(f"\n=== Final Result ===")
    if all_passed:
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed!")
        sys.exit(1)