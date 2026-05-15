"""
cli.py - Command-line interface for the browser agent harness.

Provides interactive commands:
- /screenshot: Take immediate screenshot
- /state: Show extracted data
- /retry [step_id]: Retry a step
- /skip [step_id]: Skip a step
- /report: Generate partial report
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.core import BrowserAgentHarness
from harness.schemas import TaskResult


class HarnessCLI:
    """Interactive CLI for the browser agent harness."""

    def __init__(self, harness: BrowserAgentHarness) -> None:
        self._harness = harness
        self._running = False
        self._paused = False

    def print_header(self) -> None:
        """Print CLI header."""
        print("=" * 60)
        print("Browser Agent Harness - Interactive Mode")
        print("=" * 60)
        print("\nCommands:")
        print("  /screenshot    - Take screenshot of current page")
        print("  /state         - Show all extracted data")
        print("  /retry <step>  - Retry a specific step")
        print("  /skip <step>   - Skip a specific step")
        print("  /report        - Generate current report")
        print("  /pause         - Pause execution")
        print("  /resume        - Resume execution")
        print("  /progress      - Show execution progress")
        print("  /quit          - Stop and exit")
        print("=" * 60)

    def print_progress(self, progress: dict[str, Any]) -> None:
        """Print execution progress."""
        print("\n--- Progress ---")
        print(f"State: {progress.get('state', 'unknown')}")
        print(f"Phase: {progress.get('phase', 'unknown')}")
        print(f"Current Step: {progress.get('current_step', 'None')}")
        print(f"Completed: {progress.get('completed', 0)}/{progress.get('total', 0)}")
        print(f"Failed: {progress.get('failed', 0)}")
        print(f"Skipped: {progress.get('skipped', 0)}")
        print("----------------\n")

    def print_state(self, state: dict[str, Any]) -> None:
        """Print current state."""
        print("\n--- Extracted Data ---")
        data = state.get("extracted_data", {})
        for key, value in data.items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {key}: {value}")
        print("----------------------\n")

    def log(self, message: str) -> None:
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    async def approval_callback(self, action: str) -> bool:
        """Handle approval requests."""
        print(f"\n{'='*40}")
        print(f"APPROVAL REQUIRED: {action}")
        print(f"{'='*40}")

        while True:
            response = input("Approve? [y/n]: ").strip().lower()
            if response in ("y", "yes"):
                return True
            elif response in ("n", "no"):
                return False
            print("Please enter 'y' or 'n'")

    async def handle_command(self, command: str) -> bool:
        """Handle a CLI command. Returns False to quit."""
        parts = command.strip().split()
        if not parts:
            return True

        cmd = parts[0].lower()

        if cmd == "/screenshot":
            await self._handle_screenshot()

        elif cmd == "/state":
            state = self._harness.get_state()
            self.print_state(state)

        elif cmd == "/retry":
            if len(parts) < 2:
                print("Usage: /retry <step_id>")
            else:
                try:
                    step_id = int(parts[1])
                    self._harness.retry_step(step_id)
                    self.log(f"Step {step_id} marked for retry")
                except ValueError:
                    print("Invalid step ID")

        elif cmd == "/skip":
            if len(parts) < 2:
                print("Usage: /skip <step_id>")
            else:
                try:
                    step_id = int(parts[1])
                    self._harness.skip_step(step_id)
                    self.log(f"Step {step_id} marked for skip")
                except ValueError:
                    print("Invalid step ID")

        elif cmd == "/report":
            state = self._harness.get_state()
            self._print_partial_report(state)

        elif cmd == "/pause":
            self._harness.pause()
            self._paused = True
            self.log("Execution paused")

        elif cmd == "/resume":
            self._harness.resume()
            self._paused = False
            self.log("Execution resumed")

        elif cmd == "/progress":
            state = self._harness.get_state()
            if state.get("progress"):
                self.print_progress(state["progress"])
            else:
                print("No progress data available")

        elif cmd in ("/quit", "/exit", "/q"):
            self.log("Stopping execution...")
            return False

        else:
            print(f"Unknown command: {cmd}")

        return True

    async def _handle_screenshot(self) -> None:
        """Take an immediate screenshot."""
        if not self._harness._page:
            print("No browser page available")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"output/screenshots/manual_{timestamp}.png"
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        try:
            await self._harness._page.screenshot(path=path)
            self.log(f"Screenshot saved: {path}")
        except Exception as e:
            print(f"Screenshot failed: {e}")

    def _print_partial_report(self, state: dict[str, Any]) -> None:
        """Print a partial execution report."""
        print("\n" + "=" * 50)
        print("PARTIAL EXECUTION REPORT")
        print("=" * 50)

        progress = state.get("progress", {})
        print(f"\nExecution State: {progress.get('state', 'unknown')}")
        print(f"Current Phase: {progress.get('phase', 'unknown')}")
        print(f"Steps: {progress.get('completed', 0)}/{progress.get('total', 0)} completed")

        print("\n--- Extracted Data ---")
        data = state.get("extracted_data", {})
        for key, value in sorted(data.items()):
            if isinstance(value, dict):
                print(f"\n  {key}:")
                for k, v in sorted(value.items()):
                    print(f"    {k}: {v}")
            elif isinstance(value, list):
                print(f"\n  {key}: [{len(value)} items]")
            else:
                print(f"  {key}: {value}")

        print("\n" + "=" * 50)


async def run_cli(scenario_path: str, headless: bool = False) -> TaskResult:
    """Run the harness with CLI interaction."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Error: playwright is required. Install with: pip install playwright")
        print("Then run: playwright install chromium")
        sys.exit(1)

    harness = BrowserAgentHarness(output_dir="output")
    cli = HarnessCLI(harness)

    cli.print_header()
    harness.set_log_callback(cli.log)
    harness.set_approval_callback(cli.approval_callback)

    cli.log(f"Loading scenario from {scenario_path}")
    harness.load_scenario(scenario_path)

    cli.log("Launching browser...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        harness.set_browser(browser, page)

        cli.log("Starting execution...")
        result = await harness.run()

        await browser.close()

    print("\n" + result.to_report())
    return result


def main() -> None:
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Browser Agent Harness CLI")
    parser.add_argument(
        "scenario",
        nargs="?",
        default="samples/task_scenarios.json",
        help="Path to scenario JSON file",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )
    parser.add_argument(
        "--resume",
        type=str,
        help="Resume from checkpoint file",
    )

    args = parser.parse_args()

    if not os.path.exists(args.scenario):
        print(f"Error: Scenario file not found: {args.scenario}")
        sys.exit(1)

    asyncio.run(run_cli(args.scenario, args.headless))


if __name__ == "__main__":
    main()
