#!/usr/bin/env python3
"""
CLI for the Code Agent Harness.

Supports:
- Single-run mode: python -m harness.cli run
- Interactive mode: python -m harness.cli interactive
- Slash commands: /clear, /compact, /resume, /test, /status
"""

import argparse
import os
import signal
import sys
from pathlib import Path
from typing import Optional

from harness.core import CodeAgentHarness, HarnessConfig


class CLI:
    """Interactive CLI for the code agent harness."""

    def __init__(self, work_dir: Path, target_file: str, test_file: str) -> None:
        self.work_dir = work_dir
        self.config = HarnessConfig(
            work_dir=work_dir,
            target_file=target_file,
            test_file=test_file,
        )
        self.harness: Optional[CodeAgentHarness] = None
        self._running = False

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        def handler(signum, frame):
            print("\nInterrupt received, shutting down...")
            self._running = False
            if self.harness:
                self.harness.abort()
            sys.exit(0)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def run(self) -> int:
        """Run the harness in single-run mode."""
        self._setup_signal_handlers()

        print(f"Code Agent Harness")
        print(f"Working directory: {self.work_dir}")
        print(f"Target: {self.config.target_file}")
        print(f"Tests: {self.config.test_file}")
        print("-" * 50)

        self.harness = CodeAgentHarness(self.config)
        result = self.harness.run()

        if result["success"]:
            print("\n✓ All bugs fixed successfully!")
            return 0
        else:
            print(f"\n✗ Finished with state: {result['state']}")
            if "error" in result:
                print(f"Error: {result['error']}")
            return 1

    def interactive(self) -> None:
        """Run in interactive mode."""
        self._setup_signal_handlers()
        self._running = True

        print("Code Agent Harness - Interactive Mode")
        print("Commands: /run, /test [pattern], /status, /clear, /help, /quit")
        print("-" * 50)

        self.harness = CodeAgentHarness(self.config)

        while self._running:
            try:
                line = input("\n> ").strip()
            except EOFError:
                break

            if not line:
                continue

            if line.startswith("/"):
                self._handle_command(line)
            else:
                print("Enter a command (start with /) or use /help")

    def _handle_command(self, line: str) -> None:
        """Handle a slash command."""
        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "run": self._cmd_run,
            "test": self._cmd_test,
            "status": self._cmd_status,
            "clear": self._cmd_clear,
            "compact": self._cmd_compact,
            "resume": self._cmd_resume,
            "help": self._cmd_help,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            handler(args)
        else:
            print(f"Unknown command: {cmd}")
            self._cmd_help("")

    def _cmd_run(self, args: str) -> None:
        """Run the full fix workflow."""
        if not self.harness:
            self.harness = CodeAgentHarness(self.config)

        result = self.harness.run()
        if result["success"]:
            print("\n✓ All bugs fixed successfully!")
        else:
            print(f"\n✗ Finished with state: {result['state']}")

    def _cmd_test(self, pattern: str) -> None:
        """Run tests with optional pattern."""
        from harness.domain.tools import TestRunner

        runner = TestRunner(self.work_dir)
        result, _ = runner.run({
            "pattern": pattern if pattern else None,
            "file_path": self.config.test_file,
            "verbose": True,
        })

        print(f"\nTest Results:")
        print(f"  Passed: {result.result.passed}")
        print(f"  Failed: {result.result.failed}")
        print(f"  Errors: {result.result.errors}")

        if result.result.failures:
            print("\nFailures:")
            for f in result.result.failures:
                print(f"  - {f.get('test', 'unknown')}")

    def _cmd_status(self, args: str) -> None:
        """Show current status."""
        if not self.harness:
            print("Harness not initialized. Use /run first.")
            return

        status = self.harness.get_status()
        print(f"\nStatus:")
        print(f"  State: {status['state']['main_state']}")
        if status['state'].get('fix_state'):
            print(f"  Fix State: {status['state']['fix_state']}")
        print(f"  Progress: {status['progress']['fixed']}/{status['progress']['total']} bugs fixed")
        if status['current_bug']:
            print(f"  Current Bug: {status['current_bug']}")

    def _cmd_clear(self, args: str) -> None:
        """Clear state and restart."""
        if self.harness:
            self.harness.state.clear()
        self.harness = CodeAgentHarness(self.config)
        print("State cleared.")

    def _cmd_compact(self, args: str) -> None:
        """Compact context (placeholder for LLM context management)."""
        if self.harness:
            self.harness.context.clear_all()
        print("Context compacted.")

    def _cmd_resume(self, args: str) -> None:
        """Resume from saved state."""
        if not self.harness:
            self.harness = CodeAgentHarness(self.config)

        if self.harness.state.load():
            print("Resumed from saved state.")
            status = self.harness.get_status()
            print(f"Progress: {status['progress']['fixed']}/{status['progress']['total']} bugs fixed")
        else:
            print("No saved state found.")

    def _cmd_help(self, args: str) -> None:
        """Show help."""
        print("""
Commands:
  /run           - Run the full bug fixing workflow
  /test [pat]    - Run tests (optionally filtered by pattern)
  /status        - Show current progress
  /clear         - Clear state and restart
  /compact       - Compact context
  /resume        - Resume from saved state
  /help          - Show this help
  /quit          - Exit
""")

    def _cmd_quit(self, args: str) -> None:
        """Exit the CLI."""
        print("Goodbye!")
        self._running = False
        sys.exit(0)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Code Agent Harness")
    parser.add_argument(
        "mode",
        choices=["run", "interactive"],
        default="run",
        nargs="?",
        help="Execution mode",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path.cwd(),
        help="Working directory",
    )
    parser.add_argument(
        "--target",
        default="buggy_server.py",
        help="Target file to fix",
    )
    parser.add_argument(
        "--tests",
        default="test_server.py",
        help="Test file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    cli = CLI(
        work_dir=args.work_dir,
        target_file=args.target,
        test_file=args.tests,
    )

    if args.mode == "interactive":
        cli.interactive()
    else:
        sys.exit(cli.run())


if __name__ == "__main__":
    main()
