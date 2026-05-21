"""Tests for the Lifecycle module."""

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.lifecycle import (
    HookContext,
    HookEvent,
    LifecycleManager,
    OperationGuard,
    TimeoutError,
)
from harness.state import StateStore


class TestHookEvent:
    """Tests for HookEvent enum."""

    def test_all_events_exist(self):
        events = [
            HookEvent.TASK_START,
            HookEvent.TASK_END,
            HookEvent.PHASE_ENTER,
            HookEvent.PHASE_EXIT,
            HookEvent.PRE_EDIT,
            HookEvent.POST_EDIT,
            HookEvent.PRE_TEST,
            HookEvent.POST_TEST,
            HookEvent.ERROR,
            HookEvent.TIMEOUT,
            HookEvent.RETRY,
            HookEvent.ROLLBACK,
        ]
        assert len(events) == 12


class TestHookContext:
    """Tests for HookContext dataclass."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_context_creation(self, temp_dir):
        state_store = StateStore(temp_dir)
        ctx = HookContext(
            event=HookEvent.TASK_START,
            state_store=state_store,
            data={"key": "value"},
        )

        assert ctx.event == HookEvent.TASK_START
        assert ctx.data["key"] == "value"
        assert ctx.timestamp > 0


class TestLifecycleManager:
    """Tests for LifecycleManager."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def state_store(self, temp_dir):
        return StateStore(temp_dir)

    @pytest.fixture
    def lifecycle(self, state_store):
        return LifecycleManager(state_store)

    def test_register_hook(self, lifecycle):
        called = []

        def handler(ctx):
            called.append(ctx.event)

        lifecycle.register_hook(HookEvent.TASK_START, handler)
        lifecycle.trigger(HookEvent.TASK_START)

        assert HookEvent.TASK_START in called

    def test_unregister_hook(self, lifecycle):
        called = []

        def handler(ctx):
            called.append(True)

        lifecycle.register_hook(HookEvent.TASK_START, handler)
        success = lifecycle.unregister_hook(HookEvent.TASK_START, handler)

        assert success
        lifecycle.trigger(HookEvent.TASK_START)
        # Handler should still be called from default hooks, but our custom one shouldn't add
        assert len([x for x in called if x is True]) == 0

    def test_trigger_with_data(self, lifecycle):
        received_data = {}

        def handler(ctx):
            received_data.update(ctx.data)

        lifecycle.register_hook(HookEvent.PRE_EDIT, handler)
        lifecycle.trigger(HookEvent.PRE_EDIT, file="/test/file.py", reason="test")

        assert received_data["file"] == "/test/file.py"
        assert received_data["reason"] == "test"

    def test_trigger_error(self, lifecycle):
        errors = []

        def handler(ctx):
            if ctx.error:
                errors.append(ctx.error)

        lifecycle.register_hook(HookEvent.ERROR, handler)
        lifecycle.trigger_error(ValueError("test error"), context="testing")

        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)

    def test_phase_guard_success(self, lifecycle):
        entered = []
        exited = []

        def on_enter(ctx):
            entered.append(ctx.data.get("phase"))

        def on_exit(ctx):
            exited.append(ctx.data.get("phase"))

        lifecycle.register_hook(HookEvent.PHASE_ENTER, on_enter)
        lifecycle.register_hook(HookEvent.PHASE_EXIT, on_exit)

        with lifecycle.phase_guard("EDIT"):
            pass

        assert "EDIT" in entered
        assert "EDIT" in exited

    def test_phase_guard_exception(self, lifecycle):
        errors = []

        def on_error(ctx):
            errors.append(ctx.error)

        lifecycle.register_hook(HookEvent.ERROR, on_error)

        with pytest.raises(ValueError):
            with lifecycle.phase_guard("TEST"):
                raise ValueError("phase failed")

        assert any(isinstance(e, ValueError) for e in errors)

    def test_edit_guard_backup(self, lifecycle, state_store, temp_dir):
        test_file = Path(temp_dir) / "edit_test.py"
        test_file.write_text("original")

        with lifecycle.edit_guard(str(test_file)):
            pass

        assert str(test_file) in state_store.file_backups

    def test_default_hooks_registered(self, lifecycle):
        assert len(lifecycle._hooks[HookEvent.TASK_START]) > 0
        assert len(lifecycle._hooks[HookEvent.ERROR]) > 0
        assert len(lifecycle._hooks[HookEvent.TIMEOUT]) > 0

    def test_timeout_guard_no_timeout(self, lifecycle):
        result = None
        with lifecycle.timeout_guard(5):
            result = 42

        assert result == 42

    def test_retry_increments_counter(self, lifecycle, state_store):
        initial = state_store.state.retry_count
        lifecycle.trigger(HookEvent.RETRY)
        assert state_store.state.retry_count == initial + 1


class TestOperationGuard:
    """Tests for OperationGuard."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def state_store(self, temp_dir):
        return StateStore(temp_dir)

    @pytest.fixture
    def guard(self, state_store):
        lifecycle = LifecycleManager(state_store)
        return OperationGuard(lifecycle)

    def test_safe_edit_success(self, guard, temp_dir):
        test_file = Path(temp_dir) / "safe_edit.py"
        test_file.write_text("original")

        def edit():
            test_file.write_text("modified")
            return True

        result = guard.safe_edit(str(test_file), edit)

        assert result is True
        assert test_file.read_text() == "modified"

    def test_safe_edit_rollback_on_failure(self, guard, state_store, temp_dir):
        test_file = Path(temp_dir) / "rollback_edit.py"
        test_file.write_text("original")

        def failing_edit():
            test_file.write_text("modified")
            raise ValueError("edit failed")

        with pytest.raises(ValueError):
            guard.safe_edit(str(test_file), failing_edit)

        assert test_file.read_text() == "original"

    def test_safe_test(self, guard):
        def test_func():
            return {"passed": 5, "failed": 0}

        result = guard.safe_test("pytest tests/", test_func)

        assert result["passed"] == 5

    def test_with_retry_success(self, guard):
        attempts = [0]

        def operation():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ValueError("not yet")
            return "success"

        result = guard.with_retry(operation, max_retries=5)

        assert result == "success"
        assert attempts[0] == 3

    def test_with_retry_exhausted(self, guard):
        def always_fails():
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            guard.with_retry(always_fails, max_retries=3)
