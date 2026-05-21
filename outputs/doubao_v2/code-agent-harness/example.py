#!/usr/bin/env python3
"""
Example usage of the code intelligence harness
"""

import sys
import os
from pathlib import Path

# Add the parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import (
    ExecutionLoop,
    ToolRegistry,
    ContextManager,
    StateStore,
    LifecycleHooks,
    Evaluator
)


def example_task():
    """Example: Create a simple Python file"""
    print("=== Code Intelligence Harness Example ===\n")

    # Initialize components
    print("Initializing harness components...")
    state_store = StateStore()
    tool_registry = ToolRegistry()
    context_manager = ContextManager()
    lifecycle_hooks = LifecycleHooks()
    evaluator = Evaluator()

    # Create execution loop
    executor = ExecutionLoop(
        state_store,
        tool_registry,
        context_manager,
        lifecycle_hooks,
        evaluator
    )

    # Define a simple task: create a Python file that prints hello world
    task_spec = {
        "task_type": "feature",
        "description": "Create a Python file called hello.py that prints 'Hello, World!' when run",
        "repo_path": "./",
        "test_command": "python hello.py",
        "constraints": []
    }

    print("\nStarting task execution:")
    print(f"Task type: {task_spec['task_type']}")
    print(f"Description: {task_spec['description']}")

    try:
        # Run the task
        result = executor.run_task(task_spec)

        print("\n=== Execution Results ===")
        print(f"Status: {result['status']}")
        print(f"Number of edits: {len(result['edits'])}")
        print(f"Test results: {result['test_results']}")
        print(f"Trajectory saved to: {result['trajectory']}")

        # Show what was created
        if os.path.exists("hello.py"):
            print("\n=== Created File ===")
            with open("hello.py", 'r') as f:
                print(f.read())

    except Exception as e:
        print(f"\nTask failed: {str(e)}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(example_task())