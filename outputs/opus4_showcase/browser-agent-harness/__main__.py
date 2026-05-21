"""CLI entry point for the browser agent harness."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Browser Agent Harness - autonomous web task completion",
    )
    parser.add_argument(
        "-p", "--prompt", required=True, help="Task description for the browser agent"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output/",
        help="Directory for output files (default: ./output/)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Maximum number of action steps (default: 50)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_false",
        dest="headless",
        help="Run browser with visible UI",
    )
    parser.add_argument(
        "--viewport-width", type=int, default=1280, help="Browser viewport width"
    )
    parser.add_argument(
        "--viewport-height", type=int, default=720, help="Browser viewport height"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Overall timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=5,
        help="Steps between state checkpoints (default: 5)",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="Path to checkpoint file to resume from",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from harness.execution import ExecutionEngine, ExecutionConfig

    config = ExecutionConfig(
        task_prompt=args.prompt,
        output_dir=output_dir,
        max_steps=args.max_steps,
        headless=args.headless,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
        timeout_seconds=args.timeout,
        checkpoint_interval=args.checkpoint_interval,
        resume_from=Path(args.resume_from) if args.resume_from else None,
    )

    engine = ExecutionEngine(config)
    result = await engine.run()

    result_path = output_dir / "result.json"
    with open(result_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nResult written to: {result_path}")
    print(f"Status: {result['status']}")
    if result["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
