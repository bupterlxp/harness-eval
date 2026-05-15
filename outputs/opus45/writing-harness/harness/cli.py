"""
cli.py - Command-line interface for the harness

Implements REPL mode and single-task mode with streaming output,
slash commands, and approval gates.
"""

from __future__ import annotations
import sys
import signal
import uuid
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm

from harness.core import create_harness, Harness
from harness.schemas import ExecutionState


console = Console()


class CLI:
    """Interactive CLI for the harness"""

    SAMPLE_PATH = Path("./samples/the_tell_tale_heart.txt")

    def __init__(self):
        self.harness: Harness | None = None
        self.running = True
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup graceful interrupt handling"""
        def handler(signum, frame):
            if self.harness:
                console.print("\n[yellow]Interrupting... saving state[/yellow]")
                self.harness.interrupt()
            self.running = False

        signal.signal(signal.SIGINT, handler)

    def _output_handler(self, message: str):
        """Handle output from harness"""
        console.print(f"[dim]→[/dim] {message}")

    def _approval_handler(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Handle approval requests"""
        console.print(Panel(
            f"[bold yellow]Approval Required[/bold yellow]\n\n"
            f"Tool: [cyan]{tool_name}[/cyan]\n"
            f"Args: {list(args.keys())}",
            title="Permission Request"
        ))
        return Confirm.ask("Approve this operation?", default=True)

    def _create_harness(self, auto_approve: bool = False) -> Harness:
        """Create a configured harness instance"""
        return create_harness(
            on_output=self._output_handler,
            approval_handler=None if auto_approve else self._approval_handler,
            auto_approve=auto_approve
        )

    def cmd_clear(self):
        """Clear current context"""
        if self.harness:
            self.harness.context.reset()
            console.print("[green]Context cleared[/green]")
        else:
            console.print("[red]No active session[/red]")

    def cmd_compact(self):
        """Compact context"""
        if self.harness:
            before = self.harness.context.get_token_usage()
            compressed = self.harness.context.compress()
            after_tokens = sum(e.token_estimate for e in compressed)
            console.print(f"[green]Compacted: {before['total']} → {after_tokens} tokens[/green]")
        else:
            console.print("[red]No active session[/red]")

    def cmd_resume(self, session_id: str):
        """Resume a previous session"""
        if not session_id:
            sessions = self.harness.list_sessions() if self.harness else []
            if not sessions:
                console.print("[red]No sessions found[/red]")
                return

            table = Table(title="Available Sessions")
            table.add_column("ID")
            table.add_column("Created")
            table.add_column("Updated")

            for s in sessions[:10]:
                table.add_row(s["session_id"][:8], s["created_at"], s["updated_at"])

            console.print(table)
            session_id = Prompt.ask("Session ID to resume")

        self.harness = self._create_harness()
        try:
            final = self.harness.resume(session_id)
            console.print(f"[green]Resumed session {session_id[:8]}, state: {final.current_state.value}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to resume: {e}[/red]")

    def cmd_trajectory(self):
        """Show trajectory path"""
        if self.harness and self.harness.get_trajectory():
            traj = self.harness.get_trajectory()
            console.print(f"[cyan]Trajectory: {traj.output_path}[/cyan]")
            console.print(f"Steps recorded: {len(traj.get_entries())}")
        else:
            console.print("[red]No active trajectory[/red]")

    def cmd_diff(self):
        """Compare current output with sample"""
        if not self.harness or not self.harness.get_final_draft():
            console.print("[red]No generated output to compare[/red]")
            return

        if not self.SAMPLE_PATH.exists():
            console.print(f"[red]Sample not found: {self.SAMPLE_PATH}[/red]")
            return

        try:
            report = self.harness.compare_with_sample(self.SAMPLE_PATH)

            table = Table(title="Sample Comparison Report")
            table.add_column("Dimension")
            table.add_column("Aspect")
            table.add_column("Sample")
            table.add_column("Actual")
            table.add_column("Aligned")
            table.add_column("Component")

            all_comparisons = (
                report.structure_comparisons +
                report.style_comparisons +
                report.imagery_comparisons
            )

            for comp in all_comparisons:
                aligned_str = "[green]✓[/green]" if comp.aligned else "[red]✗[/red]"
                table.add_row(
                    comp.dimension,
                    comp.aspect,
                    comp.sample_value[:20],
                    comp.actual_value[:20],
                    aligned_str,
                    comp.component_attribution or "-"
                )

            console.print(table)
            console.print(f"\n[bold]Overall: {report.overall_alignment_score:.1%}[/bold]")
            console.print(report.summary)

        except Exception as e:
            console.print(f"[red]Comparison failed: {e}[/red]")

    def cmd_help(self):
        """Show help"""
        help_text = """
## Available Commands

| Command | Description |
|---------|-------------|
| `/clear` | Clear current context (C reset, S preserved) |
| `/compact` | Trigger context compression |
| `/resume <id>` | Resume a previous session |
| `/trajectory` | Show trajectory JSONL path |
| `/diff` | Compare output with sample |
| `/sessions` | List saved sessions |
| `/status` | Show current state |
| `/help` | Show this help |
| `/quit` | Exit |

## Running a Task

Enter a task description to start generation:
```
体裁: 心理惊悚
篇幅: 2000-2500 词
核心张力: ...
```
"""
        console.print(Markdown(help_text))

    def cmd_sessions(self):
        """List sessions"""
        if not self.harness:
            self.harness = self._create_harness()

        sessions = self.harness.list_sessions()
        if not sessions:
            console.print("[yellow]No sessions found[/yellow]")
            return

        table = Table(title="Sessions")
        table.add_column("ID")
        table.add_column("Created")
        table.add_column("Updated")

        for s in sessions[:20]:
            table.add_row(
                s["session_id"][:8] + "...",
                s["created_at"][:19],
                s["updated_at"][:19]
            )

        console.print(table)

    def cmd_status(self):
        """Show current status"""
        if not self.harness:
            console.print("[yellow]No active harness[/yellow]")
            return

        session = self.harness.get_session()
        if not session:
            console.print("[yellow]No active session[/yellow]")
            return

        table = Table(title="Current Status")
        table.add_column("Property")
        table.add_column("Value")

        table.add_row("Session ID", session.session_id[:8] + "...")
        table.add_row("State", session.current_state.value)
        table.add_row("Scenes Drafted", str(len(session.scene_drafts)))
        table.add_row("Imagery Items", str(len(session.imagery_table)))
        table.add_row("Revisions", str(session.revision_count))

        if session.final_draft:
            table.add_row("Final Words", str(len(session.final_draft.split())))

        console.print(table)

        token_usage = self.harness.context.get_token_usage()
        console.print(f"\n[dim]Context tokens: {token_usage.get('total', 0)}[/dim]")

    def process_command(self, line: str) -> bool:
        """Process a slash command. Returns False to exit."""
        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "clear":
                self.cmd_clear()
            case "compact":
                self.cmd_compact()
            case "resume":
                self.cmd_resume(args)
            case "trajectory":
                self.cmd_trajectory()
            case "diff":
                self.cmd_diff()
            case "sessions":
                self.cmd_sessions()
            case "status":
                self.cmd_status()
            case "help":
                self.cmd_help()
            case "quit" | "exit":
                return False
            case _:
                console.print(f"[red]Unknown command: {cmd}[/red]")
                self.cmd_help()

        return True

    def run_task(self, task_input: str, auto_approve: bool = False):
        """Run a task to completion"""
        self.harness = self._create_harness(auto_approve=auto_approve)

        console.print(Panel(
            "[bold]Starting story generation...[/bold]\n"
            "Use Ctrl+C to interrupt and save state.",
            title="Harness"
        ))

        try:
            final = self.harness.run(task_input)

            if final.current_state == ExecutionState.COMPLETE:
                console.print("\n[bold green]Generation complete![/bold green]")

                if final.final_draft:
                    console.print(Panel(
                        final.final_draft[:500] + "..." if len(final.final_draft) > 500 else final.final_draft,
                        title=f"Preview ({len(final.final_draft.split())} words)"
                    ))

                traj = self.harness.get_trajectory()
                if traj:
                    console.print(f"\n[dim]Trajectory saved: {traj.output_path}[/dim]")

            elif final.current_state == ExecutionState.ERROR:
                console.print("[bold red]Generation failed[/bold red]")

            elif final.current_state == ExecutionState.SUSPENDED:
                console.print(f"[yellow]Session suspended. Resume with: /resume {final.session_id[:8]}[/yellow]")

        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")

    def repl(self):
        """Run interactive REPL"""
        console.print(Panel(
            "[bold]Short Story Writing Harness[/bold]\n\n"
            "Enter a task description to generate a story,\n"
            "or use /help for commands.",
            title="Welcome"
        ))

        while self.running:
            try:
                line = Prompt.ask("\n[bold cyan]harness[/bold cyan]")
                line = line.strip()

                if not line:
                    continue

                if line.startswith("/"):
                    if not self.process_command(line):
                        break
                else:
                    self.run_task(line)

            except KeyboardInterrupt:
                console.print("\n[yellow]Use /quit to exit[/yellow]")
            except EOFError:
                break

        console.print("[dim]Goodbye![/dim]")


def main():
    """Main entry point"""
    cli = CLI()

    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
        if task.startswith("/"):
            cli.harness = cli._create_harness()
            cli.process_command(task)
        else:
            cli.run_task(task, auto_approve="--auto-approve" in sys.argv)
    else:
        cli.repl()


if __name__ == "__main__":
    main()
