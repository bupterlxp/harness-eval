"""Lifecycle Hooks — hooks at key boundaries.

Provides pre/post operation hooks, failure handlers, timeout handling,
and integration with the trajectory recorder.
"""

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from harness.evaluation import TrajectoryRecorder


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""
    phase: str
    iteration: int
    tool_name: str = ""
    input_data: Any = None
    output_data: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    token_usage: int = 0


HookFunction = Callable[[HookContext], None]


class LifecycleManager:
    """Manages lifecycle hooks at key boundaries."""

    def __init__(self, recorder: Optional[TrajectoryRecorder] = None,
                 timeout_seconds: float = 300.0):
        self.recorder = recorder
        self.timeout_seconds = timeout_seconds
        self._start_time = time.time()
        self._phase_start_time = time.time()

        # Hook registries
        self._pre_phase_hooks: list[HookFunction] = []
        self._post_phase_hooks: list[HookFunction] = []
        self._pre_tool_hooks: list[HookFunction] = []
        self._post_tool_hooks: list[HookFunction] = []
        self._failure_hooks: list[HookFunction] = []
        self._timeout_hooks: list[HookFunction] = []
        self._checkpoint_hooks: list[HookFunction] = []

        # Statistics
        self.total_tool_calls = 0
        self.total_token_usage = 0
        self.total_errors = 0
        self.phase_durations: dict[str, float] = {}

    # ===== Hook Registration =====

    def on_pre_phase(self, hook: HookFunction) -> None:
        self._pre_phase_hooks.append(hook)

    def on_post_phase(self, hook: HookFunction) -> None:
        self._post_phase_hooks.append(hook)

    def on_pre_tool(self, hook: HookFunction) -> None:
        self._pre_tool_hooks.append(hook)

    def on_post_tool(self, hook: HookFunction) -> None:
        self._post_tool_hooks.append(hook)

    def on_failure(self, hook: HookFunction) -> None:
        self._failure_hooks.append(hook)

    def on_timeout(self, hook: HookFunction) -> None:
        self._timeout_hooks.append(hook)

    def on_checkpoint(self, hook: HookFunction) -> None:
        self._checkpoint_hooks.append(hook)

    # ===== Hook Execution =====

    def enter_phase(self, phase: str, iteration: int) -> None:
        """Called when entering a new FSM phase."""
        self._phase_start_time = time.time()
        ctx = HookContext(phase=phase, iteration=iteration)

        for hook in self._pre_phase_hooks:
            try:
                hook(ctx)
            except Exception as e:
                self._handle_hook_error("pre_phase", e)

        if self.recorder:
            self.recorder.record_phase_transition(phase, iteration)

    def exit_phase(self, phase: str, iteration: int) -> None:
        """Called when exiting an FSM phase."""
        duration = (time.time() - self._phase_start_time) * 1000
        self.phase_durations[phase] = self.phase_durations.get(phase, 0) + duration

        ctx = HookContext(phase=phase, iteration=iteration, duration_ms=duration)

        for hook in self._post_phase_hooks:
            try:
                hook(ctx)
            except Exception as e:
                self._handle_hook_error("post_phase", e)

    def pre_tool_call(self, tool_name: str, input_data: Any,
                      phase: str, iteration: int) -> None:
        """Called before a tool is invoked."""
        ctx = HookContext(
            phase=phase, iteration=iteration,
            tool_name=tool_name, input_data=input_data,
        )

        for hook in self._pre_tool_hooks:
            try:
                hook(ctx)
            except Exception as e:
                self._handle_hook_error("pre_tool", e)

    def post_tool_call(self, tool_name: str, input_data: Any, output_data: Any,
                       phase: str, iteration: int, duration_ms: float,
                       token_usage: int) -> None:
        """Called after a tool returns."""
        self.total_tool_calls += 1
        self.total_token_usage += token_usage

        ctx = HookContext(
            phase=phase, iteration=iteration,
            tool_name=tool_name, input_data=input_data,
            output_data=output_data, duration_ms=duration_ms,
            token_usage=token_usage,
        )

        for hook in self._post_tool_hooks:
            try:
                hook(ctx)
            except Exception as e:
                self._handle_hook_error("post_tool", e)

        if self.recorder:
            self.recorder.record_action(
                action_type="tool_call",
                tool_name=tool_name,
                input_data=self._safe_serialize_input(input_data),
                output_data=self._safe_serialize_output(output_data),
                duration_ms=duration_ms,
                token_usage=token_usage,
                phase=phase,
                iteration=iteration,
            )

    def handle_failure(self, error: Exception, phase: str, iteration: int,
                       tool_name: str = "") -> None:
        """Called when an operation fails."""
        self.total_errors += 1
        error_str = f"{type(error).__name__}: {str(error)}"

        ctx = HookContext(
            phase=phase, iteration=iteration,
            tool_name=tool_name, error=error_str,
        )

        for hook in self._failure_hooks:
            try:
                hook(ctx)
            except Exception as e:
                self._handle_hook_error("failure", e)

        if self.recorder:
            self.recorder.record_error(
                error_str,
                phase=phase,
                iteration=iteration,
                tool_name=tool_name,
            )

    def check_timeout(self, phase: str, iteration: int) -> bool:
        """Check if we've exceeded the timeout. Returns True if timed out."""
        elapsed = time.time() - self._start_time
        if elapsed > self.timeout_seconds:
            ctx = HookContext(
                phase=phase, iteration=iteration,
                duration_ms=elapsed * 1000,
            )
            for hook in self._timeout_hooks:
                try:
                    hook(ctx)
                except Exception as e:
                    self._handle_hook_error("timeout", e)

            if self.recorder:
                self.recorder.record_error(
                    f"Timeout after {elapsed:.1f}s",
                    phase=phase,
                    iteration=iteration,
                )
            return True
        return False

    def notify_checkpoint(self, phase: str, iteration: int, path: str) -> None:
        """Called when a checkpoint is saved."""
        ctx = HookContext(
            phase=phase, iteration=iteration,
            output_data={"checkpoint_path": path},
        )
        for hook in self._checkpoint_hooks:
            try:
                hook(ctx)
            except Exception as e:
                self._handle_hook_error("checkpoint", e)

    def get_stats(self) -> dict[str, Any]:
        """Get lifecycle statistics."""
        elapsed = time.time() - self._start_time
        return {
            "elapsed_seconds": elapsed,
            "total_tool_calls": self.total_tool_calls,
            "total_token_usage": self.total_token_usage,
            "total_errors": self.total_errors,
            "phase_durations_ms": self.phase_durations,
        }

    # ===== Internal =====

    def _handle_hook_error(self, hook_type: str, error: Exception) -> None:
        """Handle errors in hooks themselves (don't let them crash the system)."""
        tb = traceback.format_exc()
        print(f"WARNING: {hook_type} hook error: {error}\n{tb}")

    def _safe_serialize_input(self, data: Any) -> Any:
        """Safely serialize input data for recording (truncate large strings)."""
        if isinstance(data, str):
            return data[:500] if len(data) > 500 else data
        if isinstance(data, dict):
            return {k: self._safe_serialize_input(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._safe_serialize_input(v) for v in data[:10]]
        return data

    def _safe_serialize_output(self, data: Any) -> Any:
        """Safely serialize output data for recording."""
        if isinstance(data, str):
            return data[:1000] if len(data) > 1000 else data
        if isinstance(data, dict):
            return {k: self._safe_serialize_output(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._safe_serialize_output(v) for v in data[:10]]
        return data
