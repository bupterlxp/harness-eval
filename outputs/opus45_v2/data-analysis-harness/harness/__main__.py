"""
Command-line interface for the Data Analysis Agent Harness.

Usage:
    python -m harness -p "analysis task description" --output-dir ./output/
"""

import argparse
import json
import sys
from pathlib import Path

from harness.execution import run_analysis


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Data Analysis Agent Harness - autonomous data exploration and analysis"
    )

    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Natural language analysis task description"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Output directory for charts, reports, and results (default: ./output)"
    )

    parser.add_argument(
        "--data-files",
        type=str,
        nargs="*",
        default=[],
        help="Data file paths (CSV/Excel/JSON/Parquet). If not specified, auto-discovers from working directory."
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum analysis steps (default: 20)"
    )

    parser.add_argument(
        "--constraints",
        type=str,
        nargs="*",
        default=[],
        help='Analysis constraints (e.g., "金额=数量×单价×(1-折扣)")'
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.verbose:
        print(f"Analysis goal: {args.prompt}")
        print(f"Output directory: {output_dir}")
        print(f"Data files: {args.data_files or 'auto-discover'}")
        print(f"Max steps: {args.max_steps}")
        if args.constraints:
            print(f"Constraints: {args.constraints}")
        print("-" * 50)

    try:
        result = run_analysis(
            analysis_goal=args.prompt,
            output_dir=str(output_dir),
            data_files=args.data_files,
            max_steps=args.max_steps,
            constraints=args.constraints
        )

        if args.verbose:
            print("-" * 50)
            print(f"Status: {result['status']}")
            print(f"Charts generated: {len(result['charts'])}")
            print(f"Insights discovered: {len(result['insights'])}")
            print(f"Report: {result['report_path']}")
            print(f"Script: {result['script_path']}")
            print(f"Trajectory: {result['trajectory']}")

        result_path = output_dir / "result.json"
        print(f"\nResult saved to: {result_path}")

        if result['status'] == 'failed':
            return 1
        return 0

    except Exception as e:
        error_result = {
            "status": "failed",
            "charts": [],
            "insights": [],
            "report_path": "",
            "script_path": "",
            "trajectory": "",
            "error": str(e)
        }
        result_path = output_dir / "result.json"
        with open(result_path, "w") as f:
            json.dump(error_result, f, indent=2)

        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
