#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
from playwright.async_api import async_playwright
from harness.execution import ExecutionLoop
from harness import TaskSpec


async def run_task(task_spec: TaskSpec):
    """Run the browser automation task"""
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )

        try:
            # Initialize execution loop
            executor = ExecutionLoop(task_spec)
            await executor.initialize(context)

            # Run execution
            result = await executor.run()

            # Save result
            result_file = os.path.join(task_spec.output_dir, "result.json")
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "status": result.status,
                    "extracted_data": result.extracted_data,
                    "screenshots": result.screenshots,
                    "downloads": result.downloads,
                    "errors": result.errors,
                    "trajectory": result.trajectory
                }, f, indent=2, ensure_ascii=False)

            print(f"Task completed with status: {result.status}")
            print(f"Results saved to: {task_spec.output_dir}")
            print(f"Trajectory log: {result.trajectory}")
            print(f"Result file: {result_file}")

            return result

        finally:
            await context.close()
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description="Browser Automation Harness")
    parser.add_argument("-p", "--prompt", required=True, help="Natural language task description")
    parser.add_argument("--url", help="Target URL to start from")
    parser.add_argument("--output-dir", default="./output", help="Output directory for results")
    parser.add_argument("--max-steps", type=int, default=50, help="Maximum number of steps")
    parser.add_argument("--credentials", help="JSON string of credentials")

    args = parser.parse_args()

    # Parse credentials
    credentials = None
    if args.credentials:
        try:
            credentials = json.loads(args.credentials)
        except json.JSONDecodeError:
            print("Warning: Invalid credentials JSON format")

    # Create task spec
    if not args.url:
        # If no URL provided, use a default or ask user?
        # For now, use a simple test URL
        args.url = "https://example.com"

    task_spec = TaskSpec(
        target_url=args.url,
        task_description=args.prompt,
        credentials=credentials,
        output_dir=args.output_dir,
        max_steps=args.max_steps
    )

    # Run the task
    asyncio.run(run_task(task_spec))


if __name__ == "__main__":
    main()