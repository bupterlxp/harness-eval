"""Tests for harness package initialization and CLI."""

import subprocess
import sys

import pytest


class TestPackageImport:
    """Tests for package imports."""

    def test_import_harness(self):
        """Test that harness package can be imported."""
        import harness
        assert harness.__version__ is not None

    def test_import_all_modules(self):
        """Test that all six modules can be imported."""
        from harness import execution
        from harness import tools
        from harness import context
        from harness import state
        from harness import lifecycle
        from harness import evaluation

        assert execution is not None
        assert tools is not None
        assert context is not None
        assert state is not None
        assert lifecycle is not None
        assert evaluation is not None

    def test_execution_classes_available(self):
        """Test key execution classes are available."""
        from harness.execution import ExecutionLoop, StateMachine
        assert ExecutionLoop is not None
        assert StateMachine is not None

    def test_tools_classes_available(self):
        """Test key tools classes are available."""
        from harness.tools import ToolRegistry, ToolResult, ToolSchema
        assert ToolRegistry is not None
        assert ToolResult is not None
        assert ToolSchema is not None

    def test_context_classes_available(self):
        """Test key context classes are available."""
        from harness.context import ContextManager, ContextRole
        assert ContextManager is not None
        assert ContextRole is not None

    def test_state_classes_available(self):
        """Test key state classes are available."""
        from harness.state import StateStore, AgentPhase
        assert StateStore is not None
        assert AgentPhase is not None

    def test_lifecycle_classes_available(self):
        """Test key lifecycle classes are available."""
        from harness.lifecycle import LifecycleManager, BudgetManager
        assert LifecycleManager is not None
        assert BudgetManager is not None

    def test_evaluation_classes_available(self):
        """Test key evaluation classes are available."""
        from harness.evaluation import TrajectoryLogger, EvaluationMetrics
        assert TrajectoryLogger is not None
        assert EvaluationMetrics is not None


class TestCLI:
    """Tests for CLI functionality."""

    def test_cli_help(self):
        """Test CLI help command."""
        result = subprocess.run(
            [sys.executable, "-m", "harness", "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "harness" in result.stdout.lower()

    def test_cli_run_help(self):
        """Test CLI run subcommand help."""
        result = subprocess.run(
            [sys.executable, "-m", "harness", "run", "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "--task" in result.stdout
        assert "--output" in result.stdout

    def test_cli_missing_task_file(self):
        """Test CLI with missing task file."""
        result = subprocess.run(
            [sys.executable, "-m", "harness", "run",
             "--task", "nonexistent.json",
             "--output", "result.json"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower()
