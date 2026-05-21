#!/usr/bin/env python3
"""Command-line interface for Data Analysis Agent Harness"""

import argparse
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(description="Data Analysis Agent Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--output-dir", default="./output", help="Output directory for charts and reports")
    parser.add_argument("--max-steps", type=int, default=20, help="Maximum analysis steps")
    parser.add_argument("--list-tools", action="store_true", help="List available analysis tools")
    args = parser.parse_args()

    if args.list_tools:
        from harness.tools import ToolRegistry
        registry = ToolRegistry()
        print("Available tools:")
        for name, desc in registry.get_tool_descriptions().items():
            print(f"  - {name}: {desc}")
        return

    # Import and run the main harness
    from __main__ import main as harness_main
    harness_main()


if __name__ == "__main__":
    main()