"""Execution Loop (E) - Main execution state machine.

Drives browser operations with explicit state machine separating:
- Task-level flow (task decomposition and progression)
- Single page operation logic

Supports single-step retry and skip with configurable retry limits.
"""

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TYPE_CHECKING

from openai import AsyncOpenAI

from harness.state import StateStore, StepState, StepStatus
from harness.context import ContextManager, PageContext
from harness.tools import ToolRegistry, ToolResult
from harness.lifecycle import LifecycleHooks
from harness.evaluation import TrajectoryRecorder

if TYPE_CHECKING:
    from playwright.async_api import Page, Browser, BrowserContext


class TaskFlowState(str, Enum):
    """Task-level state machine states."""
    INITIALIZING = "initializing"
    PLANNING = "planning"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"


class OperationState(str, Enum):
    """Single operation state machine states."""
    PENDING = "pending"
    WAITING = "waiting"
    ACTING = "acting"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    RETRYING = "retrying"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class OperationContext:
    """Context for a single operation."""
    step_id: int
    action_type: str
    action_params: dict[str, Any]
    target_element: str | None = None
    state: OperationState = OperationState.PENDING
    retry_count: int = 0
    max_retries: int = 3
    error: str | None = None


class ExecutionLoop:
    """Main execution loop with explicit state machine.

    Separates task-level flow from single-page operation logic.
    """

    MAX_RETRIES_PER_STEP = 3
    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(
        self,
        state_store: StateStore,
        context_manager: ContextManager,
        tool_registry: ToolRegistry,
        lifecycle_hooks: LifecycleHooks,
        trajectory_recorder: TrajectoryRecorder,
    ):
        self.state_store = state_store
        self.context_manager = context_manager
        self.tool_registry = tool_registry
        self.lifecycle_hooks = lifecycle_hooks
        self.trajectory_recorder = trajectory_recorder

        self._task_state = TaskFlowState.INITIALIZING
        self._operation_state = OperationState.PENDING
        self._current_operation: OperationContext | None = None
        self._consecutive_failures = 0
        self._page: "Page | None" = None

    def set_page(self, page: "Page") -> None:
        """Set the browser page."""
        self._page = page
        self.tool_registry.set_page(page)
        self.lifecycle_hooks.set_page(page)

    @property
    def page(self) -> "Page":
        if self._page is None:
            raise RuntimeError("Page not set")
        return self._page

    async def execute_operation(self, operation: OperationContext) -> ToolResult:
        """Execute a single operation through its state machine.

        This is the inner loop for single-page operations.
        """
        self._current_operation = operation
        self._operation_state = OperationState.PENDING

        while True:
            if self._operation_state == OperationState.PENDING:
                self._operation_state = OperationState.WAITING
                await self.lifecycle_hooks.check_and_handle_popups()

            elif self._operation_state == OperationState.WAITING:
                try:
                    await self.lifecycle_hooks.wait_for_page_ready(timeout=10000)
                    self._operation_state = OperationState.ACTING
                except Exception as e:
                    operation.error = f"Page not ready: {e}"
                    self._operation_state = OperationState.RETRYING

            elif self._operation_state == OperationState.ACTING:
                url_before = self.page.url
                result = await self.tool_registry.execute(
                    operation.action_type,
                    **operation.action_params
                )

                if result.success:
                    self._operation_state = OperationState.VERIFYING
                    operation.error = None
                else:
                    operation.error = result.error
                    self._operation_state = OperationState.RETRYING

                self.trajectory_recorder.record(
                    url=url_before,
                    action_type=operation.action_type,
                    action_params=operation.action_params,
                    target_element=operation.target_element,
                    result=result.data if result.data else {},
                    success=result.success,
                    error=result.error,
                    screenshot_path=result.screenshot_path,
                )

            elif self._operation_state == OperationState.VERIFYING:
                await asyncio.sleep(0.3)
                await self.lifecycle_hooks.check_and_handle_popups()
                self._operation_state = OperationState.SUCCEEDED
                self._consecutive_failures = 0
                return ToolResult(success=True, data=result.data if 'result' in dir() else None)

            elif self._operation_state == OperationState.RETRYING:
                operation.retry_count += 1
                if operation.retry_count > operation.max_retries:
                    self._operation_state = OperationState.FAILED
                else:
                    screenshot_path = await self.tool_registry.take_error_screenshot(
                        f"retry_{operation.retry_count}"
                    )
                    if screenshot_path:
                        self.state_store.add_screenshot(screenshot_path)

                    await asyncio.sleep(1.0 * operation.retry_count)
                    self._operation_state = OperationState.WAITING

            elif self._operation_state == OperationState.FAILED:
                self._consecutive_failures += 1
                screenshot_path = await self.tool_registry.take_error_screenshot("failed")
                if screenshot_path:
                    self.state_store.add_screenshot(screenshot_path)

                return ToolResult(
                    success=False,
                    error=operation.error,
                    screenshot_path=screenshot_path,
                )

            elif self._operation_state == OperationState.SUCCEEDED:
                return ToolResult(success=True)

            elif self._operation_state == OperationState.SKIPPED:
                return ToolResult(success=True, data={"skipped": True})

    def reset_operation_state(self) -> None:
        """Reset operation state for a new operation.

        Called when task-level flow advances to maintain proper state separation.
        """
        self._operation_state = OperationState.PENDING
        self._current_operation = None

    def should_abort(self) -> bool:
        """Check if execution should abort due to too many failures."""
        return self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES

    def get_task_state(self) -> TaskFlowState:
        """Get current task-level state."""
        return self._task_state

    def set_task_state(self, state: TaskFlowState) -> None:
        """Set task-level state."""
        self._task_state = state


class BrowserAgent:
    """High-level browser agent that uses LLM for task planning and execution."""

    SYSTEM_PROMPT = """You are a browser automation agent. Given a task description and the current page context, decide what action to take next.

You have access to these tools:
{tools}

IMPORTANT RULES:
1. Always wait for elements to be ready before interacting
2. Use semantic selectors when possible (aria-label, text content, placeholder)
3. Take screenshots at key moments
4. Extract and accumulate data as you find it
5. Handle popups and dialogs gracefully - they should not block your progress
6. If an action fails, try alternative approaches before giving up

Respond with a JSON object:
{{
    "reasoning": "Brief explanation of your decision",
    "action": "tool_name",
    "params": {{}},
    "is_complete": false,
    "extracted_data": {{}}
}}

Set is_complete to true when the task is finished.
Put any extracted data in extracted_data to accumulate results."""

    def __init__(
        self,
        output_dir: str,
        max_steps: int = 50,
        model_name: str | None = None,
    ):
        self.output_dir = output_dir
        self.max_steps = max_steps
        self.model_name = model_name or os.getenv("MODEL_NAME", "gpt-4o")

        self.state_store = StateStore(output_dir)
        self.context_manager = ContextManager()
        self.tool_registry = ToolRegistry(output_dir)
        self.lifecycle_hooks = LifecycleHooks(output_dir)
        self.trajectory_recorder = TrajectoryRecorder(output_dir)

        self.execution_loop = ExecutionLoop(
            self.state_store,
            self.context_manager,
            self.tool_registry,
            self.lifecycle_hooks,
            self.trajectory_recorder,
        )

        self._llm_client: AsyncOpenAI | None = None
        self._browser: "Browser | None" = None
        self._browser_context: "BrowserContext | None" = None
        self._page: "Page | None" = None

    async def initialize(
        self,
        target_url: str,
        task_description: str,
        credentials: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the browser agent."""
        from playwright.async_api import async_playwright

        task_id = str(uuid.uuid4())[:8]
        task_state, resumed = self.state_store.load_or_create(
            task_id=task_id,
            target_url=target_url,
            task_description=task_description,
            max_steps=self.max_steps,
        )

        self.trajectory_recorder.record_task_event(
            url=target_url,
            event_type="start" if not resumed else "resume",
            details={
                "task_id": task_id,
                "task_description": task_description,
                "resumed": resumed,
                "resume_step": self.state_store.get_resume_point() if resumed else 0,
            },
        )

        self._llm_client = AsyncOpenAI(
            base_url=os.getenv("OPENAI_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )

        playwright = await async_playwright().start()
        self._browser = await playwright.chromium.launch(headless=True)
        self._browser_context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )

        if credentials:
            await self._browser_context.add_cookies([
                {"name": k, "value": v, "url": target_url}
                for k, v in credentials.items()
                if isinstance(v, str)
            ])

        self._page = await self._browser_context.new_page()
        self.execution_loop.set_page(self._page)

    async def run(
        self,
        target_url: str,
        task_description: str,
        credentials: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the browser agent to complete a task."""
        try:
            await self.initialize(target_url, task_description, credentials)

            self.execution_loop.set_task_state(TaskFlowState.INITIALIZING)

            operation = OperationContext(
                step_id=0,
                action_type="navigate",
                action_params={"url": target_url},
            )
            result = await self.execution_loop.execute_operation(operation)

            if not result.success:
                self.state_store.set_task_status("failed")
                return self.state_store.get_result()

            self.execution_loop.reset_operation_state()

            await self.lifecycle_hooks.wait_for_page_ready()
            await self.lifecycle_hooks.check_and_handle_popups()

            result_screenshot = await self.tool_registry.execute("screenshot")
            if result_screenshot.screenshot_path:
                self.state_store.add_screenshot(result_screenshot.screenshot_path)

            self.execution_loop.set_task_state(TaskFlowState.EXECUTING)

            step_count = self.state_store.get_resume_point()

            while step_count < self.max_steps:
                if self.execution_loop.should_abort():
                    self.execution_loop.set_task_state(TaskFlowState.FAILED)
                    break

                page_context = await self.context_manager.extract_context(self._page)

                llm_response = await self._get_llm_decision(
                    task_description,
                    page_context,
                    step_count,
                )

                if llm_response is None:
                    self.execution_loop.set_task_state(TaskFlowState.RECOVERING)
                    step_count += 1
                    continue

                self.trajectory_recorder.record_llm_decision(
                    url=self._page.url,
                    reasoning=llm_response.get("reasoning", ""),
                    decided_action=llm_response.get("action", ""),
                    action_params=llm_response.get("params", {}),
                    page_context_summary=page_context.to_prompt_context()[:500],
                )

                if llm_response.get("extracted_data"):
                    self.state_store.update_extracted_data(llm_response["extracted_data"])

                if llm_response.get("is_complete"):
                    self.execution_loop.set_task_state(TaskFlowState.COMPLETED)
                    break

                action = llm_response.get("action")
                params = llm_response.get("params", {})

                if not action:
                    step_count += 1
                    continue

                step = StepState(
                    step_id=step_count,
                    description=llm_response.get("reasoning", ""),
                    status=StepStatus.IN_PROGRESS,
                    action_type=action,
                    action_params=params,
                    url_before=self._page.url,
                    timestamp_start=datetime.utcnow().isoformat(),
                )
                self.state_store.add_step(step)

                self.execution_loop.reset_operation_state()

                operation = OperationContext(
                    step_id=step_count,
                    action_type=action,
                    action_params=params,
                    target_element=params.get("selector"),
                    max_retries=self.execution_loop.MAX_RETRIES_PER_STEP,
                )

                result = await self.execution_loop.execute_operation(operation)

                if result.success:
                    self.state_store.mark_step_completed(
                        step_count,
                        result=result.data if result.data else {},
                    )

                    if result.screenshot_path:
                        self.state_store.add_screenshot(result.screenshot_path)
                else:
                    self.state_store.mark_step_failed(
                        step_count,
                        error=result.error or "Unknown error",
                        recovery="retried" if operation.retry_count > 0 else "failed",
                    )

                self.context_manager.clear_cache()
                step_count += 1

                for download_path in self.lifecycle_hooks.get_downloads():
                    if download_path not in self.state_store.task_state.downloads:
                        self.state_store.add_download(download_path)

            final_screenshot = await self.tool_registry.execute("screenshot")
            if final_screenshot.screenshot_path:
                self.state_store.add_screenshot(final_screenshot.screenshot_path)

            if self.execution_loop.get_task_state() == TaskFlowState.COMPLETED:
                self.state_store.set_task_status("success")
            elif self.execution_loop.get_task_state() == TaskFlowState.FAILED:
                self.state_store.set_task_status("failed")
            else:
                has_errors = len(self.state_store.task_state.errors) > 0
                has_data = bool(self.state_store.task_state.extracted_data)
                if has_data and has_errors:
                    self.state_store.set_task_status("partial")
                elif has_data:
                    self.state_store.set_task_status("success")
                else:
                    self.state_store.set_task_status("failed")

            self.trajectory_recorder.record_task_event(
                url=self._page.url if self._page else "",
                event_type="complete",
                details={
                    "status": self.state_store.task_state.status,
                    "steps_completed": step_count,
                    "errors_count": len(self.state_store.task_state.errors),
                },
            )

            return self.state_store.get_result()

        except Exception as e:
            self.state_store.set_task_status("failed")
            self.state_store.task_state.errors.append({
                "step": -1,
                "error": str(e),
                "recovery": "failed",
            })
            return self.state_store.get_result()

        finally:
            await self.cleanup()

    async def _get_llm_decision(
        self,
        task_description: str,
        page_context: PageContext,
        step_count: int,
    ) -> dict[str, Any] | None:
        """Get next action decision from LLM."""
        tools_description = "\n".join([
            f"- {t.name}: {t.description}"
            for t in self.tool_registry.list_tools()
        ])

        system_prompt = self.SYSTEM_PROMPT.format(tools=tools_description)

        user_prompt = f"""Task: {task_description}

Current Step: {step_count + 1}/{self.max_steps}

Current Page Context:
{page_context.to_prompt_context()}

Previously extracted data: {json.dumps(self.state_store.task_state.extracted_data)}

Recent errors: {json.dumps(self.state_store.task_state.errors[-3:]) if self.state_store.task_state.errors else "None"}

What should I do next?"""

        try:
            response = await self._llm_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=1024,
            )

            content = response.choices[0].message.content
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]

            return json.loads(content.strip())

        except Exception as e:
            self.trajectory_recorder.record_error(
                url=self._page.url if self._page else "",
                action_type="llm_decision",
                action_params={},
                error=str(e),
                recovery_action="skipped",
            )
            return None

    async def cleanup(self) -> None:
        """Cleanup browser resources."""
        try:
            if self._page:
                await self._page.close()
            if self._browser_context:
                await self._browser_context.close()
            if self._browser:
                await self._browser.close()
        except Exception:
            pass

        self.state_store.save_result()
