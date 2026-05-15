#!/usr/bin/env python3
"""Command line interface for the data analysis agent harness"""

import argparse
import sys
import os
from typing import Optional, List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.core import AgentHarness, DataAnalysisAgent
from harness.evaluation import TrajectoryTracker
from harness.state import ExecutionStateManager


class AnalysisCLI:
    """CLI for data analysis agent"""

    def __init__(self):
        self.parser = self._create_parser()

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create argument parser"""
        parser = argparse.ArgumentParser(
            description="Data Analysis Agent Harness - Perform comprehensive data analysis with stateful execution",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s analyze samples/sales_data.csv \
      --goal "Sales analysis for January 2024" \
      --requirements "Data overview" "Sales trends" "Regional analysis"

  %(prog)s continue saved_state.json

  %(prog)s preview --var sales_data

  %(prog)s plot --last
"""
        )

        subparsers = parser.add_subparsers(dest="command", help="Available commands")
        subparsers.required = True

        # Analyze command
        analyze_parser = subparsers.add_parser("analyze", help="Run a new analysis")
        analyze_parser.add_argument("data_file", help="Path to the data file (CSV)")
        analyze_parser.add_argument("--goal", required=True, help="Analysis goal")
        analyze_parser.add_argument("--requirements", nargs="+", required=True,
                                help="List of analysis requirements")
        analyze_parser.add_argument("--output-dir", default="analysis_results",
                                      help="Directory to save results")

        # Continue command
        continue_parser = subparsers.add_parser("continue", help="Continue from saved state")
        continue_parser.add_argument("state_file", help="Path to saved state file")

        # Preview command
        preview_parser = subparsers.add_parser("preview", help="Preview data variables")
        preview_parser.add_argument("--var", default="main", help="Variable name to preview")
        preview_parser.add_argument("--head", type=int, default=5, help="Number of rows to show")

        # Plot command
        plot_parser = subparsers.add_parser("plot", help="Generate plots")
        plot_parser.add_argument("--last", action="store_true", help="Plot last generated chart")
        plot_parser.add_argument("--step", type=int, help="Plot chart from specific step")

        # Info command
        info_parser = subparsers.add_parser("info", help="Show analysis information")
        info_parser.add_argument("--state", action="store_true", help="Show current state")
        info_parser.add_argument("--history", action="store_true", help="Show analysis history")

        # Export command
        export_parser = subparsers.add_parser("export", help="Export analysis")
        export_parser.add_argument("--format", default="python", choices=["python", "notebook"],
                                     help="Export format")
        export_parser.add_argument("--output", help="Output file path")

        return parser

    def run(self, args: Optional[List[str]] = None) -> int:
        """Run CLI"""
        if args is None:
            args = sys.argv[1:]

        parsed_args = self.parser.parse_args(args)

        try:
            if parsed_args.command == "analyze":
                return self._run_analyze(parsed_args)
            elif parsed_args.command == "continue":
                return self._run_continue(parsed_args)
            elif parsed_args.command == "preview":
                return self._run_preview(parsed_args)
            elif parsed_args.command == "plot":
                return self._run_plot(parsed_args)
            elif parsed_args.command == "info":
                return self._run_info(parsed_args)
            elif parsed_args.command == "export":
                return self._run_export(parsed_args)
            else:
                self.parser.print_help()
                return 1
        except Exception as e:
            print(f"\nError: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def _run_analyze(self, args) -> int:
        """Run new analysis"""
        print(f"Starting new analysis:")
        print(f"  Goal: {args.goal}")
        print(f"  Data file: {args.data_file}")
        print(f"  Requirements: {len(args.requirements)} items")
        print()

        # Create and run analysis
        results = AgentHarness.run_standard_analysis(
            data_file=args.data_file,
            analysis_goal=args.goal,
            requirements=args.requirements
        )

        if results["success"]:
            print("✅ Analysis completed successfully!")
            print(f"\nResults saved to: {args.output_dir}")
            if "save_paths" in results:
                for name, path in results["save_paths"].items():
                    print(f"  - {name}: {path}")

            print("\nNext steps:")
            print("  Use 'preview' command to view data variables")
            print("  Use 'plot' command to generate visualizations")
            print("  Use 'export' command to export the analysis")
        else:
            print("❌ Analysis failed!")
            print(f"Error: {results.get('error', 'Unknown error')}", file=sys.stderr)
            return 1

        return 0

    def _run_continue(self, args) -> int:
        """Continue from saved state"""
        print(f"Continuing analysis from state: {args.state_file}")

        if not os.path.exists(args.state_file):
            print(f"Error: State file not found: {args.state_file}", file=sys.stderr)
            return 1

        try:
            agent = DataAnalysisAgent.from_saved_state(args.state_file)
            print(f"✅ Loaded state successfully")
            print(f"Current state: {agent.current_state.current_step}")
            print(f"Total steps completed: {len(agent.analysis_context.analysis_history.steps)}")

            # TODO: Implement interactive continuation
            print("\nInteractive continuation not fully implemented yet.")
            print("Use the API to continue executing steps programmatically.")

        except Exception as e:
            print(f"Error loading state: {str(e)}", file=sys.stderr)
            return 1

        return 0

    def _run_preview(self, args) -> int:
        """Preview data variables"""
        # This is a placeholder - in real implementation would connect to running agent
        print(f"Previewing variable: {args.var}")
        print(f"Showing first {args.head} rows:")
        print()

        # TODO: Implement actual preview from state
        print("Note: Preview command requires an active analysis session.")
        print("This feature will be implemented in a future update.")
        return 0

    def _run_plot(self, args) -> int:
        """Generate plots"""
        if args.last:
            print("Plotting last generated chart...")
        elif args.step:
            print(f"Plotting chart from step {args.step}...")
        else:
            print("Please specify either --last or --step")
            return 1

        # TODO: Implement actual plotting
        print("\nNote: Plot command requires an active analysis session.")
        print("This feature will be implemented in a future update.")
        return 0

    def _run_info(self, args) -> int:
        """Show analysis information"""
        print("Analysis info:")
        if args.state:
            print("  Showing current state...")
        if args.history:
            print("  Showing analysis history...")

        # TODO: Implement actual info display
        print("\nNote: Info command requires an active analysis session.")
        print("This feature will be implemented in a future update.")
        return 0

    def _run_export(self, args) -> int:
        """Export analysis"""
        print(f"Exporting analysis as {args.format}...")

        # TODO: Implement actual export
        if args.output:
            print(f"Output: {args.output}")

        print("\nNote: Export command requires an active analysis session.")
        print("This feature will be implemented in a future update.")
        return 0


def main():
    """Main entry point"""
    cli = AnalysisCLI()
    return cli.run()


if __name__ == "__main__":
    sys.exit(main())