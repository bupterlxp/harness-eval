"""CLI entry point for the Research Agent Harness."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Deep Research Agent Harness - autonomous information retrieval and report generation",
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Research question or topic to investigate",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/",
        help="Directory for output files (default: ./output/)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=4,
        help="Maximum number of iterative retrieval rounds (default: 4)",
    )
    parser.add_argument(
        "--breadth",
        type=int,
        default=4,
        help="Initial breadth of parallel sub-queries (default: 4)",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Path to checkpoint file to resume from",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["auto", "report", "qa"],
        default="auto",
        help="Output mode: auto-detect, report, or qa (default: auto)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from harness.execution import ExecutionLoop
    from harness.state import StateStore

    # Resume from checkpoint if provided
    if args.checkpoint:
        store = StateStore.load_checkpoint(args.checkpoint)
        loop = ExecutionLoop.from_state_store(store, output_dir=output_dir)
    else:
        loop = ExecutionLoop(
            question=args.prompt,
            output_dir=output_dir,
            max_rounds=args.max_rounds,
            initial_breadth=args.breadth,
            mode=args.mode,
        )

    result = await loop.run()

    result_path = output_dir / "result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nResult written to: {result_path}")
    print(f"Status: {result['status']}")
    if result["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
