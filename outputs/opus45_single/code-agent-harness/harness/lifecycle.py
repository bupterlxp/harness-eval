"""
Lifecycle Hooks (L) - Boundary event handling.

Provides:
- Pre-operation backup
- Failure rollback
- Timeout interrupt with state save
- Custom hook registration
"""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from contextlib import contextmanager

from harness.state import StateStore, AgentPhase


class LifecycleEvent(Enum):
    """Events that trigger lifecycle hooks."""
    TASK_START = "task_start"
    TASK_END = "task_end"
    PHASE_ENTER = "phase_enter"
    PHASE_EXIT = "phase_exit"
    BEFORE_EDIT = "before_edit"
    AFTER_EDIT = "after_edit"
    BEFORE_TEST = "before_test"
    AFTER_TEST = "after_test"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_RETRY = "on_retry"
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""
    event: LifecycleEvent
    phase: AgentPhase
    data: dict[str, Any]
    state_store: StateStore | None = None


HookCallback = Callable[[HookContext], None]


class TimeoutError(Exception):
    """Raised when execution times out."""
    pass


class LifecycleManager:
    """
    Manages lifecycle hooks for boundary events.

    Built-in behaviors:
    - Automatic backup before file edits
    - Rollback on failure
    - State save on timeout
    """

    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self._hooks: dict[LifecycleEvent, list[HookCallback]] = {
            event: [] for event in LifecycleEvent
        }
        self._timeout_seconds: int | None = None
        self._original_handler: Any = None

        self._register_default_hooks()

    def _register_default_hooks(self) -> None:
        """Register built-in lifecycle hooks."""

        def backup_before_edit(ctx: HookContext) -> None:
            file_path = ctx.data.get("file_path")
            if file_path:
                self.state_store.backup_file(file_path)

        def rollback_on_error(ctx: HookContext) -> None:
            error = ctx.data.get("error")
            should_rollback = ctx.data.get("rollback", True)
            if should_rollback and error:
                modified_files = self.state_store.get_modified_files()
                if modified_files:
                    self.state_store.rollback_all_files()

        def save_on_timeout(ctx: HookContext) -> None:
            self.state_store.create_snapshot("timeout_snapshot")
            self.state_store.set_metadata("timeout_reason", str(ctx.data.get("reason", "unknown")))

        def snapshot_before_test(ctx: HookContext) -> None:
            self.state_store.create_snapshot("pre_test")

        self.register_hook(LifecycleEvent.BEFORE_EDIT, backup_before_edit)
        self.register_hook(LifecycleEvent.ON_ERROR, rollback_on_error)
        self.register_hook(LifecycleEvent.ON_TIMEOUT, save_on_timeout)
        self.register_hook(LifecycleEvent.BEFORE_TEST, snapshot_before_test)

    def register_hook(self, event: LifecycleEvent, callback: HookCallback) -> None:
        """Register a callback for a lifecycle event."""
        self._hooks[event].append(callback)

    def unregister_hook(self, event: LifecycleEvent, callback: HookCallback) -> bool:
        """Unregister a callback. Returns True if found and removed."""
        try:
            self._hooks[event].remove(callback)
            return True
        except ValueError:
            return False

    def trigger(self, event: LifecycleEvent, data: dict[str, Any] | None = None) -> None:
        """Trigger all hooks for an event."""
        ctx = HookContext(
            event=event,
            phase=self.state_store.current_phase,
            data=data or {},
            state_store=self.state_store
        )

        for hook in self._hooks[event]:
            try:
                hook(ctx)
            except Exception:
                pass

    def _timeout_handler(self, signum: int, frame: Any) -> None:
        """Signal handler for timeout."""
        self.trigger(LifecycleEvent.ON_TIMEOUT, {"reason": "execution_timeout"})
        raise TimeoutError("Execution timed out")

    @contextmanager
    def timeout(self, seconds: int):
        """Context manager for timeout handling."""
        self._timeout_seconds = seconds

        if hasattr(signal, 'SIGALRM'):
            self._original_handler = signal.signal(signal.SIGALRM, self._timeout_handler)
            signal.alarm(seconds)

        try:
            yield
        finally:
            if hasattr(signal, 'SIGALRM'):
                signal.alarm(0)
                if self._original_handler is not None:
                    signal.signal(signal.SIGALRM, self._original_handler)
            self._timeout_seconds = None

    @contextmanager
    def phase_scope(self, phase: AgentPhase):
        """Context manager for phase entry/exit hooks."""
        old_phase = self.state_store.current_phase
        self.trigger(LifecycleEvent.PHASE_ENTER, {"phase": phase.value, "from_phase": old_phase.value})
        self.state_store.set_phase(phase)

        try:
            yield
        finally:
            self.trigger(LifecycleEvent.PHASE_EXIT, {"phase": phase.value})

    @contextmanager
    def edit_scope(self, file_path: str):
        """Context manager for file edit lifecycle."""
        self.trigger(LifecycleEvent.BEFORE_EDIT, {"file_path": file_path})
        try:
            yield
            self.trigger(LifecycleEvent.AFTER_EDIT, {"file_path": file_path, "success": True})
        except Exception as e:
            self.trigger(LifecycleEvent.AFTER_EDIT, {"file_path": file_path, "success": False, "error": str(e)})
            raise

    @contextmanager
    def test_scope(self, test_command: str):
        """Context manager for test execution lifecycle."""
        self.trigger(LifecycleEvent.BEFORE_TEST, {"command": test_command})
        try:
            yield
            self.trigger(LifecycleEvent.AFTER_TEST, {"command": test_command, "success": True})
        except Exception as e:
            self.trigger(LifecycleEvent.AFTER_TEST, {"command": test_command, "success": False, "error": str(e)})
            raise

    @contextmanager
    def error_boundary(self, rollback: bool = True):
        """Context manager that catches errors and triggers hooks."""
        try:
            yield
        except TimeoutError:
            raise
        except Exception as e:
            self.trigger(LifecycleEvent.ON_ERROR, {"error": str(e), "rollback": rollback})
            raise

    def handle_retry(self, reason: str, attempt: int) -> None:
        """Called when retrying an operation."""
        self.trigger(LifecycleEvent.ON_RETRY, {"reason": reason, "attempt": attempt})

    def task_start(self, task_spec: dict[str, Any]) -> None:
        """Called at task start."""
        self.state_store.set_metadata("task_spec", task_spec)
        self.state_store.create_snapshot("task_start")
        self.trigger(LifecycleEvent.TASK_START, {"task_spec": task_spec})

    def task_end(self, status: str, result: dict[str, Any]) -> None:
        """Called at task end."""
        self.state_store.set_metadata("final_status", status)
        self.trigger(LifecycleEvent.TASK_END, {"status": status, "result": result})


class BudgetManager:
    """Manages execution budgets to prevent infinite loops."""

    def __init__(
        self,
        max_llm_calls: int = 50,
        max_retries: int = 5,
        max_iterations: int = 100,
        max_duration_seconds: int = 600
    ):
        self.max_llm_calls = max_llm_calls
        self.max_retries = max_retries
        self.max_iterations = max_iterations
        self.max_duration_seconds = max_duration_seconds

        self.llm_calls = 0
        self.retries = 0
        self.iterations = 0
        self.start_time = time.time()

    def record_llm_call(self) -> None:
        """Record an LLM call."""
        self.llm_calls += 1

    def record_retry(self) -> None:
        """Record a retry."""
        self.retries += 1

    def record_iteration(self) -> None:
        """Record an iteration."""
        self.iterations += 1

    def check_budget(self) -> tuple[bool, str]:
        """
        Check if within budget.

        Returns:
            (is_within_budget, reason_if_exceeded)
        """
        if self.llm_calls >= self.max_llm_calls:
            return False, f"LLM call limit exceeded ({self.llm_calls}/{self.max_llm_calls})"

        if self.retries >= self.max_retries:
            return False, f"Retry limit exceeded ({self.retries}/{self.max_retries})"

        if self.iterations >= self.max_iterations:
            return False, f"Iteration limit exceeded ({self.iterations}/{self.max_iterations})"

        elapsed = time.time() - self.start_time
        if elapsed >= self.max_duration_seconds:
            return False, f"Time limit exceeded ({elapsed:.0f}s/{self.max_duration_seconds}s)"

        return True, ""

    def get_remaining(self) -> dict[str, int]:
        """Get remaining budget."""
        elapsed = int(time.time() - self.start_time)
        return {
            "llm_calls": self.max_llm_calls - self.llm_calls,
            "retries": self.max_retries - self.retries,
            "iterations": self.max_iterations - self.iterations,
            "seconds": max(0, self.max_duration_seconds - elapsed)
        }
