"""Lifecycle Hooks - hooks at key boundaries.

Provides pre/post operation hooks, failure handlers, and timeout management.
Hooks can be registered for any lifecycle event and are executed in order.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from harness.state import AgentState, AgentPhase


class HookEvent(str, Enum):
    """Events that can trigger lifecycle hooks."""
    PRE_TRANSITION = "pre_transition"
    POST_TRANSITION = "post_transition"
    PRE_SEARCH = "pre_search"
    POST_SEARCH = "post_search"
    PRE_FETCH = "pre_fetch"
    POST_FETCH = "post_fetch"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    PRE_GENERATE = "pre_generate"
    POST_GENERATE = "post_generate"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_CHECKPOINT = "on_checkpoint"
    ON_BUDGET_WARNING = "on_budget_warning"
    ON_ROUND_START = "on_round_start"
    ON_ROUND_END = "on_round_end"
    ON_COMPLETE = "on_complete"


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""
    event: HookEvent
    state: AgentState
    phase_from: AgentPhase | None = None
    phase_to: AgentPhase | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: Exception | None = None
    timestamp: float = field(default_factory=time.time)


HookFunction = Callable[[HookContext], Awaitable[None]]


@dataclass
class HookRegistration:
    """A registered hook with its metadata."""
    event: HookEvent
    func: HookFunction
    name: str
    priority: int = 0  # Lower = earlier execution


class LifecycleManager:
    """Manages lifecycle hooks and timeout enforcement."""

    def __init__(self, state: AgentState, timeout_seconds: float = 600.0):
        self._state = state
        self._hooks: dict[HookEvent, list[HookRegistration]] = {e: [] for e in HookEvent}
        self._timeout_seconds = timeout_seconds
        self._start_time: float = time.time()
        self._step_times: list[float] = []

    def register_hook(
        self,
        event: HookEvent,
        func: HookFunction,
        name: str = "",
        priority: int = 0,
    ) -> None:
        """Register a hook for a lifecycle event."""
        reg = HookRegistration(event=event, func=func, name=name or func.__name__, priority=priority)
        self._hooks[event].append(reg)
        # Keep sorted by priority
        self._hooks[event].sort(key=lambda h: h.priority)

    def unregister_hook(self, event: HookEvent, name: str) -> bool:
        """Unregister a hook by name. Returns True if found and removed."""
        before = len(self._hooks[event])
        self._hooks[event] = [h for h in self._hooks[event] if h.name != name]
        return len(self._hooks[event]) < before

    async def emit(self, event: HookEvent, **kwargs: Any) -> None:
        """Emit a lifecycle event, triggering all registered hooks."""
        ctx = HookContext(
            event=event,
            state=self._state,
            **kwargs,
        )

        for hook in self._hooks[event]:
            try:
                await hook.func(ctx)
            except Exception as e:
                # Hooks should not crash the main loop
                self._state.error_log.append(
                    f"Hook error [{hook.name}@{event.value}]: {e}"
                )

    async def emit_transition(self, from_phase: AgentPhase, to_phase: AgentPhase) -> None:
        """Emit pre/post transition events."""
        await self.emit(
            HookEvent.PRE_TRANSITION,
            phase_from=from_phase,
            phase_to=to_phase,
        )
        await self.emit(
            HookEvent.POST_TRANSITION,
            phase_from=from_phase,
            phase_to=to_phase,
        )

    async def emit_error(self, error: Exception, data: dict[str, Any] | None = None) -> None:
        """Emit an error event."""
        await self.emit(HookEvent.ON_ERROR, error=error, data=data or {})

    def check_timeout(self) -> bool:
        """Check if the overall timeout has been exceeded.

        Returns True if timed out.
        """
        elapsed = time.time() - self._start_time
        return elapsed > self._timeout_seconds

    def elapsed_seconds(self) -> float:
        """Get elapsed time since start."""
        return time.time() - self._start_time

    def record_step_time(self, duration: float) -> None:
        """Record the duration of a step for performance tracking."""
        self._step_times.append(duration)

    def average_step_time(self) -> float:
        """Get average step duration."""
        if not self._step_times:
            return 0.0
        return sum(self._step_times) / len(self._step_times)

    def estimated_remaining_time(self) -> float:
        """Estimate remaining time based on remaining steps."""
        remaining_rounds = self._state.max_rounds - self._state.current_round
        avg = self.average_step_time()
        # Rough estimate: ~3 steps per round
        return remaining_rounds * 3 * avg

    async def run_with_timeout(self, coro: Awaitable[Any], timeout: float | None = None) -> Any:
        """Run a coroutine with timeout enforcement.

        Raises asyncio.TimeoutError if exceeded.
        """
        effective_timeout = timeout or self._timeout_seconds
        remaining = effective_timeout - self.elapsed_seconds()
        if remaining <= 0:
            await self.emit(HookEvent.ON_TIMEOUT)
            raise asyncio.TimeoutError("Overall timeout exceeded")

        try:
            return await asyncio.wait_for(coro, timeout=min(remaining, 120.0))
        except asyncio.TimeoutError:
            await self.emit(HookEvent.ON_TIMEOUT)
            raise


def build_default_hooks(lifecycle: LifecycleManager) -> None:
    """Register default lifecycle hooks for logging and monitoring."""

    async def log_transition(ctx: HookContext) -> None:
        """Log state transitions."""
        if ctx.phase_from and ctx.phase_to:
            ctx.state.transition_history.append(
                (ctx.phase_from.value, ctx.phase_to.value)
            )

    async def log_error(ctx: HookContext) -> None:
        """Log errors to state."""
        if ctx.error:
            msg = f"[{ctx.state.phase.value}] {type(ctx.error).__name__}: {ctx.error}"
            ctx.state.error_log.append(msg)

    async def budget_warning(ctx: HookContext) -> None:
        """Handle budget warnings."""
        pass  # Handled by context manager

    async def round_logging(ctx: HookContext) -> None:
        """Log round start/end."""
        pass  # State tracking handles this

    lifecycle.register_hook(HookEvent.POST_TRANSITION, log_transition, "log_transition")
    lifecycle.register_hook(HookEvent.ON_ERROR, log_error, "log_error")
    lifecycle.register_hook(HookEvent.ON_BUDGET_WARNING, budget_warning, "budget_warning")
    lifecycle.register_hook(HookEvent.ON_ROUND_START, round_logging, "round_logging")
