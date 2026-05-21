"""Tests for the execution module."""

import pytest

from harness.execution import (
    ExecutionContext,
    ExecutionState,
    StateMachine,
)


class TestExecutionState:
    """Tests for ExecutionState enum."""

    def test_all_states_defined(self) -> None:
        """Verify all expected states are defined."""
        expected_states = [
            "INIT", "UNDERSTAND", "LOCATE", "PLAN", "EDIT",
            "VALIDATE", "RETRY", "ROLLBACK", "SUCCESS", "FAILED"
        ]
        actual_states = [s.name for s in ExecutionState]
        assert set(expected_states) == set(actual_states)

    def test_states_are_unique(self) -> None:
        """Verify all states have unique values."""
        values = [s.value for s in ExecutionState]
        assert len(values) == len(set(values))


class TestStateMachine:
    """Tests for StateMachine."""

    def test_init_to_understand_transition(self) -> None:
        """Test valid transition from INIT to UNDERSTAND."""
        sm = StateMachine()
        assert sm.can_transition(ExecutionState.INIT, ExecutionState.UNDERSTAND)

    def test_understand_to_locate_transition(self) -> None:
        """Test valid transition from UNDERSTAND to LOCATE."""
        sm = StateMachine()
        assert sm.can_transition(ExecutionState.UNDERSTAND, ExecutionState.LOCATE)

    def test_invalid_transition(self) -> None:
        """Test invalid transition is rejected."""
        sm = StateMachine()
        assert not sm.can_transition(ExecutionState.INIT, ExecutionState.SUCCESS)

    def test_terminal_states(self) -> None:
        """Test terminal state detection."""
        sm = StateMachine()
        assert sm.is_terminal(ExecutionState.SUCCESS)
        assert sm.is_terminal(ExecutionState.FAILED)
        assert not sm.is_terminal(ExecutionState.INIT)
        assert not sm.is_terminal(ExecutionState.EDIT)

    def test_get_valid_transitions(self) -> None:
        """Test getting valid transitions from a state."""
        sm = StateMachine()
        transitions = sm.get_valid_transitions(ExecutionState.VALIDATE)
        assert ExecutionState.SUCCESS in transitions
        assert ExecutionState.RETRY in transitions

    def test_retry_loop_supported(self) -> None:
        """Test that retry loop is supported."""
        sm = StateMachine()
        assert sm.can_transition(ExecutionState.VALIDATE, ExecutionState.RETRY)
        assert sm.can_transition(ExecutionState.RETRY, ExecutionState.EDIT)

    def test_rollback_supported(self) -> None:
        """Test that rollback transitions are supported."""
        sm = StateMachine()
        assert sm.can_transition(ExecutionState.RETRY, ExecutionState.ROLLBACK)
        assert sm.can_transition(ExecutionState.ROLLBACK, ExecutionState.PLAN)
        assert sm.can_transition(ExecutionState.ROLLBACK, ExecutionState.FAILED)


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def test_context_creation(self) -> None:
        """Test creating an execution context."""
        ctx = ExecutionContext(
            task_type="bug_fix",
            description="Fix the login bug",
            repo_path="/tmp/repo",
            test_command="pytest",
            constraints=["no breaking changes"],
        )

        assert ctx.task_type == "bug_fix"
        assert ctx.description == "Fix the login bug"
        assert ctx.repo_path == "/tmp/repo"
        assert ctx.test_command == "pytest"
        assert ctx.constraints == ["no breaking changes"]

    def test_context_defaults(self) -> None:
        """Test default values in execution context."""
        ctx = ExecutionContext(
            task_type="feature",
            description="Add feature",
            repo_path="/tmp",
            test_command=None,
            constraints=[],
        )

        assert ctx.current_state == ExecutionState.INIT
        assert ctx.iteration == 0
        assert ctx.max_iterations == 10
        assert ctx.llm_calls == 0
        assert ctx.edits == []
        assert ctx.retry_count == 0

    def test_context_test_results_default(self) -> None:
        """Test default test results structure."""
        ctx = ExecutionContext(
            task_type="feature",
            description="Add feature",
            repo_path="/tmp",
            test_command=None,
            constraints=[],
        )

        assert ctx.test_results["passed"] == 0
        assert ctx.test_results["failed"] == 0
        assert ctx.test_results["errors"] == []
