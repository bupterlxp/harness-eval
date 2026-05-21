"""Lifecycle Hooks (L) — hooks at key boundaries.

Provides pre/post operation hooks, failure handlers, timeout handlers,
and startup/shutdown hooks. Allows instrumentation and error recovery
at each phase of the execution loop.
"""

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from harness.state import TaskState, StepMemory


class HookPhase(str, Enum):
    """Phases where lifecycle hooks can fire."""

    PRE_STEP = "pre_step"
    POST_STEP = "post_step"
    PRE_ACTION = "pre_action"
    POST_ACTION = "post_action"
    PRE_LLM_CALL = "pre_llm_call"
    POST_LLM_CALL = "post_llm_call"
    ON_FAILURE = "on_failure"
    ON_TIMEOUT = "on_timeout"
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    ON_STAGNATION = "on_stagnation"
    ON_PLAN_UPDATE = "on_plan_update"
    ON_CHECKPOINT = "on_checkpoint"
    ON_TAB_CHANGE = "on_tab_change"
    ON_POPUP = "on_popup"
    ON_RECOVERY = "on_recovery"


# Hook function type: receives context dict, returns optional modified context
HookFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


@dataclass
class HookRegistration:
    """A registered hook with priority for ordering."""

    phase: HookPhase
    handler: HookFn
    name: str
    priority: int = 0  # Higher priority runs first


@dataclass
class LifecycleEvent:
    """Record of a lifecycle event for debugging."""

    phase: HookPhase
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0
    error: str | None = None


class LifecycleHooks:
    """Manages lifecycle hooks at key execution boundaries."""

    def __init__(self):
        self._hooks: dict[HookPhase, list[HookRegistration]] = {
            phase: [] for phase in HookPhase
        }
        self._event_log: list[LifecycleEvent] = []
        self._max_event_log: int = 200
        self._start_time: float = 0
        self._register_default_hooks()

    def register(
        self,
        phase: HookPhase,
        handler: HookFn,
        name: str = "",
        priority: int = 0,
    ) -> None:
        """Register a hook for a specific phase."""
        reg = HookRegistration(
            phase=phase, handler=handler, name=name or handler.__name__, priority=priority
        )
        self._hooks[phase].append(reg)
        # Sort by priority (higher first)
        self._hooks[phase].sort(key=lambda h: -h.priority)

    async def fire(self, phase: HookPhase, context: dict[str, Any]) -> dict[str, Any]:
        """Fire all hooks for a phase, passing context through the chain."""
        start = time.time()
        result_context = context.copy()
        error_msg = None

        for hook in self._hooks[phase]:
            try:
                result = await hook.handler(result_context)
                if result is not None:
                    result_context = result
            except Exception as e:
                error_msg = f"Hook '{hook.name}' failed: {str(e)}"
                result_context["hook_error"] = error_msg
                # Don't break the chain on hook failure
                continue

        duration_ms = (time.time() - start) * 1000
        event = LifecycleEvent(
            phase=phase,
            timestamp=time.time(),
            data={"hook_count": len(self._hooks[phase])},
            duration_ms=duration_ms,
            error=error_msg,
        )
        self._event_log.append(event)
        if len(self._event_log) > self._max_event_log:
            self._event_log = self._event_log[-self._max_event_log:]

        return result_context

    async def fire_startup(self, task_state: TaskState) -> None:
        """Fire startup hooks."""
        self._start_time = time.time()
        await self.fire(HookPhase.ON_STARTUP, {"task_state": task_state})

    async def fire_shutdown(self, task_state: TaskState, result: dict[str, Any]) -> None:
        """Fire shutdown hooks."""
        elapsed = time.time() - self._start_time
        await self.fire(HookPhase.ON_SHUTDOWN, {
            "task_state": task_state,
            "result": result,
            "elapsed_seconds": elapsed,
        })

    async def fire_pre_step(self, task_state: TaskState, step: int) -> dict[str, Any]:
        """Fire pre-step hooks. Returns context that may modify step behavior."""
        return await self.fire(HookPhase.PRE_STEP, {
            "task_state": task_state,
            "step": step,
        })

    async def fire_post_step(
        self, task_state: TaskState, step: int, action_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Fire post-step hooks."""
        return await self.fire(HookPhase.POST_STEP, {
            "task_state": task_state,
            "step": step,
            "action_result": action_result,
        })

    async def fire_pre_action(
        self, action_type: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Fire pre-action hooks. Can modify action parameters."""
        return await self.fire(HookPhase.PRE_ACTION, {
            "action_type": action_type,
            "params": params,
        })

    async def fire_post_action(
        self, action_type: str, params: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """Fire post-action hooks."""
        return await self.fire(HookPhase.POST_ACTION, {
            "action_type": action_type,
            "params": params,
            "result": result,
        })

    async def fire_failure(
        self, error: str, task_state: TaskState, step: int
    ) -> dict[str, Any]:
        """Fire failure hooks. May provide recovery instructions."""
        return await self.fire(HookPhase.ON_FAILURE, {
            "error": error,
            "task_state": task_state,
            "step": step,
        })

    async def fire_timeout(self, task_state: TaskState, elapsed: float) -> dict[str, Any]:
        """Fire timeout hooks."""
        return await self.fire(HookPhase.ON_TIMEOUT, {
            "task_state": task_state,
            "elapsed_seconds": elapsed,
        })

    async def fire_stagnation(
        self, task_state: TaskState, warning: str
    ) -> dict[str, Any]:
        """Fire stagnation hooks."""
        return await self.fire(HookPhase.ON_STAGNATION, {
            "task_state": task_state,
            "warning": warning,
        })

    async def fire_checkpoint(self, task_state: TaskState, path: str) -> None:
        """Fire checkpoint hooks."""
        await self.fire(HookPhase.ON_CHECKPOINT, {
            "task_state": task_state,
            "checkpoint_path": path,
        })

    async def fire_tab_change(
        self, task_state: TaskState, old_tab: str, new_tab: str
    ) -> None:
        """Fire tab change hooks."""
        await self.fire(HookPhase.ON_TAB_CHANGE, {
            "task_state": task_state,
            "old_tab": old_tab,
            "new_tab": new_tab,
        })

    async def fire_popup(self, popup_info: dict[str, Any]) -> dict[str, Any]:
        """Fire popup detection hooks."""
        return await self.fire(HookPhase.ON_POPUP, {"popup_info": popup_info})

    def get_event_log(self) -> list[dict[str, Any]]:
        """Get lifecycle event log for debugging."""
        return [
            {
                "phase": e.phase.value,
                "timestamp": e.timestamp,
                "duration_ms": e.duration_ms,
                "error": e.error,
                **e.data,
            }
            for e in self._event_log
        ]

    def _register_default_hooks(self) -> None:
        """Register default lifecycle hooks."""

        async def log_step_start(ctx: dict[str, Any]) -> dict[str, Any] | None:
            step = ctx.get("step", 0)
            state = ctx.get("task_state")
            if state:
                print(f"  [Step {step}] URL: {state.current_url}")
            return None

        async def log_action(ctx: dict[str, Any]) -> dict[str, Any] | None:
            action = ctx.get("action_type", "")
            params = ctx.get("params", {})
            print(f"  [Action] {action}: {_dumps_short(params)}")
            return None

        async def log_failure(ctx: dict[str, Any]) -> dict[str, Any] | None:
            error = ctx.get("error", "")
            step = ctx.get("step", 0)
            print(f"  [FAILURE at step {step}] {error}")
            return None

        async def log_shutdown(ctx: dict[str, Any]) -> dict[str, Any] | None:
            elapsed = ctx.get("elapsed_seconds", 0)
            result = ctx.get("result", {})
            status = result.get("status", "unknown")
            print(f"  [Shutdown] Status: {status}, Elapsed: {elapsed:.1f}s")
            return None

        self.register(HookPhase.PRE_STEP, log_step_start, "log_step_start", priority=-10)
        self.register(HookPhase.ON_FAILURE, log_failure, "log_failure", priority=-10)
        self.register(HookPhase.ON_SHUTDOWN, log_shutdown, "log_shutdown", priority=-10)


def _dumps_short(obj: Any, max_len: int = 100) -> str:
    """Serialize object to short JSON string for logging."""
    import json as _json_mod
    try:
        s = _json_mod.dumps(obj, ensure_ascii=False)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    except (TypeError, ValueError):
        return str(obj)[:max_len]


class ErrorRecoveryManager:
    """Manages error recovery strategies."""

    def __init__(self):
        self._recovery_strategies: list[str] = [
            "scroll_to_element",
            "try_different_selector",
            "go_back_and_retry",
            "refresh_page",
            "wait_and_retry",
        ]
        self._current_strategy_index: int = 0

    def get_recovery_instruction(
        self, consecutive_failures: int, element_failures: int
    ) -> str:
        """Get recovery instruction based on failure pattern."""
        if element_failures >= 3:
            return (
                "Multiple failures on same element. Try: scroll to make it visible, "
                "use a different selector strategy, or navigate back and try alternate path."
            )
        if consecutive_failures >= 3:
            return (
                "Multiple consecutive failures. Consider: refreshing the page, "
                "going back to a known state, or trying a completely different approach."
            )
        if consecutive_failures >= 2:
            return "Action failed again. Try waiting briefly or scrolling to ensure element is visible."
        return "Previous action failed. Re-observe the page and try an alternative."

    def get_next_strategy(self) -> str:
        """Get next recovery strategy to try."""
        strategy = self._recovery_strategies[
            self._current_strategy_index % len(self._recovery_strategies)
        ]
        self._current_strategy_index += 1
        return strategy

    def reset(self) -> None:
        """Reset recovery state."""
        self._current_strategy_index = 0


class RetryManager:
    """Manages API retry with exponential backoff."""

    def __init__(
        self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute_with_retry(
        self, func: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
    ) -> Any:
        """Execute a function with exponential backoff retry."""
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt == self.max_retries:
                    break
                delay = min(self.base_delay * (2**attempt), self.max_delay)
                print(f"  [Retry] Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        raise last_error  # type: ignore
