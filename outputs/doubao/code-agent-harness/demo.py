#!/usr/bin/env python3
"""
Script to run the agent harness on the sample buggy server.
"""

import os
import sys
import subprocess


def main():
    print("=== Code Agent Harness - Sample Bug Fixing Demo ===\n")

    # Check if we're in the right directory
    if not os.path.exists("samples/buggy_server.py"):
        print("ERROR: samples/buggy_server.py not found")
        sys.exit(1)

    # Show initial state
    print("1. Checking initial test suite status...")
    result = subprocess.run(["python", "-m", "pytest", "samples/test_server.py", "-v"],
                          capture_output=True, text=True)
    print(f"Initial tests: {'PASSED' if result.returncode == 0 else 'FAILED'} (exit code: {result.returncode})")

    if result.stderr:
        print(f"\nTest stderr output:\n{result.stderr[:500]}...")

    print("\n2. Starting agent harness...")
    print("This will:")
    print("  - Index the codebase")
    print("  - Run initial tests")
    print("  - Identify and classify bugs")
    print("  - Prioritize fixes")
    print("  - Fix each bug individually")
    print("  - Run regression tests")
    print("  - Generate a full report")
    print()

    # Run the harness
    os.environ["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(["python", "-m", "harness", "--fix-all"],
                          capture_output=False, text=True)

    print("\n3. Post-fix test run...")
    result = subprocess.run(["python", "-m", "pytest", "samples/test_server.py", "-v"],
                          capture_output=True, text=True)
    print(f"Final tests: {'PASSED' if result.returncode == 0 else 'FAILED'}")

    print("\n=== Demo Complete ===")
    print("\nNext steps:")
    print("  - Check trajectory.jsonl for full execution history")
    print("  - Check harness_state.json for saved state")
    print("  - Run 'agent-harness --list-bugs' to see fixed bugs")
    print("  - Run 'agent-harness --show-trajectory' to see execution summary")


if __name__ == "__main__":
    main()