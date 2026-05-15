#!/usr/bin/env python3
"""
Main entry point for the agent harness.
"""

import os
import sys
from typing import Dict, Any, Optional

from .state import StateStore
from .tools import ToolRegistry
from .context import ContextManager
from .lifecycle import LifecycleHooks
from .evaluation import TrajectoryRecorder
from .execution import ExecutionStateMachine, AgentState
from .schemas import *


class AgentHarness:
    """Main agent harness class that combines all components."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.state_store = StateStore()
        self.tool_registry = ToolRegistry()
        self.context_manager = ContextManager()
        self.lifecycle_hooks = LifecycleHooks(self.state_store)
        self.trajectory_recorder = TrajectoryRecorder(
            self.config.get("trajectory_file", "trajectory.jsonl")
        )
        self.execution_machine = ExecutionStateMachine(
            state_store=self.state_store,
            tool_registry=self.tool_registry,
            context_manager=self.context_manager,
            lifecycle_hooks=self.lifecycle_hooks,
            trajectory_recorder=self.trajectory_recorder
        )

        # Initialize default tools
        self._register_default_tools()

        # Setup default lifecycle hooks
        self.lifecycle_hooks.setup_default_hooks()

    def _register_default_tools(self) -> None:
        """Register all default tools."""
        from .tools import FileSearchTool, FileEditorTool, TestRunnerTool, GitTool, StaticAnalysisTool
        self.tool_registry.register_tool(FileSearchTool())
        self.tool_registry.register_tool(FileEditorTool())
        self.tool_registry.register_tool(TestRunnerTool())
        self.tool_registry.register_tool(GitTool())
        self.tool_registry.register_tool(StaticAnalysisTool())

    def run(self) -> None:
        """Run the full agent harness workflow."""
        print("Starting agent harness...")
        self.execution_machine.run()
        print("Agent harness completed.")

    def run_tests(self, test_file: str = "test_server.py", pattern: Optional[str] = None) -> Any:
        """Run tests using the test runner tool."""
        return self.tool_registry.execute_tool(
            "test_runner",
            test_file=test_file,
            pattern=pattern
        )

    def list_bugs(self, status: Optional[str] = None) -> List[BugReport]:
        """List all tracked bugs."""
        return self.state_store.bug_tracker.list_bugs(status)

    def add_bug_report(self, bug_report: BugReport) -> int:
        """Add a new bug report."""
        return self.state_store.bug_tracker.add_bug(bug_report)

    def save_state(self, filepath: str = "harness_state.json") -> None:
        """Save harness state to file."""
        self.state_store.save_state(filepath)

    def load_state(self, filepath: str = "harness_state.json") -> None:
        """Load harness state from file."""
        self.state_store.load_state(filepath)


def create_default_harness() -> AgentHarness:
    """Create a default configured agent harness."""
    config = {
        "trajectory_file": "trajectory.jsonl",
        "test_file": "samples/test_server.py",
        "source_file": "samples/buggy_server.py"
    }
    return AgentHarness(config)


if __name__ == "__main__":
    # Run CLI when executed directly
    from harness.cli import main
    main()