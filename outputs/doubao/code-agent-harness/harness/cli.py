#!/usr/bin/env python3
"""
CLI for the agent harness.
"""

import argparse
import sys
import os
from typing import Optional

from harness.core import AgentHarness
from harness.execution import AgentState


def main():
    parser = argparse.ArgumentParser(description="Code Agent Harness for bug fixing")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--test-file", default="test_server.py", help="Test file to run")
    parser.add_argument("--source-file", default="buggy_server.py", help="Source file to fix")
    parser.add_argument("--trajectory", default="trajectory.jsonl", help="Trajectory output file")
    parser.add_argument("--state", default="harness_state.json", help="State file path")
    parser.add_argument("--run-tests", action="store_true", help="Run tests only")
    parser.add_argument("--fix-all", action="store_true", help="Fix all bugs automatically")
    parser.add_argument("--fix-bug", type=int, help="Fix a specific bug by ID")
    parser.add_argument("--list-bugs", action="store_true", help="List all identified bugs")
    parser.add_argument("--show-trajectory", action="store_true", help="Show trajectory summary")

    args = parser.parse_args()

    # Initialize harness
    harness = AgentHarness()

    if args.run_tests:
        print("Running tests...")
        result = harness.run_tests()
        print(f"Tests {'passed' if result.success else 'failed'}")
        if result.output:
            print(result.output)
        return 0

    if args.list_bugs:
        bugs = harness.list_bugs()
        print(f"Found {len(bugs)} bugs:")
        for bug in bugs:
            status = f"[{bug.status.upper()}]"
            print(f"{status} Bug #{bug.bug_id}: {bug.title}")
            print(f"  {bug.description}")
            print(f"  Severity: {bug.severity}")
            print(f"  File: {bug.file_path}:{bug.line_number}\n")
        return 0

    if args.show_trajectory:
        if os.path.exists(args.trajectory):
            from harness.evaluation import load_trajectory
            trajectory = load_trajectory(args.trajectory)
            trajectory.print_summary()
        else:
            print(f"Trajectory file not found: {args.trajectory}")
        return 0

    if args.fix_bug:
        print(f"Fixing bug #{args.fix_bug}...")
        # Implement single bug fix
        return 0

    if args.fix_all:
        print("Starting automatic bug fixing process...")
        try:
            harness.run()
            print("\n=== Fix process completed ===")
            bugs = harness.list_bugs()
            fixed = [b for b in bugs if b.status == "fixed"]
            print(f"Fixed {len(fixed)}/{len(bugs)} bugs")

            if harness.trajectory_recorder:
                harness.trajectory_recorder.save_to_file(args.trajectory)
                print(f"Trajectory saved to: {args.trajectory}")

            if args.state:
                harness.state_store.save_state(args.state)
                print(f"State saved to: {args.state}")

        except KeyboardInterrupt:
            print("\nOperation interrupted by user")
            if args.state:
                harness.state_store.save_state(args.state + ".interrupt")
                print(f"State saved to: {args.state}.interrupt")
            return 1
        except Exception as e:
            print(f"\nError during execution: {str(e)}")
            import traceback
            traceback.print_exc()
            if args.state:
                harness.state_store.save_state(args.state + ".error")
                print(f"Error state saved to: {args.state}.error")
            return 1

    # Default interactive mode
    print("=== Code Agent Harness ===")
    print("Use --help to see available commands")
    print("\nAvailable commands:")
    print("  --run-tests           Run test suite")
    print("  --list-bugs           List identified bugs")
    print("  --fix-all             Fix all bugs automatically")
    print("  --fix-bug ID          Fix specific bug")
    print("  --show-trajectory     Show execution trajectory summary")
    print("\nRun with --fix-all to start automatic bug fixing")


if __name__ == "__main__":
    sys.exit(main())