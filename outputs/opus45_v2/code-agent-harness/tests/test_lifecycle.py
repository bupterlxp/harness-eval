"""Tests for the lifecycle module."""

import tempfile
from unittest.mock import MagicMock

import pytest

from harness.execution import ExecutionContext, ExecutionState
from harness.lifecycle import HookResult, LifecycleManager, create_default_hooks
from harness.state import StateStore


class TestHookResult:
    """Tests for HookResult class."""

    def test_hook_result_creation(self) -> None:
        """Test creating a hook result."""
        result = HookResult(
            hook_name="test_hook",
            success=True,
            message="Test passed",
            data={"key": "value"},
        )

        assert result.hook_name == "test_hook"
        assert result.success is True
        assert result.message == "Test passed"
        assert result.data["key"] == "value"
        assert result.timestamp > 0


class TestLifecycleManager:
    """Tests for LifecycleManager."""

    def create_test_context(self, tmpdir: str) -> ExecutionContext:
        """Create a test execution context."""
        return ExecutionContext(
            task_type="test",
            description="test task",
            repo_path=tmpdir,
            test_command=None,
            constraints=[],
        )

    def test_manager_creation(self) -> None:
        """Test creating a lifecycle manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store, timeout=60)

            assert manager.timeout == 60

    def test_register_hook(self) -> None:
        """Test registering a custom hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            callback = MagicMock(return_value=None)
            manager.register_hook("start", callback)

            ctx = self.create_test_context(tmpdir)
            manager.on_start(ctx)

            callback.assert_called_once_with(ctx)

    def test_unregister_hook(self) -> None:
        """Test unregistering a hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            callback = MagicMock(return_value=None)
            manager.register_hook("start", callback)
            manager.unregister_hook("start", callback)

            ctx = self.create_test_context(tmpdir)
            manager.on_start(ctx)

            callback.assert_not_called()

    def test_on_start_sets_time(self) -> None:
        """Test that on_start sets start time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            ctx = self.create_test_context(tmpdir)
            manager.on_start(ctx)

            assert manager.get_elapsed_time() >= 0

    def test_on_success_records_result(self) -> None:
        """Test that on_success records result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            ctx = self.create_test_context(tmpdir)
            manager.on_start(ctx)
            manager.on_success(ctx)

            results = manager.get_hook_results()
            assert any(r.hook_name == "success" for r in results)

    def test_on_failure_records_result(self) -> None:
        """Test that on_failure records result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            ctx = self.create_test_context(tmpdir)
            ctx.last_error = "Test error"
            manager.on_start(ctx)
            manager.on_failure(ctx)

            results = manager.get_hook_results()
            assert any(r.hook_name == "failure" for r in results)

    def test_on_error_records_exception(self) -> None:
        """Test that on_error records the exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            ctx = self.create_test_context(tmpdir)
            error = ValueError("Test error")
            manager.on_error(ctx, error)

            results = manager.get_hook_results()
            assert any(r.hook_name == "error" for r in results)

    def test_on_rollback_calls_store(self) -> None:
        """Test that on_rollback calls state store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            ctx = self.create_test_context(tmpdir)
            store.snapshot(ctx)
            manager.on_rollback(ctx)

            results = manager.get_hook_results()
            assert any(r.hook_name == "rollback" for r in results)

    def test_get_remaining_time(self) -> None:
        """Test getting remaining time before timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store, timeout=3600)

            ctx = self.create_test_context(tmpdir)
            manager.on_start(ctx)

            remaining = manager.get_remaining_time()
            assert remaining > 0
            assert remaining <= 3600

    def test_is_interrupted_default_false(self) -> None:
        """Test that is_interrupted is false by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            manager = LifecycleManager(store)

            assert manager.is_interrupted() is False


class TestDefaultHooks:
    """Tests for default hooks."""

    def test_create_default_hooks(self) -> None:
        """Test creating default hooks."""
        hooks = create_default_hooks()

        assert len(hooks) >= 2
        assert any(event == "start" for event, _ in hooks)
        assert any(event == "backup" for event, _ in hooks)

    def test_default_start_hook(self) -> None:
        """Test default start hook execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            hooks = create_default_hooks()
            start_hook = next(cb for event, cb in hooks if event == "start")

            ctx = ExecutionContext(
                task_type="bug_fix",
                description="Fix the login bug",
                repo_path=tmpdir,
                test_command=None,
                constraints=[],
            )

            result = start_hook(ctx)

            assert result is not None
            assert result.success is True
            assert "bug_fix" in result.message
