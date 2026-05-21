"""Lifecycle Hooks — hooks at key boundaries (pre/post operation, failure, timeout)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class HookEvent(str, Enum):
    """Events that trigger lifecycle hooks."""

    # Execution boundaries
    RUN_START = "run_start"
    RUN_END = "run_end"
    STEP_START = "step_start"
    STEP_END = "step_end"

    # Operation boundaries
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"

    # Error and recovery
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"
    PARSE_ERROR = "parse_error"
    TIMEOUT = "timeout"
    BUDGET_WARNING = "budget_warning"
    DOOM_LOOP = "doom_loop"

    # State transitions
    STATE_CHANGE = "state_change"
    CHECKPOINT_SAVED = "checkpoint_saved"
    CHECKPOINT_RESTORED = "checkpoint_restored"

    # Context management
    CONTEXT_COMPRESSED = "context_compressed"
    CONTEXT_OVERFLOW = "context_overflow"


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""

    event: HookEvent
    step_number: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def tool_name(self) -> str | None:
        return self.data.get("tool_name")

    @property
    def error(self) -> str | None:
        return self.data.get("error")

    @property
    def duration_ms(self) -> float | None:
        return self.data.get("duration_ms")


# Type alias for hook functions
HookFunc = Callable[[HookContext], None]


class LifecycleManager:
    """Manages lifecycle hooks at key execution boundaries.

    Hooks are registered for specific events and called in registration order.
    Hooks should not raise exceptions — errors are logged and swallowed.
    """

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookFunc]] = {event: [] for event in HookEvent}
        self._timing: dict[str, float] = {}
        self._stats: dict[str, int] = {
            "total_steps": 0,
            "tool_calls": 0,
            "llm_calls": 0,
            "errors": 0,
            "retries": 0,
        }

    def register(self, event: HookEvent, hook: HookFunc) -> None:
        """Register a hook function for an event."""
        self._hooks[event].append(hook)

    def unregister(self, event: HookEvent, hook: HookFunc) -> None:
        """Remove a hook function for an event."""
        try:
            self._hooks[event].remove(hook)
        except ValueError:
            pass

    def trigger(self, event: HookEvent, step_number: int = 0, **data: Any) -> None:
        """Trigger all hooks registered for an event."""
        ctx = HookContext(event=event, step_number=step_number, data=data)

        # Update internal stats
        self._update_stats(event)

        # Call registered hooks
        for hook in self._hooks[event]:
            try:
                hook(ctx)
            except Exception:
                # Hooks must not crash the harness
                pass

    def start_timer(self, label: str) -> None:
        """Start a named timer."""
        self._timing[label] = time.time()

    def stop_timer(self, label: str) -> float:
        """Stop a named timer and return elapsed milliseconds."""
        start = self._timing.pop(label, None)
        if start is None:
            return 0.0
        return (time.time() - start) * 1000

    @property
    def stats(self) -> dict[str, int]:
        """Get execution statistics."""
        return self._stats.copy()

    def _update_stats(self, event: HookEvent) -> None:
        """Update internal statistics based on events."""
        if event == HookEvent.STEP_END:
            self._stats["total_steps"] += 1
        elif event == HookEvent.POST_TOOL_CALL:
            self._stats["tool_calls"] += 1
        elif event == HookEvent.POST_LLM_CALL:
            self._stats["llm_calls"] += 1
        elif event in (HookEvent.TOOL_ERROR, HookEvent.LLM_ERROR, HookEvent.PARSE_ERROR):
            self._stats["errors"] += 1


def create_logging_hooks() -> list[tuple[HookEvent, HookFunc]]:
    """Create a set of hooks that log events to stdout (useful for debugging)."""
    import sys

    def log_hook(ctx: HookContext) -> None:
        ts = time.strftime("%H:%M:%S", time.localtime(ctx.timestamp))
        msg = f"[{ts}] {ctx.event.value}"
        if ctx.step_number:
            msg += f" (step {ctx.step_number})"
        if ctx.tool_name:
            msg += f" tool={ctx.tool_name}"
        if ctx.error:
            msg += f" error={ctx.error[:100]}"
        if ctx.duration_ms is not None:
            msg += f" ({ctx.duration_ms:.0f}ms)"
        print(msg, file=sys.stderr)

    hooks = []
    for event in HookEvent:
        hooks.append((event, log_hook))
    return hooks


def create_timing_hooks(lifecycle: LifecycleManager) -> None:
    """Register hooks that track timing of LLM and tool calls."""

    def pre_llm(ctx: HookContext) -> None:
        lifecycle.start_timer(f"llm_step_{ctx.step_number}")

    def post_llm(ctx: HookContext) -> None:
        elapsed = lifecycle.stop_timer(f"llm_step_{ctx.step_number}")
        # Could log or store this somewhere

    def pre_tool(ctx: HookContext) -> None:
        lifecycle.start_timer(f"tool_step_{ctx.step_number}_{ctx.tool_name}")

    def post_tool(ctx: HookContext) -> None:
        elapsed = lifecycle.stop_timer(f"tool_step_{ctx.step_number}_{ctx.tool_name}")

    lifecycle.register(HookEvent.PRE_LLM_CALL, pre_llm)
    lifecycle.register(HookEvent.POST_LLM_CALL, post_llm)
    lifecycle.register(HookEvent.PRE_TOOL_CALL, pre_tool)
    lifecycle.register(HookEvent.POST_TOOL_CALL, post_tool)
