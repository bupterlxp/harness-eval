"""
execution.py - Execution engine for the browser agent harness.

Implements dual-layer state machine:
- Outer layer: Task phases (INIT → LOGIN → DASHBOARD → EMPLOYEES → LEAVE_MGMT → REPORTS → REPORT_GEN)
- Inner layer: Page operation phases (NAVIGATE → WAIT_LOAD → POPUP_CHECK → INTERACT → EXTRACT → SCREENSHOT → RECORD)

Supports step-level retry and skip operations.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine

from harness.context import ContextManager
from harness.evaluation import TrajectoryLogger
from harness.lifecycle import HookResult, LifecycleManager
from harness.schemas import (
    PageOperationPhase,
    PageState,
    Screenshot,
    StepStatus,
    TaskPhase,
    TaskResult,
    TaskStep,
)
from harness.state import CheckpointManager, CrossPageDataStore, TaskGraph


class ExecutionState(str, Enum):
    """Overall execution state."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PageOperationContext:
    """Context for inner state machine page operations."""
    phase: PageOperationPhase
    step: TaskStep
    target_url: str | None = None
    selector: str | None = None
    action_type: str | None = None
    action_params: dict[str, Any] | None = None
    result: Any = None
    error: str | None = None


class ExecutionEngine:
    """
    Dual-layer state machine execution engine.

    Outer layer manages task flow across phases.
    Inner layer manages individual page operations within each step.
    """

    def __init__(
        self,
        task_graph: TaskGraph,
        data_store: CrossPageDataStore,
        context_manager: ContextManager,
        lifecycle_manager: LifecycleManager,
        trajectory_logger: TrajectoryLogger,
        checkpoint_manager: CheckpointManager | None = None,
    ) -> None:
        self._task_graph = task_graph
        self._data_store = data_store
        self._context = context_manager
        self._lifecycle = lifecycle_manager
        self._logger = trajectory_logger
        self._checkpoint = checkpoint_manager

        self._state = ExecutionState.IDLE
        self._current_phase = TaskPhase.INIT
        self._current_step: TaskStep | None = None
        self._current_page_phase = PageOperationPhase.NAVIGATE

        self._browser_tools: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}
        self._step_handlers: dict[int, Callable[..., Coroutine[Any, Any, bool]]] = {}

        self._pause_requested = False
        self._skip_requested: set[int] = set()
        self._retry_requested: set[int] = set()

        self._start_time: datetime | None = None
        self._screenshots: list[Screenshot] = []
        self._errors: list[str] = []

    @property
    def state(self) -> ExecutionState:
        """Get current execution state."""
        return self._state

    @property
    def current_phase(self) -> TaskPhase:
        """Get current task phase."""
        return self._current_phase

    @property
    def current_step(self) -> TaskStep | None:
        """Get currently executing step."""
        return self._current_step

    def set_browser_tool(
        self,
        name: str,
        handler: Callable[..., Coroutine[Any, Any, Any]],
    ) -> None:
        """Register a browser tool handler."""
        self._browser_tools[name] = handler

    def set_step_handler(
        self,
        step_id: int,
        handler: Callable[..., Coroutine[Any, Any, bool]],
    ) -> None:
        """Register a custom handler for a specific step."""
        self._step_handlers[step_id] = handler

    async def _call_tool(self, name: str, **params: Any) -> Any:
        """Call a browser tool with logging."""
        if name not in self._browser_tools:
            raise ValueError(f"Unknown tool: {name}")

        step_id = self._current_step.step_id if self._current_step else None
        url = self._context.page.current_url

        self._logger.log_tool_call(step_id, name, params, url)

        start = datetime.now()
        try:
            result = await self._browser_tools[name](**params)
            duration = int((datetime.now() - start).total_seconds() * 1000)
            self._logger.log_tool_result(step_id, name, result, True, None, duration, url)
            return result
        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            self._logger.log_tool_result(step_id, name, None, False, str(e), duration, url)
            raise

    async def run(self) -> TaskResult:
        """Execute all task steps."""
        self._state = ExecutionState.RUNNING
        self._start_time = datetime.now()

        try:
            while self._task_graph.can_continue() and self._state == ExecutionState.RUNNING:
                if self._pause_requested:
                    self._state = ExecutionState.PAUSED
                    break

                step = self._task_graph.get_next_executable()
                if not step:
                    break

                if step.step_id in self._skip_requested:
                    self._skip_step(step)
                    continue

                await self._execute_step(step)

                if self._checkpoint:
                    self._checkpoint.save(
                        self._task_graph,
                        self._data_store,
                        self._current_phase,
                    )

            if self._task_graph.is_complete():
                self._state = ExecutionState.COMPLETED

        except Exception as e:
            self._state = ExecutionState.FAILED
            self._errors.append(str(e))
            self._logger.log_error(
                self._current_step.step_id if self._current_step else None,
                str(e),
                self._context.page.current_url,
            )

        return self._build_result()

    async def _execute_step(self, step: TaskStep) -> None:
        """Execute a single task step with inner state machine."""
        self._current_step = step
        self._context.task.set_current_step(step.step_id)
        self._task_graph.update_step_status(step.step_id, StepStatus.RUNNING)

        self._logger.log_step_start(
            step.step_id,
            step.action,
            self._context.page.current_url,
        )

        retry_count = 0
        success = False

        while retry_count <= step.max_retries and not success:
            try:
                if step.step_id in self._step_handlers:
                    success = await self._step_handlers[step.step_id](step, self)
                else:
                    success = await self._execute_page_operation(step)

                if success:
                    self._task_graph.update_step_status(step.step_id, StepStatus.COMPLETED)
                    step.retry_count = retry_count
                else:
                    raise RuntimeError(f"Step {step.step_id} failed")

            except Exception as e:
                retry_count += 1
                step.retry_count = retry_count

                if retry_count <= step.max_retries:
                    hook_result = await self._lifecycle.on_timeout(
                        step.step_id,
                        self._context.page.current_url,
                        step.action,
                        retry_count - 1,
                        step.max_retries,
                    )

                    self._logger.log_retry(
                        step.step_id,
                        retry_count,
                        step.max_retries,
                        str(e),
                        self._context.page.current_url,
                    )

                    if hook_result.screenshot_path:
                        self._screenshots.append(Screenshot(
                            path=hook_result.screenshot_path,
                            step_id=step.step_id,
                            url=self._context.page.current_url or "",
                            description=f"Retry {retry_count}",
                        ))

                    await asyncio.sleep(1)
                else:
                    self._task_graph.update_step_status(
                        step.step_id,
                        StepStatus.FAILED,
                        str(e),
                    )
                    self._errors.append(f"Step {step.step_id}: {e}")
                    break

        self._logger.log_step_end(
            step.step_id,
            success,
            self._context.page.current_url,
            step.error_message,
            step.extracted_data,
            step.retry_count,
        )

        self._update_phase(step)
        self._current_step = None

    async def _execute_page_operation(self, step: TaskStep) -> bool:
        """Execute inner state machine for page operations."""
        phases = [
            PageOperationPhase.NAVIGATE,
            PageOperationPhase.WAIT_LOAD,
            PageOperationPhase.POPUP_CHECK,
            PageOperationPhase.INTERACT,
            PageOperationPhase.EXTRACT,
            PageOperationPhase.SCREENSHOT,
            PageOperationPhase.RECORD,
        ]

        for phase in phases:
            self._current_page_phase = phase
            success = await self._execute_phase(step, phase)
            if not success:
                return False

        return True

    async def _execute_phase(self, step: TaskStep, phase: PageOperationPhase) -> bool:
        """Execute a single phase of the inner state machine."""
        if phase == PageOperationPhase.POPUP_CHECK:
            if self._context.page.has_popup:
                popup_type = self._context.page.popup_type
                if popup_type:
                    await self._lifecycle.on_popup(
                        step.step_id,
                        self._context.page.current_url,
                        popup_type,
                    )
            return True

        elif phase == PageOperationPhase.SCREENSHOT:
            if "screenshot" in self._browser_tools:
                path = f"screenshots/step_{step.step_id}_{datetime.now().strftime('%H%M%S')}.png"
                try:
                    await self._call_tool("screenshot", path=path)
                    step.screenshot_path = path
                    self._screenshots.append(Screenshot(
                        path=path,
                        step_id=step.step_id,
                        url=self._context.page.current_url or "",
                        description=step.action,
                    ))
                    self._logger.log_screenshot(
                        step.step_id,
                        path,
                        self._context.page.current_url,
                        step.action,
                    )
                except Exception:
                    pass
            return True

        elif phase == PageOperationPhase.RECORD:
            if step.extracted_data:
                for key, value in step.extracted_data.items():
                    self._data_store.set(key, value)
                    self._context.task.store_extracted_data(key, value)
                self._logger.log_extraction(
                    step.step_id,
                    step.extracted_data,
                    None,
                    self._context.page.current_url,
                )
            return True

        return True

    def _update_phase(self, step: TaskStep) -> None:
        """Update outer state machine phase based on completed step."""
        phase_map = {
            1: TaskPhase.INIT,
            2: TaskPhase.LOGIN,
            3: TaskPhase.LOGIN,
            4: TaskPhase.DASHBOARD,
            5: TaskPhase.EMPLOYEES,
            6: TaskPhase.EMPLOYEES,
            7: TaskPhase.LEAVE_MGMT,
            8: TaskPhase.LEAVE_MGMT,
            9: TaskPhase.LEAVE_MGMT,
            10: TaskPhase.REPORTS,
            11: TaskPhase.REPORTS,
            12: TaskPhase.REPORT_GEN,
        }
        if step.step_id in phase_map:
            self._current_phase = phase_map[step.step_id]

    def _skip_step(self, step: TaskStep) -> None:
        """Mark a step as skipped."""
        self._task_graph.update_step_status(step.step_id, StepStatus.SKIPPED)
        self._skip_requested.discard(step.step_id)
        self._logger.log_step_start(step.step_id, step.action, self._context.page.current_url)
        self._logger.log_step_end(
            step.step_id,
            True,
            self._context.page.current_url,
            "Skipped by user request",
        )

    def _build_result(self) -> TaskResult:
        """Build final execution result."""
        stats = self._task_graph.get_stats()

        duration_ms = 0
        if self._start_time:
            duration_ms = int((datetime.now() - self._start_time).total_seconds() * 1000)

        return TaskResult(
            success=stats["failed"] == 0 and stats["completed"] == stats["total"],
            total_steps=stats["total"],
            completed_steps=stats["completed"],
            failed_steps=stats["failed"],
            skipped_steps=stats["skipped"],
            extracted_data=self._data_store.get_all_extracted_data(),
            screenshots=self._screenshots,
            errors=self._errors,
            execution_time_ms=duration_ms,
            trajectory_path=self._logger.file_path,
        )

    def pause(self) -> None:
        """Request pause after current step."""
        self._pause_requested = True

    def resume(self) -> None:
        """Resume paused execution."""
        if self._state == ExecutionState.PAUSED:
            self._pause_requested = False
            self._state = ExecutionState.RUNNING

    def skip_step(self, step_id: int) -> None:
        """Mark a step to be skipped."""
        self._skip_requested.add(step_id)

    def retry_step(self, step_id: int) -> None:
        """Mark a step for retry."""
        step = self._task_graph.get_step(step_id)
        if step and step.status in (StepStatus.FAILED, StepStatus.SKIPPED):
            step.status = StepStatus.PENDING
            step.retry_count = 0
            step.error_message = None
            self._retry_requested.add(step_id)

    def get_progress(self) -> dict[str, Any]:
        """Get current execution progress."""
        stats = self._task_graph.get_stats()
        return {
            "state": self._state.value,
            "phase": self._current_phase.value,
            "current_step": self._current_step.step_id if self._current_step else None,
            "page_phase": self._current_page_phase.value,
            **stats,
        }
