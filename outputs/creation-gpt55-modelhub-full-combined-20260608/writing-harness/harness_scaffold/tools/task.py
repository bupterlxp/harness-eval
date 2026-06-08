"""TaskTool: a generic, network-free subtask abstraction.

A :class:`~harness_scaffold.core.context.RuntimeContext`-driven program often
needs to run a nested sub-step in isolation: with its own slice of the step /
time / output budget, its own labelled trajectory events, and a clear
success/failure boundary. ``TaskTool`` provides exactly that and nothing more.

It does NOT spawn a model, talk to the network, or shell out. The caller hands
it a *runner*: a plain callable (sync or async) that takes ``(ctx, args)`` and
returns either a :class:`~harness_scaffold.core.schemas.ToolResult` or any
JSON-serialisable value. The runner is supplied either:

  * programmatically -- the host program registers a runner on the tool
    instance via :meth:`TaskTool.register_runner` or by constructing
    ``TaskTool(runner=...)``; or
  * by name -- pass ``args["runner"]`` matching a previously registered runner.

During execution the tool:

  * derives a child :class:`~harness_scaffold.core.budgets.Budget` carved out of
    the parent's remaining budget (``max_steps`` / ``max_seconds`` /
    ``max_output_bytes`` overridable per call, always clamped to what the parent
    has left), and a child :class:`~harness_scaffold.core.abort.AbortSignal`
    sharing the parent deadline;
  * builds a child ``RuntimeContext`` whose artifacts/permissions/logging are
    the parent's (so subtask output is confined to the same sandbox), but whose
    budget/abort/metadata are the child's;
  * records ``subtask_start`` / ``subtask_end`` markers on the parent
    trajectory.

The tool never prints, never raises to the caller, and runs no subprocess.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any, Awaitable, Callable

from harness_scaffold.core.abort import AbortSignal
from harness_scaffold.core.budgets import Budget
from harness_scaffold.core.context import RuntimeContext
from harness_scaffold.core.errors import ErrorCode, HarnessError, TimeoutErrorH
from harness_scaffold.core.schemas import ToolResult
from harness_scaffold.tools.base import AtomicTool

Runner = Callable[[RuntimeContext, dict], Any]


class TaskTool(AtomicTool):
    name = "task"
    description = (
        "Run a nested sub-step (subtask) in isolation with its own slice of the "
        "step/time/output budget. The subtask runner is a host-provided callable; "
        "no network, model, or shell access is performed by this tool itself."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Human-readable name for this subtask.",
            },
            "runner": {
                "type": "string",
                "description": "Name of a registered runner to invoke (optional "
                "if a default runner was supplied to the tool).",
            },
            "args": {
                "type": "object",
                "description": "Arguments object passed through to the runner.",
            },
            "max_steps": {
                "type": "integer",
                "description": "Step budget for the subtask (clamped to parent).",
            },
            "max_seconds": {
                "type": "number",
                "description": "Time budget for the subtask (clamped to parent).",
            },
            "max_output_bytes": {
                "type": "integer",
                "description": "Output-byte budget for the subtask (clamped to parent).",
            },
        },
        "required": [],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "ok": {"type": "boolean"},
            "result": {},
            "budget": {"type": "object"},
        },
    }
    is_read_only = False
    is_destructive = False
    requires_network = False
    requires_optional_dependency = False

    def __init__(self, *, runner: Runner | None = None,
                 runners: dict[str, Runner] | None = None):
        self._default_runner = runner
        self._runners: dict[str, Runner] = dict(runners or {})

    # ----- runner registration (host-program facing) -----
    def register_runner(self, name: str, runner: Runner) -> None:
        """Register a named runner the program can later invoke by name."""
        self._runners[name] = runner

    def set_default_runner(self, runner: Runner) -> None:
        self._default_runner = runner

    def _resolve_runner(self, args: dict) -> Runner | None:
        name = args.get("runner")
        if name:
            return self._runners.get(name)
        return self._default_runner

    # ----- budget slicing -----
    @staticmethod
    def _clamp(requested, available, default):
        """Pick a child budget bound: requested if given, else default; never
        exceeding the parent's available headroom (when finite)."""
        val = requested if requested is not None else default
        if val is None:
            val = available
        if available is not None and available >= 0 and val > available:
            val = available
        return val

    def _child_budget(self, ctx: RuntimeContext, args: dict) -> Budget:
        parent = ctx.budget
        try:
            steps_left = max(int(parent.steps_left()), 0)
        except Exception:
            steps_left = ctx.policy.max_steps
        try:
            secs_left = float(parent.seconds_left())
        except Exception:
            secs_left = ctx.policy.max_seconds
        try:
            bytes_left = max(int(parent.output_bytes_left()), 0)
        except Exception:
            bytes_left = ctx.policy.max_output_bytes

        max_steps = self._clamp(args.get("max_steps"), steps_left, steps_left)
        max_seconds = self._clamp(args.get("max_seconds"), secs_left, secs_left)
        max_output_bytes = self._clamp(
            args.get("max_output_bytes"), bytes_left, bytes_left
        )
        return Budget(
            max_steps=int(max_steps),
            max_seconds=float(max_seconds),
            max_output_bytes=int(max_output_bytes),
        )

    # ----- main entry point -----
    async def run(self, ctx: RuntimeContext, args: dict) -> ToolResult:
        label = str(args.get("label") or args.get("runner") or "subtask")
        runner = self._resolve_runner(args)
        if runner is None:
            return ToolResult.fail(
                "no subtask runner available (supply TaskTool(runner=...), "
                "register_runner(name, fn), or args['runner'] naming one)",
                error_code=ErrorCode.TOOL_ERROR,
                stage="task",
            )

        sub_args = args.get("args")
        if sub_args is None:
            sub_args = {}
        if not isinstance(sub_args, dict):
            return ToolResult.fail(
                "subtask 'args' must be an object",
                error_code=ErrorCode.TOOL_ERROR,
                stage="task",
            )

        child_budget = self._child_budget(ctx, args)
        child_abort = AbortSignal(
            deadline_seconds=child_budget.seconds_left(),
            reason=ctx.abort_signal.reason,
        )
        child_meta = dict(ctx.metadata)
        child_meta["subtask"] = label
        child_ctx = replace(
            ctx,
            budget=child_budget,
            abort_signal=child_abort,
            metadata=child_meta,
        )

        started = time.time()
        ctx.trajectory.log_info(
            f"subtask_start: {label}",
            subtask=label,
            budget={
                "max_steps": child_budget.max_steps
                if hasattr(child_budget, "max_steps") else None,
                "max_seconds": getattr(child_budget, "max_seconds", None),
            },
        )

        try:
            # honour the parent abort/deadline before doing work
            ctx.check_abort(stage="task")
            outcome = runner(child_ctx, sub_args)
            if asyncio.iscoroutine(outcome) or isinstance(outcome, Awaitable):
                outcome = await outcome
        except TimeoutErrorH as exc:
            return self._finish_fail(
                ctx, label, started, child_budget, exc,
                ErrorCode.TIMEOUT,
            )
        except HarnessError as exc:
            return self._finish_fail(
                ctx, label, started, child_budget, exc,
                getattr(exc, "error_code", ErrorCode.TOOL_ERROR),
            )
        except Exception as exc:  # noqa: BLE001 - never raise to caller
            return self._finish_fail(
                ctx, label, started, child_budget, exc,
                ErrorCode.TOOL_ERROR,
            )

        elapsed = time.time() - started

        # Normalise the runner's return value.
        if isinstance(outcome, ToolResult):
            sub_result = outcome
        else:
            sub_result = ToolResult.success(data=outcome)

        budget_snap = self._budget_snapshot(child_budget)
        ctx.trajectory.log_info(
            f"subtask_end: {label}",
            subtask=label,
            ok=sub_result.ok,
            elapsed_seconds=elapsed,
            budget=budget_snap,
        )

        if not sub_result.ok:
            # Surface the child's structured error verbatim.
            return ToolResult.fail(
                sub_result.error
                or "subtask failed",
                error_code=ErrorCode.TOOL_ERROR,
                stage="task",
                artifacts=sub_result.artifacts,
                elapsed_seconds=elapsed,
                metadata={"label": label, "budget": budget_snap},
            )

        return ToolResult.success(
            data={
                "label": label,
                "ok": True,
                "result": sub_result.data,
                "budget": budget_snap,
            },
            artifacts=sub_result.artifacts,
            stdout_preview=f"subtask {label}: ok",
            elapsed_seconds=elapsed,
            metadata={"label": label, "budget": budget_snap},
        )

    # ----- failure helper -----
    def _finish_fail(self, ctx, label, started, child_budget, exc, code):
        elapsed = time.time() - started
        budget_snap = self._budget_snapshot(child_budget)
        ctx.trajectory.log_info(
            f"subtask_end: {label}",
            subtask=label,
            ok=False,
            error=str(exc),
            elapsed_seconds=elapsed,
            budget=budget_snap,
        )
        return ToolResult.fail(
            f"subtask {label!r} failed: {exc}",
            error_code=code,
            stage="task",
            elapsed_seconds=elapsed,
            metadata={"label": label, "budget": budget_snap},
        )

    @staticmethod
    def _budget_snapshot(budget: Budget) -> dict:
        try:
            return budget.snapshot()
        except Exception:
            return {
                "steps_used": getattr(budget, "steps_used", None),
                "output_bytes_used": getattr(budget, "output_bytes_used", None),
            }


def get_tools() -> list[AtomicTool]:
    """Discovery hook: return the tool instances defined in this module.

    A bare ``TaskTool()`` has no runner registered; the host program is expected
    to call :meth:`TaskTool.register_runner` / :meth:`TaskTool.set_default_runner`
    (or construct its own ``TaskTool(runner=...)``) before invoking it.
    """
    return [TaskTool()]
