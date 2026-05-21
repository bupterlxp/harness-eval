"""Browser Agent Harness CLI entry point.

Usage:
    python -m harness -p "task description" --output-dir ./output/
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from harness.execution import BrowserAgent


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Browser automation harness for web task execution",
    )

    parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Natural language task description",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Output directory for screenshots, downloads, and results (default: ./output)",
    )

    parser.add_argument(
        "--target-url",
        type=str,
        help="Starting URL (can also be inferred from task description)",
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Maximum number of operation steps (default: 50)",
    )

    parser.add_argument(
        "--credentials",
        type=str,
        help="JSON string or file path containing credentials",
    )

    parser.add_argument(
        "--model",
        type=str,
        help="LLM model name (default: from MODEL_NAME env var or gpt-4o)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    return parser.parse_args()


def extract_url_from_task(task: str) -> str | None:
    """Try to extract a URL from the task description."""
    import re

    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    match = re.search(url_pattern, task)
    if match:
        return match.group(0)

    domain_pattern = r'(?:www\.)?([a-zA-Z0-9-]+(?:\.[a-zA-Z]{2,})+)'
    match = re.search(domain_pattern, task)
    if match:
        return f"https://{match.group(0)}"

    return None


def load_credentials(creds_arg: str | None) -> dict | None:
    """Load credentials from JSON string or file."""
    if not creds_arg:
        return None

    if creds_arg.startswith("{"):
        return json.loads(creds_arg)

    creds_path = Path(creds_arg)
    if creds_path.exists():
        with open(creds_path) as f:
            return json.load(f)

    return None


async def main() -> int:
    """Main entry point."""
    args = parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    target_url = args.target_url or extract_url_from_task(args.prompt)

    if not target_url:
        print("Error: Could not determine target URL. Please provide --target-url or include a URL in the task description.", file=sys.stderr)
        return 1

    credentials = load_credentials(args.credentials)

    if args.verbose:
        print(f"Task: {args.prompt}")
        print(f"Target URL: {target_url}")
        print(f"Output directory: {output_dir}")
        print(f"Max steps: {args.max_steps}")
        print()

    agent = BrowserAgent(
        output_dir=str(output_dir),
        max_steps=args.max_steps,
        model_name=args.model,
    )

    try:
        result = await agent.run(
            target_url=target_url,
            task_description=args.prompt,
            credentials=credentials,
        )

        result_path = output_dir / "result.json"
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)

        if args.verbose:
            print("\nResult:")
            print(json.dumps(result, indent=2))
        else:
            print(f"Status: {result['status']}")
            print(f"Result saved to: {result_path}")

        if result["status"] == "success":
            return 0
        elif result["status"] == "partial":
            return 0
        else:
            return 1

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def run():
    """Synchronous entry point."""
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    run()
