#!/usr/bin/env python3
"""
Simple demo script to show the agent harness in action.
"""

import os
import sys
import time

def main():
    print("=== Code Agent Harness Demo ===\n")

    # Show the project structure
    print("1. Project Structure:")
    for root, dirs, files in os.walk('.'):
        if '.git' in root or '__pycache__' in root or 'test_state' in root:
            continue
        level = root.replace('.', '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            print(f"{subindent}{file}")
    print()

    # Show the buggy server header
    print("2. Sample Buggy Server:")
    with open('samples/buggy_server.py', 'r') as f:
        lines = f.readlines()[:20]
        print(''.join(lines))
    print("... (truncated)")
    print()

    # Show the 8 bugs
    print("3. Identified Bugs:")
    bugs = [
        "1. Non-ASCII character handling in JSON responses",
        "2. Incorrect logical operator (OR instead of AND) in list filtering",
        "3. Missing ordering in query results",
        "4. SQL injection vulnerability",
        "5. Invalid status values silently corrected",
        "6. Database connection closed before query execution",
        "7. Updated timestamp not maintained on updates",
        "8. Incorrect 404 response for deleted non-existent tasks"
    ]
    for i, bug in enumerate(bugs, 1):
        print(f"   {i}. {bug}")
    print()

    print("4. How to run:")
    print("   $ pip install -e .")
    print("   $ agent-harness --fix-all")
    print()

    print("5. Expected Outcomes:")
    print("   - ✅ All 8 bugs fixed automatically")
    print("   - ✅ 8 separate git commits")
    print("   - ✅ 100% test pass rate")
    print("   - ✅ Full trajectory recorded in trajectory.jsonl")
    print()

    print("=== Demo Complete ===")
    print("\nRun the commands above to see the harness in action!")

if __name__ == "__main__":
    main()