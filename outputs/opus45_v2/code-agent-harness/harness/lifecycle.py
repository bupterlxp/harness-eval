"""Lifecycle Hooks (L) - Boundary event handling for the execution process."""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from harness.execution import ExecutionContext
    from harness.state import StateStore


@dataclass
class HookResult:
    """Result of a hook execution."""
    hook_name: str
    success: bool
    message: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)


HookCallback = Callable[["ExecutionContext"], HookResult | None]


class LifecycleManager:
    """Manages lifecycle hooks for execution boundary events."""

    def __init__(self, state_store: StateStore, timeout: int = 3600) -> None:
        self.state_store = state_store
        self.timeout = timeout

        self._hooks: dict[str, list[HookCallback]] = {
            "start": [],
            "backup": [],
            "success": [],
            "failure": [],
            "error": [],
            "rollback": [],
            "timeout": [],
            "interrupt": [],
        }
        self._hook_results: list[HookResult] = []

        self._start_time: float | None = None
        self._timeout_timer: threading.Timer | None = None
        self._interrupted = False
        self._original_sigint: Any = None
        self._original_sigterm: Any = None

    def register_hook(self, event: str, callback: HookCallback) -> None:
        """Register a callback for a lifecycle event."""
        if event in self._hooks:
            self._hooks[event].append(callback)

    def unregister_hook(self, event: str, callback: HookCallback) -> None:
        """Unregister a callback for a lifecycle event."""
        if event in self._hooks and callback in self._hooks[event]:
            self._hooks[event].remove(callback)

    def on_start(self, ctx: ExecutionContext) -> None:
        """Called when execution starts."""
        self._start_time = time.time()
        self._interrupted = False

        self._setup_signal_handlers(ctx)
        self._setup_timeout(ctx)

        self._run_hooks("start", ctx)

    def on_backup(self, ctx: ExecutionContext) -> None:
        """Called before modifications to create backups."""
        repo_path = Path(ctx.repo_path)

        if repo_path.exists():
            for fpath in repo_path.rglob("*"):
                if fpath.is_file() and not self._should_ignore(fpath):
                    self.state_store.backup_file(str(fpath))

        self._run_hooks("backup", ctx)

    def on_success(self, ctx: ExecutionContext) -> None:
        """Called when execution completes successfully."""
        self._cleanup_timeout()
        self._restore_signal_handlers()

        result = HookResult(
            hook_name="success",
            success=True,
            message="Execution completed successfully",
            data={
                "duration": time.time() - (self._start_time or 0),
                "iterations": ctx.iteration,
                "llm_calls": ctx.llm_calls,
                "edits": len(ctx.edits),
            },
        )
        self._hook_results.append(result)

        self._run_hooks("success", ctx)

    def on_failure(self, ctx: ExecutionContext) -> None:
        """Called when execution fails."""
        self._cleanup_timeout()
        self._restore_signal_handlers()

        result = HookResult(
            hook_name="failure",
            success=False,
            message=f"Execution failed: {ctx.last_error}",
            data={
                "duration": time.time() - (self._start_time or 0),
                "iterations": ctx.iteration,
                "llm_calls": ctx.llm_calls,
                "last_error": ctx.last_error,
            },
        )
        self._hook_results.append(result)

        self._run_hooks("failure", ctx)

    def on_error(self, ctx: ExecutionContext, error: Exception) -> None:
        """Called when an unexpected error occurs."""
        result = HookResult(
            hook_name="error",
            success=False,
            message=f"Error occurred: {error}",
            data={"error_type": type(error).__name__, "error_message": str(error)},
        )
        self._hook_results.append(result)

        self._run_hooks("error", ctx)

    def on_rollback(self, ctx: ExecutionContext) -> None:
        """Called when rollback is triggered."""
        self.state_store.rollback(ctx)

        result = HookResult(
            hook_name="rollback",
            success=True,
            message="Rollback completed",
            data={"iteration": ctx.iteration, "retry_count": ctx.retry_count},
        )
        self._hook_results.append(result)

        self._run_hooks("rollback", ctx)

    def on_timeout(self, ctx: ExecutionContext) -> None:
        """Called when execution times out."""
        self.state_store.snapshot(ctx)

        result = HookResult(
            hook_name="timeout",
            success=False,
            message=f"Execution timed out after {self.timeout}s",
            data={
                "timeout": self.timeout,
                "iterations": ctx.iteration,
                "current_state": ctx.current_state.name,
            },
        )
        self._hook_results.append(result)

        self._run_hooks("timeout", ctx)

    def on_interrupt(self, ctx: ExecutionContext) -> None:
        """Called when execution is interrupted (SIGINT/SIGTERM)."""
        self._interrupted = True

        self.state_store.snapshot(ctx)

        result = HookResult(
            hook_name="interrupt",
            success=False,
            message="Execution interrupted by signal",
            data={
                "iterations": ctx.iteration,
                "current_state": ctx.current_state.name,
            },
        )
        self._hook_results.append(result)

        self._run_hooks("interrupt", ctx)

    def is_interrupted(self) -> bool:
        """Check if execution has been interrupted."""
        return self._interrupted

    def get_elapsed_time(self) -> float:
        """Get elapsed time since start."""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def get_remaining_time(self) -> float:
        """Get remaining time before timeout."""
        elapsed = self.get_elapsed_time()
        return max(0.0, self.timeout - elapsed)

    def get_hook_results(self) -> list[HookResult]:
        """Get all hook execution results."""
        return self._hook_results.copy()

    def _run_hooks(self, event: str, ctx: ExecutionContext) -> None:
        """Run all hooks for an event."""
        for callback in self._hooks.get(event, []):
            try:
                result = callback(ctx)
                if result:
                    self._hook_results.append(result)
            except Exception as e:
                self._hook_results.append(
                    HookResult(
                        hook_name=f"{event}_callback",
                        success=False,
                        message=f"Hook failed: {e}",
                    )
                )

    def _setup_signal_handlers(self, ctx: ExecutionContext) -> None:
        """Setup signal handlers for graceful interruption."""

        def signal_handler(signum: int, frame: Any) -> None:
            self.on_interrupt(ctx)

        try:
            self._original_sigint = signal.signal(signal.SIGINT, signal_handler)
            self._original_sigterm = signal.signal(signal.SIGTERM, signal_handler)
        except (ValueError, OSError):
            pass

    def _restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        try:
            if self._original_sigint is not None:
                signal.signal(signal.SIGINT, self._original_sigint)
            if self._original_sigterm is not None:
                signal.signal(signal.SIGTERM, self._original_sigterm)
        except (ValueError, OSError):
            pass

    def _setup_timeout(self, ctx: ExecutionContext) -> None:
        """Setup timeout timer."""
        if self.timeout <= 0:
            return

        def timeout_handler() -> None:
            self.on_timeout(ctx)
            self._interrupted = True

        self._timeout_timer = threading.Timer(self.timeout, timeout_handler)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    def _cleanup_timeout(self) -> None:
        """Cleanup timeout timer."""
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path should be ignored for backup."""
        ignore_patterns = {
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".tox",
            ".eggs",
            "dist",
            "build",
            ".harness_state",
        }

        for part in path.parts:
            if part in ignore_patterns:
                return True
            if part.endswith(".pyc") or part.endswith(".pyo"):
                return True

        return False


def create_default_hooks() -> list[tuple[str, HookCallback]]:
    """Create default lifecycle hooks."""

    def log_start(ctx: ExecutionContext) -> HookResult:
        return HookResult(
            hook_name="log_start",
            success=True,
            message=f"Starting execution for task: {ctx.task_type}",
            data={"description": ctx.description[:100]},
        )

    def log_backup(ctx: ExecutionContext) -> HookResult:
        return HookResult(
            hook_name="log_backup",
            success=True,
            message="Backup created for repository files",
        )

    return [
        ("start", log_start),
        ("backup", log_backup),
    ]
