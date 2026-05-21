"""Lifecycle Hooks — hooks at key boundaries.

Provides pre/post operation hooks, failure handlers, timeout handlers,
and step boundary notifications. Allows external observers to monitor
and react to execution events.
"""

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class LifecycleHook(Protocol):
    """Protocol for lifecycle hook callables."""

    def __call__(self, **kwargs: Any) -> None: ...


@dataclass
class StepMetrics:
    """Metrics collected during a single step."""

    step_number: int
    state: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: int = 0
    token_usage: dict[str, int] = field(default_factory=dict)
    success: bool = True
    error: str | None = None
    retry_count: int = 0


class LifecycleManager:
    """Manages lifecycle hooks at key execution boundaries.

    Hook points:
      - pre_step / post_step: Before and after each execution step
      - pre_llm_call / post_llm_call: Before and after LLM API calls
      - pre_code_execution / post_code_execution: Before and after code runs
      - on_failure: When an unrecoverable error occurs
      - on_timeout: When a step exceeds time limit
      - on_checkpoint: When a checkpoint is saved
      - on_compression: When context compression is triggered
      - on_terminate: When the agent decides to terminate
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[..., None]]] = {
            "pre_step": [],
            "post_step": [],
            "pre_llm_call": [],
            "post_llm_call": [],
            "pre_code_execution": [],
            "post_code_execution": [],
            "on_failure": [],
            "on_timeout": [],
            "on_checkpoint": [],
            "on_compression": [],
            "on_terminate": [],
            "on_plan_created": [],
            "on_artifact_registered": [],
        }
        self._step_metrics: list[StepMetrics] = []
        self._current_metrics: StepMetrics | None = None

    def register_hook(self, event: str, hook: Callable[..., None]) -> None:
        """Register a hook for a specific lifecycle event."""
        if event not in self._hooks:
            raise ValueError(f"Unknown lifecycle event: {event}")
        self._hooks[event].append(hook)

    def _fire(self, event: str, **kwargs: Any) -> None:
        """Fire all hooks registered for an event."""
        for hook in self._hooks.get(event, []):
            try:
                hook(**kwargs)
            except Exception:
                # Hooks should not break execution
                pass

    def pre_step(self, step_number: int, state: str) -> None:
        """Called before each execution step."""
        self._current_metrics = StepMetrics(
            step_number=step_number,
            state=state,
            start_time=time.time(),
        )
        self._fire("pre_step", step_number=step_number, state=state)

    def post_step(
        self,
        step_number: int,
        state: str,
        success: bool = True,
        error: str | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> StepMetrics:
        """Called after each execution step. Returns collected metrics."""
        if self._current_metrics is None:
            self._current_metrics = StepMetrics(step_number=step_number, state=state)

        self._current_metrics.end_time = time.time()
        self._current_metrics.duration_ms = int(
            (self._current_metrics.end_time - self._current_metrics.start_time) * 1000
        )
        self._current_metrics.success = success
        self._current_metrics.error = error
        self._current_metrics.token_usage = token_usage or {}
        self._step_metrics.append(self._current_metrics)

        self._fire(
            "post_step",
            step_number=step_number,
            state=state,
            success=success,
            error=error,
            metrics=self._current_metrics,
        )

        metrics = self._current_metrics
        self._current_metrics = None
        return metrics

    def pre_llm_call(self, messages_count: int, token_budget: int) -> None:
        """Called before an LLM API call."""
        self._fire(
            "pre_llm_call",
            messages_count=messages_count,
            token_budget=token_budget,
        )

    def post_llm_call(self, token_usage: dict[str, int], duration_ms: int) -> None:
        """Called after an LLM API call."""
        self._fire(
            "post_llm_call",
            token_usage=token_usage,
            duration_ms=duration_ms,
        )

    def pre_code_execution(self, code: str) -> None:
        """Called before code execution in sandbox."""
        self._fire("pre_code_execution", code=code)

    def post_code_execution(
        self, code: str, success: bool, output: str, duration_ms: int
    ) -> None:
        """Called after code execution."""
        self._fire(
            "post_code_execution",
            code=code,
            success=success,
            output=output,
            duration_ms=duration_ms,
        )

    def on_failure(self, error: Exception | None = None, context: str = "") -> None:
        """Called when an unrecoverable error occurs."""
        error_str = "".join(traceback.format_exception(error)) if error else context
        self._fire("on_failure", error=error_str, context=context)
        print(f"[lifecycle] FAILURE: {error_str[:200]}")

    def on_timeout(self, step_number: int, timeout_seconds: float) -> None:
        """Called when a step exceeds its time limit."""
        if self._current_metrics:
            self._current_metrics.error = f"Timeout after {timeout_seconds}s"
        self._fire(
            "on_timeout",
            step_number=step_number,
            timeout_seconds=timeout_seconds,
        )
        print(f"[lifecycle] TIMEOUT at step {step_number}: {timeout_seconds}s exceeded")

    def on_checkpoint(self, checkpoint_path: str) -> None:
        """Called when a checkpoint is saved."""
        self._fire("on_checkpoint", checkpoint_path=checkpoint_path)

    def on_compression(self, level: int, tokens_before: int, tokens_after: int) -> None:
        """Called when context compression is triggered."""
        self._fire(
            "on_compression",
            level=level,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )
        print(
            f"[lifecycle] Compression L{level}: {tokens_before} -> {tokens_after} tokens"
        )

    def on_terminate(self, reason: str, step_number: int) -> None:
        """Called when the agent decides to terminate."""
        self._fire("on_terminate", reason=reason, step_number=step_number)
        print(f"[lifecycle] Terminate at step {step_number}: {reason}")

    def on_plan_created(self, plan: list[dict[str, Any]]) -> None:
        """Called when a plan is created or updated."""
        self._fire("on_plan_created", plan=plan)

    def on_artifact_registered(self, artifact: dict[str, Any]) -> None:
        """Called when a new artifact is registered."""
        self._fire("on_artifact_registered", artifact=artifact)

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get aggregated metrics across all steps."""
        if not self._step_metrics:
            return {"total_steps": 0}

        total_duration = sum(m.duration_ms for m in self._step_metrics)
        success_count = sum(1 for m in self._step_metrics if m.success)
        total_tokens = sum(
            m.token_usage.get("total_tokens", 0) for m in self._step_metrics
        )

        return {
            "total_steps": len(self._step_metrics),
            "successful_steps": success_count,
            "failed_steps": len(self._step_metrics) - success_count,
            "total_duration_ms": total_duration,
            "avg_step_duration_ms": total_duration // max(len(self._step_metrics), 1),
            "total_tokens": total_tokens,
        }
