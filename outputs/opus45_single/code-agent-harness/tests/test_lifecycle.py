"""Tests for harness.lifecycle module."""

import tempfile
import shutil
import time
from pathlib import Path

import pytest

from harness.lifecycle import (
    LifecycleManager,
    LifecycleEvent,
    HookContext,
    BudgetManager,
    TimeoutError,
)
from harness.state import StateStore, AgentPhase


class TestLifecycleManager:
    """Tests for LifecycleManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d)

    @pytest.fixture
    def state_store(self, temp_dir):
        """Create a StateStore instance."""
        return StateStore(temp_dir)

    @pytest.fixture
    def lifecycle(self, state_store):
        """Create a LifecycleManager instance."""
        return LifecycleManager(state_store)

    def test_register_hook(self, lifecycle):
        """Test registering a custom hook."""
        called = []

        def my_hook(ctx: HookContext):
            called.append(ctx.event)

        lifecycle.register_hook(LifecycleEvent.TASK_START, my_hook)
        lifecycle.trigger(LifecycleEvent.TASK_START)

        assert LifecycleEvent.TASK_START in called

    def test_unregister_hook(self, lifecycle):
        """Test unregistering a hook."""
        called = []

        def my_hook(ctx: HookContext):
            called.append(True)

        lifecycle.register_hook(LifecycleEvent.TASK_START, my_hook)
        success = lifecycle.unregister_hook(LifecycleEvent.TASK_START, my_hook)
        assert success is True

        lifecycle.trigger(LifecycleEvent.TASK_START)
        assert len(called) == 0

    def test_trigger_passes_data(self, lifecycle):
        """Test that trigger passes data to hooks."""
        received_data = {}

        def capture_hook(ctx: HookContext):
            received_data.update(ctx.data)

        lifecycle.register_hook(LifecycleEvent.TASK_START, capture_hook)
        lifecycle.trigger(LifecycleEvent.TASK_START, {"key": "value"})

        assert received_data["key"] == "value"

    def test_default_backup_hook(self, lifecycle, temp_dir, state_store):
        """Test default backup hook backs up files before edit."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("original")

        lifecycle.trigger(LifecycleEvent.BEFORE_EDIT, {"file_path": str(test_file)})

        assert str(test_file.resolve()) in state_store.get_modified_files()

    def test_phase_scope(self, lifecycle, state_store):
        """Test phase scope context manager."""
        assert state_store.current_phase == AgentPhase.INIT

        with lifecycle.phase_scope(AgentPhase.UNDERSTAND):
            assert state_store.current_phase == AgentPhase.UNDERSTAND

    def test_edit_scope_triggers_hooks(self, lifecycle, temp_dir):
        """Test edit scope triggers before/after edit hooks."""
        events = []

        def track_before(ctx):
            events.append("before")

        def track_after(ctx):
            events.append("after")

        lifecycle.register_hook(LifecycleEvent.BEFORE_EDIT, track_before)
        lifecycle.register_hook(LifecycleEvent.AFTER_EDIT, track_after)

        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        with lifecycle.edit_scope(str(test_file)):
            pass

        assert events == ["before", "after"]

    def test_error_boundary_catches_errors(self, lifecycle):
        """Test error boundary triggers error hook."""
        error_caught = []

        def on_error(ctx):
            error_caught.append(ctx.data.get("error"))

        lifecycle.register_hook(LifecycleEvent.ON_ERROR, on_error)

        with pytest.raises(ValueError):
            with lifecycle.error_boundary():
                raise ValueError("Test error")

        assert len(error_caught) == 1
        assert "Test error" in error_caught[0]

    def test_handle_retry(self, lifecycle):
        """Test retry handling triggers hook."""
        retry_info = []

        def on_retry(ctx):
            retry_info.append((ctx.data["reason"], ctx.data["attempt"]))

        lifecycle.register_hook(LifecycleEvent.ON_RETRY, on_retry)
        lifecycle.handle_retry("Test failed", 2)

        assert retry_info == [("Test failed", 2)]

    def test_task_start_creates_snapshot(self, lifecycle, state_store):
        """Test task_start creates initial snapshot."""
        lifecycle.task_start({"task_type": "test"})

        assert len(state_store.snapshots) > 0
        assert state_store.get_metadata("task_spec") == {"task_type": "test"}


class TestBudgetManager:
    """Tests for BudgetManager."""

    @pytest.fixture
    def budget(self):
        """Create a BudgetManager with small limits."""
        return BudgetManager(
            max_llm_calls=5,
            max_retries=2,
            max_iterations=10,
            max_duration_seconds=60
        )

    def test_initial_state(self, budget):
        """Test initial budget state."""
        within, reason = budget.check_budget()
        assert within is True
        assert reason == ""

    def test_llm_call_tracking(self, budget):
        """Test LLM call budget tracking."""
        for _ in range(5):
            budget.record_llm_call()

        within, reason = budget.check_budget()
        assert within is False
        assert "LLM call" in reason

    def test_retry_tracking(self, budget):
        """Test retry budget tracking."""
        budget.record_retry()
        budget.record_retry()

        within, reason = budget.check_budget()
        assert within is False
        assert "Retry" in reason

    def test_iteration_tracking(self, budget):
        """Test iteration budget tracking."""
        for _ in range(10):
            budget.record_iteration()

        within, reason = budget.check_budget()
        assert within is False
        assert "Iteration" in reason

    def test_get_remaining(self, budget):
        """Test getting remaining budget."""
        budget.record_llm_call()
        budget.record_retry()
        budget.record_iteration()
        budget.record_iteration()

        remaining = budget.get_remaining()
        assert remaining["llm_calls"] == 4
        assert remaining["retries"] == 1
        assert remaining["iterations"] == 8

    def test_time_budget(self):
        """Test time budget tracking."""
        budget = BudgetManager(max_duration_seconds=1)
        time.sleep(1.5)

        within, reason = budget.check_budget()
        assert within is False
        assert "Time" in reason


class TestHookContext:
    """Tests for HookContext."""

    def test_context_creation(self):
        """Test creating hook context."""
        ctx = HookContext(
            event=LifecycleEvent.TASK_START,
            phase=AgentPhase.INIT,
            data={"key": "value"}
        )
        assert ctx.event == LifecycleEvent.TASK_START
        assert ctx.phase == AgentPhase.INIT
        assert ctx.data["key"] == "value"


class TestLifecycleEvent:
    """Tests for LifecycleEvent enum."""

    def test_all_events_defined(self):
        """Test all required events are defined."""
        events = [
            LifecycleEvent.TASK_START,
            LifecycleEvent.TASK_END,
            LifecycleEvent.PHASE_ENTER,
            LifecycleEvent.PHASE_EXIT,
            LifecycleEvent.BEFORE_EDIT,
            LifecycleEvent.AFTER_EDIT,
            LifecycleEvent.BEFORE_TEST,
            LifecycleEvent.AFTER_TEST,
            LifecycleEvent.ON_ERROR,
            LifecycleEvent.ON_TIMEOUT,
            LifecycleEvent.ON_RETRY,
        ]
        assert len(events) >= 11
