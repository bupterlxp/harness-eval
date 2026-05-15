#!/usr/bin/env python3
"""CLI for Research Agent Harness.

Interactive command-line interface supporting:
- Long-task progress reporting
- Real-time search status display
- Section draft review
- Commands: /sources, /gaps, /outline, /verify
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from harness.core import ResearchHarness
from harness.schemas import ResearchTask, ResearchState
from harness.domain.tools import DomainTools


class ResearchCLI:
    """Interactive CLI for the research agent."""

    def __init__(self, harness: ResearchHarness) -> None:
        self.harness = harness
        self.domain_tools = DomainTools()
        self._setup_tools()
        self._running = False

    def _setup_tools(self) -> None:
        """Register domain tools with harness."""
        tools = self.domain_tools

        self.harness.register_tool(
            "web_search",
            tools.web_search,
            "Search the web for information",
        )
        self.harness.register_tool(
            "fetch_page",
            tools.fetch_page,
            "Fetch content from a URL",
        )
        self.harness.register_tool(
            "extract_facts",
            tools.extract_facts,
            "Extract facts from content",
        )
        self.harness.register_tool(
            "evaluate_source",
            tools.evaluate_source,
            "Evaluate source quality",
        )
        self.harness.register_tool(
            "format_citation",
            tools.format_citation,
            "Format a citation",
        )
        self.harness.register_tool(
            "cross_validate",
            tools.cross_validate,
            "Cross-validate a claim",
        )
        self.harness.register_tool(
            "draft_section",
            tools.draft_section,
            "Draft a report section",
        )
        self.harness.register_tool(
            "decompose_questions",
            tools.decompose_questions,
            "Decompose questions into queries",
        )
        self.harness.register_tool(
            "analyze_gap",
            tools.analyze_gap,
            "Analyze information gaps",
        )
        self.harness.register_tool(
            "generate_gap_queries",
            tools.generate_gap_queries,
            "Generate gap-filling queries",
        )

    def print_header(self) -> None:
        """Print CLI header."""
        print("\n" + "=" * 60)
        print("  Research Agent Harness v1.0")
        print("  Deep Research & Information Retrieval")
        print("=" * 60)
        print("\nCommands:")
        print("  /sources  - List collected sources with ratings")
        print("  /gaps     - Show information gaps by section")
        print("  /outline  - Display report outline and progress")
        print("  /verify   - Verify a claim against evidence")
        print("  /status   - Show current research status")
        print("  /help     - Show this help message")
        print("  /quit     - Exit the CLI")
        print("-" * 60 + "\n")

    def print_progress(self, message: str) -> None:
        """Print progress message."""
        print(f"  → {message}")

    def print_state_change(self, state: ResearchState, message: str) -> None:
        """Print state change notification."""
        state_icons = {
            ResearchState.DECOMPOSE: "📋",
            ResearchState.SEARCH: "🔍",
            ResearchState.EVALUATE: "⚖️",
            ResearchState.EXTRACT: "📝",
            ResearchState.ORGANIZE: "📊",
            ResearchState.GAP_FILL: "🔄",
            ResearchState.CROSS_VALIDATE: "✅",
            ResearchState.DRAFT: "✍️",
            ResearchState.CONSISTENCY_CHECK: "🔗",
            ResearchState.FINALIZE: "📄",
            ResearchState.COMPLETED: "🎉",
        }
        icon = state_icons.get(state, "•")
        print(f"\n{icon} [{state.value.upper()}] {message}")

    def cmd_sources(self) -> None:
        """Handle /sources command."""
        sources = self.harness.get_sources()

        if not sources:
            print("\nNo sources collected yet.\n")
            return

        print(f"\n{'=' * 60}")
        print(f"  COLLECTED SOURCES ({len(sources)} total)")
        print(f"{'=' * 60}\n")

        for i, source in enumerate(sources, 1):
            reliability = source.get("reliability", "unknown")
            score = source.get("overall_score", 0)
            status = "✓" if source.get("evaluated") else "?"

            reliability_colors = {
                "academic_paper": "🟢",
                "official_docs": "🟢",
                "tech_blog": "🟡",
                "news": "🟡",
                "forum": "🟠",
                "unknown": "⚪",
            }
            color = reliability_colors.get(reliability, "⚪")

            print(f"  {i}. {color} [{reliability}] Score: {score:.2f} {status}")
            print(f"     {source.get('title', 'Untitled')[:50]}...")
            print(f"     {source.get('url', '')[:60]}")
            print()

    def cmd_gaps(self) -> None:
        """Handle /gaps command."""
        gaps = self.harness.get_gaps()

        if not gaps:
            print("\nNo information gaps detected.\n")
            return

        print(f"\n{'=' * 60}")
        print("  INFORMATION GAPS")
        print(f"{'=' * 60}\n")

        for gap in gaps:
            section = gap["section"]
            current = gap["current_evidence"]
            required = gap["required_evidence"]
            gap_size = gap["gap_size"]

            bar_filled = "█" * current
            bar_empty = "░" * gap_size
            bar = bar_filled + bar_empty

            print(f"  {section}")
            print(f"     [{bar}] {current}/{required} evidence items")
            print(f"     Gap: Need {gap_size} more items")
            print()

    def cmd_outline(self) -> None:
        """Handle /outline command."""
        outline = self.harness.get_outline()

        print(f"\n{'=' * 60}")
        print("  REPORT OUTLINE")
        print(f"{'=' * 60}\n")

        status_icons = {
            "empty": "○",
            "partial": "◐",
            "complete": "●",
        }

        for section_name, info in outline.items():
            status = info.get("status", "empty")
            icon = status_icons.get(status, "○")
            word_count = info.get("word_count", 0)
            evidence_count = info.get("evidence_count", 0)
            citation_count = info.get("citation_count", 0)

            print(f"  {icon} {section_name}")
            print(f"     Words: {word_count} | Evidence: {evidence_count} | Citations: {citation_count}")
            print()

    def cmd_verify(self, claim: str) -> None:
        """Handle /verify command."""
        if not claim:
            print("\nUsage: /verify <claim to verify>\n")
            return

        result = self.harness.verify_claim(claim)

        print(f"\n{'=' * 60}")
        print("  CLAIM VERIFICATION")
        print(f"{'=' * 60}\n")

        print(f"  Claim: {result['claim'][:80]}...")
        print(f"  Status: {result['verification_status'].upper()}")
        print()

        if result["supporting_evidence"]:
            print("  Supporting Evidence:")
            for ev in result["supporting_evidence"][:3]:
                print(f"    • {ev['content'][:100]}...")
                print(f"      Source: {ev['source_url'][:50]}")
                print()

    def cmd_status(self) -> None:
        """Handle /status command."""
        summary = self.harness.get_state_summary()

        print(f"\n{'=' * 60}")
        print("  RESEARCH STATUS")
        print(f"{'=' * 60}\n")

        print(f"  Current State: {summary.get('state', 'unknown')}")
        print(f"  Sources: {summary.get('sources', 0)}")
        print(f"  Evidence: {summary.get('evidence', 0)}")
        print(f"  Citations: {summary.get('citations', 0)}")
        print(f"  Words: {summary.get('word_count', 0)}")
        print(f"  Hops Used: {summary.get('hops', 0)}/{self.harness.max_hops}")
        print()

    def handle_command(self, command: str) -> bool:
        """Handle a CLI command. Returns False to exit."""
        parts = command.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/sources":
            self.cmd_sources()
        elif cmd == "/gaps":
            self.cmd_gaps()
        elif cmd == "/outline":
            self.cmd_outline()
        elif cmd == "/verify":
            self.cmd_verify(args)
        elif cmd == "/status":
            self.cmd_status()
        elif cmd == "/help":
            self.print_header()
        elif cmd == "/quit" or cmd == "/exit":
            print("\nGoodbye!\n")
            return False
        else:
            print(f"\nUnknown command: {cmd}")
            print("Type /help for available commands.\n")

        return True

    async def run_research(self) -> dict:
        """Run the research pipeline with progress reporting."""
        async def on_state_change(state: ResearchState, message: str) -> None:
            self.print_state_change(state, message)

        async def on_progress(message: str) -> None:
            self.print_progress(message)

        self.harness.set_callbacks(
            on_state_change=on_state_change,
            on_progress=on_progress,
        )

        print("\nStarting research pipeline...\n")
        result = await self.harness.run()

        print("\n" + "=" * 60)
        print("  RESEARCH COMPLETE")
        print("=" * 60)
        print(f"\n  Sources collected: {len(result.get('sources', []))}")
        print(f"  Citations created: {result.get('citations', 0)}")
        print(f"  Evidence extracted: {result.get('evidence_count', 0)}")
        print(f"  Multi-hop iterations: {result.get('hops_used', 0)}")
        print()

        return result

    async def interactive_loop(self) -> None:
        """Run interactive command loop."""
        self._running = True

        while self._running:
            try:
                command = input("\n> ").strip()

                if not command:
                    continue

                if command.startswith("/"):
                    self._running = self.handle_command(command)
                else:
                    print("Enter a command starting with / or type /help")

            except KeyboardInterrupt:
                print("\n\nInterrupted. Type /quit to exit.\n")
            except EOFError:
                break

    async def run_full_pipeline(self, output_path: Optional[Path] = None) -> None:
        """Run full research pipeline and save results."""
        result = await self.run_research()

        if output_path:
            report = result.get("report", "")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"Report saved to: {output_path}")

        print("\nEntering interactive mode. Type /help for commands.\n")
        await self.interactive_loop()


def create_cli(task_path: Path, trajectory_path: Optional[Path] = None) -> ResearchCLI:
    """Create CLI from task file."""
    harness = ResearchHarness.from_json_file(task_path, trajectory_path=trajectory_path)
    return ResearchCLI(harness)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Research Agent Harness CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "task_file",
        type=Path,
        help="Path to research task JSON file",
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output path for generated report",
    )

    parser.add_argument(
        "-t", "--trajectory",
        type=Path,
        help="Path for JSONL trajectory log",
    )

    parser.add_argument(
        "--max-hops",
        type=int,
        default=3,
        help="Maximum multi-hop search iterations (default: 3)",
    )

    parser.add_argument(
        "--interactive-only",
        action="store_true",
        help="Start in interactive mode without running pipeline",
    )

    args = parser.parse_args()

    if not args.task_file.exists():
        print(f"Error: Task file not found: {args.task_file}")
        sys.exit(1)

    try:
        cli = create_cli(args.task_file, args.trajectory)
        cli.harness.max_hops = args.max_hops

        cli.print_header()

        if args.interactive_only:
            asyncio.run(cli.interactive_loop())
        else:
            asyncio.run(cli.run_full_pipeline(args.output))

    except KeyboardInterrupt:
        print("\n\nAborted.\n")
        sys.exit(130)
    except Exception as e:
        print(f"\nError: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
