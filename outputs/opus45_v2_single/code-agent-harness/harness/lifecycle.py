"""
Lifecycle Hooks (L) - Handles boundary events during agent execution.

Responsibilities:
- Pre-operation backups
- Failure rollback handling
- Timeout interruption with state saving
"""

from __future__ import annotations

import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Generator

from harness.state import StateStore


class HookEvent(Enum):
    """Events that trigger lifecycle hooks."""
    TASK_START = auto()
    TASK_END = auto()
    PHASE_ENTER = auto()
    PHASE_EXIT = auto()
    PRE_EDIT = auto()
    POST_EDIT = auto()
    PRE_TEST = auto()
    POST_TEST = auto()
    ERROR = auto()
    TIMEOUT = auto()
    RETRY = auto()
    ROLLBACK = auto()


@dataclass
class HookContext:
    """Context passed to hook handlers."""
    event: HookEvent
    state_store: StateStore
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = None


HookHandler = Callable[[HookContext], None]


class TimeoutError(Exception):
    """Raised when an operation times out."""
    pass


class LifecycleManager:
    """Manages lifecycle hooks for the agent."""

    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self._hooks: dict[HookEvent, list[HookHandler]] = {event: [] for event in HookEvent}
        self._timeout_handler_installed = False
        self._original_signal_handler: Any = None

        self._register_default_hooks()

    def register_hook(self, event: HookEvent, handler: HookHandler) -> None:
        """Register a hook handler for an event."""
        self._hooks[event].append(handler)

    def unregister_hook(self, event: HookEvent, handler: HookHandler) -> bool:
        """Unregister a hook handler."""
        try:
            self._hooks[event].remove(handler)
            return True
        except ValueError:
            return False

    def trigger(self, event: HookEvent, **data: Any) -> None:
        """Trigger all hooks for an event."""
        context = HookContext(
            event=event,
            state_store=self.state_store,
            data=data,
        )

        for handler in self._hooks[event]:
            try:
                handler(context)
            except Exception as e:
                if event != HookEvent.ERROR:
                    self.trigger(HookEvent.ERROR, error=e, original_event=event)

    def trigger_error(self, error: Exception, **data: Any) -> None:
        """Trigger error hooks with exception context."""
        context = HookContext(
            event=HookEvent.ERROR,
            state_store=self.state_store,
            error=error,
            data=data,
        )

        for handler in self._hooks[HookEvent.ERROR]:
            try:
                handler(context)
            except Exception:
                pass  # Don't recurse on error handler failures

    @contextmanager
    def timeout_guard(self, seconds: int) -> Generator[None, None, None]:
        """Context manager for timeout protection with state saving."""

        def timeout_handler(signum: int, frame: Any) -> None:
            self.trigger(HookEvent.TIMEOUT, timeout_seconds=seconds)
            raise TimeoutError(f"Operation timed out after {seconds} seconds")

        # Install signal handler
        try:
            self._original_signal_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            self._timeout_handler_installed = True
        except (ValueError, OSError):
            # Signal not available (e.g., Windows or non-main thread)
            self._timeout_handler_installed = False

        try:
            yield
        finally:
            if self._timeout_handler_installed:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, self._original_signal_handler)
                self._timeout_handler_installed = False

    @contextmanager
    def phase_guard(self, phase_name: str) -> Generator[None, None, None]:
        """Context manager for phase lifecycle."""
        self.trigger(HookEvent.PHASE_ENTER, phase=phase_name)
        try:
            yield
        except Exception as e:
            self.trigger_error(e, phase=phase_name)
            raise
        finally:
            self.trigger(HookEvent.PHASE_EXIT, phase=phase_name)

    @contextmanager
    def edit_guard(self, file_path: str) -> Generator[None, None, None]:
        """Context manager for file edit lifecycle with automatic backup."""
        self.trigger(HookEvent.PRE_EDIT, file=file_path)
        self.state_store.backup_file(file_path)

        try:
            yield
            self.trigger(HookEvent.POST_EDIT, file=file_path, success=True)
        except Exception as e:
            self.trigger(HookEvent.POST_EDIT, file=file_path, success=False, error=e)
            raise

    @contextmanager
    def test_guard(self, command: str) -> Generator[None, None, None]:
        """Context manager for test execution lifecycle."""
        self.trigger(HookEvent.PRE_TEST, command=command)

        try:
            yield
            self.trigger(HookEvent.POST_TEST, command=command, success=True)
        except Exception as e:
            self.trigger(HookEvent.POST_TEST, command=command, success=False, error=e)
            raise

    def _register_default_hooks(self) -> None:
        """Register default lifecycle hooks."""

        def on_task_start(ctx: HookContext) -> None:
            ctx.state_store.create_snapshot("task_start")

        def on_pre_edit(ctx: HookContext) -> None:
            file_path = ctx.data.get("file")
            if file_path:
                ctx.state_store.backup_file(file_path)

        def on_error(ctx: HookContext) -> None:
            ctx.state_store.create_snapshot(f"error_{time.time()}")
            if ctx.error:
                ctx.state_store.state.error_messages.append(str(ctx.error))

        def on_timeout(ctx: HookContext) -> None:
            ctx.state_store.create_snapshot("timeout_interrupt")
            ctx.state_store.save_state()

        def on_rollback(ctx: HookContext) -> None:
            rolled_back = ctx.state_store.rollback_all()
            ctx.data["rolled_back_files"] = rolled_back

        def on_retry(ctx: HookContext) -> None:
            ctx.state_store.increment_retry()
            ctx.state_store.create_snapshot(f"retry_{ctx.state_store.state.retry_count}")

        self.register_hook(HookEvent.TASK_START, on_task_start)
        self.register_hook(HookEvent.PRE_EDIT, on_pre_edit)
        self.register_hook(HookEvent.ERROR, on_error)
        self.register_hook(HookEvent.TIMEOUT, on_timeout)
        self.register_hook(HookEvent.ROLLBACK, on_rollback)
        self.register_hook(HookEvent.RETRY, on_retry)


class OperationGuard:
    """Guard for wrapping operations with lifecycle hooks."""

    def __init__(self, lifecycle: LifecycleManager):
        self.lifecycle = lifecycle

    def safe_edit(self, file_path: str, edit_func: Callable[[], Any]) -> Any:
        """Safely execute a file edit with backup and rollback on failure."""
        with self.lifecycle.edit_guard(file_path):
            try:
                return edit_func()
            except Exception as e:
                self.lifecycle.state_store.rollback_file(file_path)
                raise

    def safe_test(self, command: str, test_func: Callable[[], Any]) -> Any:
        """Safely execute a test command with lifecycle hooks."""
        with self.lifecycle.test_guard(command):
            return test_func()

    def with_timeout(self, seconds: int, operation: Callable[[], Any]) -> Any:
        """Execute an operation with timeout protection."""
        with self.lifecycle.timeout_guard(seconds):
            return operation()

    def with_retry(
        self,
        operation: Callable[[], Any],
        max_retries: int = 3,
        on_retry: Callable[[int, Exception], None] | None = None,
    ) -> Any:
        """Execute an operation with retry logic."""
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                return operation()
            except Exception as e:
                last_error = e
                self.lifecycle.trigger(HookEvent.RETRY, attempt=attempt, error=e)

                if on_retry:
                    on_retry(attempt, e)

                if attempt == max_retries - 1:
                    raise

        raise last_error or Exception("Operation failed")
