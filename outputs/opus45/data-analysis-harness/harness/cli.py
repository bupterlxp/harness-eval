#!/usr/bin/env python3
"""
CLI Interface for Data Analysis Harness

Provides interactive command-line interface with:
- /preview [var] - Preview variable data
- /plot [last] - Show last generated chart
- /check [expr] - Execute validation expression
- /export - Export analysis as Python script
- /rollback [step] - Rollback to a specific step
- /status - Show current analysis status
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from harness.core import AnalysisConfig, DataAnalysisHarness
from harness.schemas import AnalysisState


class AnalysisCLI:
    """Interactive CLI for data analysis."""

    def __init__(self, harness: DataAnalysisHarness):
        self.harness = harness
        self.running = True

    def print_welcome(self) -> None:
        """Print welcome message."""
        print("=" * 60)
        print("Data Analysis Harness - Interactive Mode")
        print("=" * 60)
        print("\nCommands:")
        print("  /run           - Run complete analysis")
        print("  /step [state]  - Execute single step")
        print("  /preview [var] - Preview variable (df_raw, df_clean, etc.)")
        print("  /plot [last]   - Show chart info")
        print("  /check [expr]  - Evaluate expression")
        print("  /rollback [n]  - Rollback to step n")
        print("  /status        - Show analysis status")
        print("  /export        - Export as Python script")
        print("  /trajectory    - Show execution trajectory")
        print("  /help          - Show this help")
        print("  /quit          - Exit")
        print()

    def run(self) -> None:
        """Run interactive CLI loop."""
        self.print_welcome()

        while self.running:
            try:
                user_input = input("\n> ").strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    self.handle_command(user_input)
                else:
                    print(f"Unknown input. Use /help for commands.")

            except KeyboardInterrupt:
                print("\n\nInterrupted. Use /quit to exit.")
            except EOFError:
                break

    def handle_command(self, command: str) -> None:
        """Handle a CLI command."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/run": self.cmd_run,
            "/step": self.cmd_step,
            "/preview": self.cmd_preview,
            "/plot": self.cmd_plot,
            "/check": self.cmd_check,
            "/rollback": self.cmd_rollback,
            "/status": self.cmd_status,
            "/export": self.cmd_export,
            "/trajectory": self.cmd_trajectory,
            "/help": lambda _: self.print_welcome(),
            "/quit": self.cmd_quit,
            "/exit": self.cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            handler(args)
        else:
            print(f"Unknown command: {cmd}")
            print("Use /help for available commands.")

    def cmd_run(self, args: str) -> None:
        """Run complete analysis."""
        print("Running complete analysis...")
        results = self.harness.run()

        success_count = sum(1 for r in results if r.success)
        print(f"\nCompleted {len(results)} steps ({success_count} successful)")

        for result in results:
            status = "✓" if result.success else "✗"
            print(f"  {status} {result.findings[0] if result.findings else 'Step completed'}")

        print(f"\nCharts generated: {len(self.harness.get_charts())}")
        print(f"Insights found: {len(self.harness.get_insights())}")

    def cmd_step(self, args: str) -> None:
        """Execute a single step."""
        if not args:
            next_state = self.harness.execution.get_next_state()
            if next_state:
                args = next_state.value
            else:
                print("Analysis is complete. No more steps.")
                return

        try:
            state = AnalysisState(args.lower())
        except ValueError:
            print(f"Unknown state: {args}")
            print(f"Available states: {', '.join(s.value for s in AnalysisState)}")
            return

        print(f"Executing step: {state.value}...")
        result = self.harness.execute_step(state)

        status = "Success" if result.success else "Failed"
        print(f"\n{status}")

        for finding in result.findings:
            print(f"  - {finding}")

        if result.charts:
            print(f"Charts generated: {len(result.charts)}")
        if result.error:
            print(f"Error: {result.error}")

    def cmd_preview(self, args: str) -> None:
        """Preview a variable."""
        var_name = args.strip() or "df_clean"

        value = self.harness.get_variable(var_name)
        if value is None:
            print(f"Variable '{var_name}' not found.")
            print("Available variables:")
            for name in self.harness.state.variables:
                print(f"  - {name}")
            return

        if isinstance(value, pd.DataFrame):
            print(f"\n{var_name}: DataFrame ({len(value)} rows × {len(value.columns)} columns)")
            print("\nColumns:", list(value.columns))
            print("\nHead:")
            print(value.head(10).to_string())
            print("\nDtypes:")
            print(value.dtypes)
        elif isinstance(value, dict):
            print(f"\n{var_name}: dict ({len(value)} keys)")
            for k, v in list(value.items())[:10]:
                print(f"  {k}: {type(v).__name__}")
        elif isinstance(value, list):
            print(f"\n{var_name}: list ({len(value)} items)")
            for item in value[:5]:
                print(f"  - {item}")
        else:
            print(f"\n{var_name}: {type(value).__name__}")
            print(value)

    def cmd_plot(self, args: str) -> None:
        """Show chart information."""
        charts = self.harness.get_charts()

        if not charts:
            print("No charts generated yet.")
            return

        if args.lower() == "last" or not args:
            chart = charts[-1]
            print(f"\nLast chart: {chart.title}")
            print(f"  Type: {chart.chart_type}")
            print(f"  File: {chart.file_path}")
            print(f"  Step: {chart.step_number}")
        else:
            print(f"\nAll charts ({len(charts)}):")
            for i, chart in enumerate(charts, 1):
                print(f"  {i}. [{chart.chart_type}] {chart.title}")
                print(f"     File: {chart.file_path}")

    def cmd_check(self, args: str) -> None:
        """Execute a validation expression."""
        if not args:
            print("Usage: /check <expression>")
            print("Example: /check df_clean['sales_amount'].sum()")
            return

        df_clean = self.harness.get_dataframe("df_clean")
        df_raw = self.harness.get_dataframe("df_raw")

        local_vars = {
            "df_clean": df_clean,
            "df_raw": df_raw,
            "pd": pd,
        }

        for name, value in self.harness.state.variables.items():
            if name not in local_vars:
                local_vars[name] = value

        try:
            result = eval(args, {"__builtins__": {}}, local_vars)
            print(f"\nResult: {result}")
        except Exception as e:
            print(f"\nError: {e}")

    def cmd_rollback(self, args: str) -> None:
        """Rollback to a specific step."""
        if not args:
            points = self.harness.execution.get_available_rollback_points()
            if not points:
                print("No rollback points available.")
                return

            print("\nAvailable rollback points:")
            for step_num, state, desc in points:
                print(f"  Step {step_num}: {state.value} - {desc}")
            print("\nUsage: /rollback <step_number>")
            return

        try:
            step_num = int(args)
        except ValueError:
            try:
                state = AnalysisState(args.lower())
                if self.harness.rollback_to(state):
                    print(f"Rolled back to state: {state.value}")
                else:
                    print(f"Cannot rollback to state: {state.value}")
            except ValueError:
                print(f"Invalid step number or state: {args}")
            return

        if self.harness.rollback_to_step(step_num):
            print(f"Rolled back to step {step_num}")
            print(f"Current state: {self.harness.state.current_state.value}")
        else:
            print(f"Cannot rollback to step {step_num}")

    def cmd_status(self, args: str) -> None:
        """Show analysis status."""
        progress = self.harness.get_progress()
        print("\n" + self.harness.get_context_summary())
        print(f"\nProgress: {progress['progress_percent']:.0f}%")
        print(f"Current state: {progress['current_state']}")
        print(f"Step number: {progress['step_number']}")

    def cmd_export(self, args: str) -> None:
        """Export analysis as Python script."""
        filepath = args.strip() or "analysis_export.py"
        result = self.harness.export_script(filepath)
        print(f"Exported to: {result}")

    def cmd_trajectory(self, args: str) -> None:
        """Show execution trajectory."""
        trajectory = self.harness.get_trajectory()
        print(trajectory)

    def cmd_quit(self, args: str) -> None:
        """Exit the CLI."""
        self.running = False
        print("Goodbye!")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Data Analysis Harness CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "data_file",
        nargs="?",
        default="./samples/sales_data.csv",
        help="Path to data CSV file",
    )
    parser.add_argument(
        "-o", "--output",
        default="./output",
        help="Output directory for charts and reports",
    )
    parser.add_argument(
        "--goal",
        default="Analyze e-commerce sales data for January 2024",
        help="Analysis goal description",
    )
    parser.add_argument(
        "--auto-run",
        action="store_true",
        help="Automatically run complete analysis without interactive mode",
    )
    parser.add_argument(
        "--keep-invalid-discount",
        action="store_true",
        help="Keep records with discount > 1.0",
    )

    args = parser.parse_args()

    if not Path(args.data_file).exists():
        print(f"Error: Data file not found: {args.data_file}")
        sys.exit(1)

    config = AnalysisConfig(
        data_file=args.data_file,
        output_dir=args.output,
        analysis_goal=args.goal,
        exclude_invalid_discount=not args.keep_invalid_discount,
    )

    print(f"Initializing harness with data: {args.data_file}")
    harness = DataAnalysisHarness(config)

    if args.auto_run:
        print("Running complete analysis...")
        results = harness.run()
        success_count = sum(1 for r in results if r.success)
        print(f"\nCompleted {len(results)} steps ({success_count} successful)")
        print(f"Charts: {len(harness.get_charts())}")
        print(f"Insights: {len(harness.get_insights())}")
        print(f"\nOutput directory: {args.output}")
    else:
        cli = AnalysisCLI(harness)
        cli.run()


if __name__ == "__main__":
    main()
