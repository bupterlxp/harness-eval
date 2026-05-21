"""Execution Loop (E) — state-machine driven execution.

Implements the Perception-Think-Act loop as an explicit FSM with
state enum and transition function. Manages the complete lifecycle
of a browser automation task.
"""

import asyncio
import json
import os
import re
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from harness.context import ContextManager, TokenBudget
from harness.evaluation import TrajectoryRecorder, TrajectoryRecord
from harness.lifecycle import (
    LifecycleHooks,
    ErrorRecoveryManager,
    RetryManager,
    HookPhase,
)
from harness.state import StateStore, TaskState, TabInfo, StepMemory
from harness.tools import ToolRegistry, ToolResult


class FSMState(str, Enum):
    """Explicit states of the execution FSM."""

    INIT = "init"
    PLAN = "plan"
    PERCEIVE = "perceive"
    THINK = "think"
    ACT = "act"
    EVALUATE = "evaluate"
    CHECKPOINT = "checkpoint"
    RECOVER = "recover"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"


# Transition table: (current_state, condition) -> next_state
TRANSITIONS: dict[tuple[FSMState, str], FSMState] = {
    (FSMState.INIT, "success"): FSMState.PLAN,
    (FSMState.INIT, "resume"): FSMState.PERCEIVE,
    (FSMState.INIT, "failure"): FSMState.FAILED,
    (FSMState.PLAN, "success"): FSMState.PERCEIVE,
    (FSMState.PLAN, "failure"): FSMState.PERCEIVE,  # Continue without plan
    (FSMState.PERCEIVE, "success"): FSMState.THINK,
    (FSMState.PERCEIVE, "failure"): FSMState.RECOVER,
    (FSMState.PERCEIVE, "timeout"): FSMState.TIMEOUT,
    (FSMState.PERCEIVE, "budget_exceeded"): FSMState.DONE,
    (FSMState.THINK, "success"): FSMState.ACT,
    (FSMState.THINK, "done"): FSMState.DONE,
    (FSMState.THINK, "failure"): FSMState.RECOVER,
    (FSMState.THINK, "timeout"): FSMState.TIMEOUT,
    (FSMState.ACT, "success"): FSMState.EVALUATE,
    (FSMState.ACT, "failure"): FSMState.EVALUATE,
    (FSMState.ACT, "done"): FSMState.DONE,
    (FSMState.ACT, "timeout"): FSMState.TIMEOUT,
    (FSMState.EVALUATE, "continue"): FSMState.PERCEIVE,
    (FSMState.EVALUATE, "checkpoint"): FSMState.CHECKPOINT,
    (FSMState.EVALUATE, "done"): FSMState.DONE,
    (FSMState.EVALUATE, "stagnation_critical"): FSMState.RECOVER,
    (FSMState.CHECKPOINT, "success"): FSMState.PERCEIVE,
    (FSMState.CHECKPOINT, "failure"): FSMState.PERCEIVE,  # Non-fatal
    (FSMState.RECOVER, "success"): FSMState.PERCEIVE,
    (FSMState.RECOVER, "failure"): FSMState.FAILED,
    (FSMState.RECOVER, "max_retries"): FSMState.FAILED,
}


def transition(current: FSMState, condition: str) -> FSMState:
    """Compute next state from current state and condition."""
    key = (current, condition)
    if key in TRANSITIONS:
        return TRANSITIONS[key]
    # Default: if condition is a terminal state name, go there
    if condition in ("done", "failed", "timeout"):
        return FSMState(condition)
    # Fallback: stay in current state
    return current


@dataclass
class ExecutionConfig:
    """Configuration for the execution engine."""

    task_prompt: str
    output_dir: Path
    max_steps: int = 50
    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    timeout_seconds: int = 300
    checkpoint_interval: int = 5
    resume_from: Path | None = None
    model_name: str = ""
    base_url: str = ""
    api_key: str = ""

    def __post_init__(self) -> None:
        self.model_name = self.model_name or os.environ.get("MODEL_NAME", "gpt-4o")
        self.base_url = self.base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.api_key = self.api_key or os.environ.get("OPENAI_API_KEY", "")


class ExecutionEngine:
    """Main execution engine — drives the FSM loop."""

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self.state_store = StateStore(config.output_dir)
        self.context_manager = ContextManager()
        self.tool_registry = ToolRegistry()
        self.lifecycle = LifecycleHooks()
        self.recovery = ErrorRecoveryManager()
        self.retry_manager = RetryManager(max_retries=3)
        self.recorder = TrajectoryRecorder(config.output_dir)
        self.llm_client: AsyncOpenAI | None = None
        self.browser: Browser | None = None
        self.browser_context: BrowserContext | None = None
        self._fsm_state: FSMState = FSMState.INIT
        self._current_observation: str = ""
        self._current_warnings: list[str] = []
        self._llm_response: dict[str, Any] = {}
        self._action_result: ToolResult | None = None
        self._recovery_attempts: int = 0
        self._max_recovery_attempts: int = 3
        self._start_time: float = 0

    async def run(self) -> dict[str, Any]:
        """Execute the full task. Returns result dict."""
        self._start_time = time.time()
        result: dict[str, Any] = {"status": "failed", "trajectory": "", "error": ""}

        try:
            # Main FSM loop
            while self._fsm_state not in (FSMState.DONE, FSMState.FAILED, FSMState.TIMEOUT):
                # Check overall timeout
                elapsed = time.time() - self._start_time
                if elapsed > self.config.timeout_seconds:
                    self._fsm_state = FSMState.TIMEOUT
                    break

                # Execute current state
                condition = await self._execute_state()

                # Transition
                next_state = transition(self._fsm_state, condition)
                if next_state != self._fsm_state:
                    self._fsm_state = next_state

            # Determine final result
            result = await self._finalize()

        except Exception as e:
            result = {
                "status": "failed",
                "trajectory": str(self.recorder.trajectory_path),
                "error": f"Unhandled exception: {str(e)}\n{traceback.format_exc()}",
            }
        finally:
            await self._cleanup()

        return result

    async def _execute_state(self) -> str:
        """Execute the current FSM state and return transition condition."""
        handlers = {
            FSMState.INIT: self._state_init,
            FSMState.PLAN: self._state_plan,
            FSMState.PERCEIVE: self._state_perceive,
            FSMState.THINK: self._state_think,
            FSMState.ACT: self._state_act,
            FSMState.EVALUATE: self._state_evaluate,
            FSMState.CHECKPOINT: self._state_checkpoint,
            FSMState.RECOVER: self._state_recover,
        }
        handler = handlers.get(self._fsm_state)
        if handler is None:
            return "failure"
        return await handler()

    async def _state_init(self) -> str:
        """Initialize browser, LLM client, and state."""
        try:
            # Init LLM client
            self.llm_client = AsyncOpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
            )

            # Init browser
            pw = await async_playwright().start()
            self.browser = await pw.chromium.launch(headless=self.config.headless)
            self.browser_context = await self.browser.new_context(
                viewport={
                    "width": self.config.viewport_width,
                    "height": self.config.viewport_height,
                }
            )

            # Handle new page/popup detection
            self.browser_context.on("page", self._on_new_page)

            page = await self.browser_context.new_page()
            self.tool_registry.set_browser_context(self.browser_context, page)

            # Init state
            if self.config.resume_from:
                self.state_store.load_checkpoint(self.config.resume_from)
                print(f"Resumed from checkpoint at step {self.state_store.state.step_number}")
                self.recorder.start()
                await self.lifecycle.fire_startup(self.state_store.state)
                return "resume"
            else:
                self.state_store.init_state(self.config.task_prompt)
                self.recorder.start()
                await self.lifecycle.fire_startup(self.state_store.state)
                return "success"

        except Exception as e:
            print(f"Initialization failed: {e}")
            return "failure"

    async def _state_plan(self) -> str:
        """Generate task plan via LLM."""
        try:
            planning_messages = self.context_manager.build_planning_prompt(
                self.config.task_prompt
            )

            response = await self.retry_manager.execute_with_retry(
                self._call_llm, planning_messages
            )

            # Parse plan from response
            content = response.choices[0].message.content or ""
            sub_goals = self._parse_plan(content)

            if sub_goals:
                self.state_store.set_plan(sub_goals)
                print(f"Plan created with {len(sub_goals)} sub-goals")
            else:
                # Create a simple default plan
                self.state_store.set_plan([
                    "Understand and analyze the task",
                    "Execute the main task actions",
                    "Verify and report results",
                ])
                print("Using default plan (could not parse LLM plan)")

            return "success"

        except Exception as e:
            print(f"Planning failed: {e}. Continuing without plan.")
            self.state_store.set_plan(["Complete the task as described"])
            return "failure"

    async def _state_perceive(self) -> str:
        """Perceive current page state — build accessibility tree."""
        try:
            task_state = self.state_store.state

            # Check budget
            if task_state.step_number >= self.config.max_steps:
                return "budget_exceeded"

            # Check timeout
            elapsed = time.time() - self._start_time
            if elapsed > self.config.timeout_seconds:
                return "timeout"

            # Update tab info
            tabs = await self.tool_registry.get_tab_list()
            tab_infos = [
                TabInfo(
                    tab_id=t["tab_id"],
                    url=t["url"],
                    title=t["title"],
                    is_active=t["is_active"],
                )
                for t in tabs
            ]
            self.state_store.update_tabs(tab_infos)

            # Update current URL
            page = self.tool_registry.page
            self.state_store.update_url(page.url)

            # Build element index map for action resolution
            await self.tool_registry.build_element_index_map()

            # Build accessibility tree
            a11y_tree = await self.tool_registry.get_accessibility_tree()

            # Get page fingerprint for stagnation detection
            fingerprint = await self.tool_registry.get_page_fingerprint()
            if fingerprint:
                stagnation_count = task_state.stagnation.record_page_fingerprint(fingerprint)
                if stagnation_count >= 5:
                    self._current_warnings.append(
                        "Page has not changed in 5 steps. Try a different approach."
                    )

            # Auto-detect and dismiss popups
            popup_result = await self.tool_registry.handle_popup_detection()
            if popup_result and popup_result.success:
                await self.lifecycle.fire_popup(popup_result.data)

            # Build observation
            self._current_warnings = self._get_contextual_warnings(task_state)
            self._current_observation = self.context_manager.build_observation(
                task_state=task_state,
                accessibility_tree=a11y_tree,
                max_steps=self.config.max_steps,
                warnings=self._current_warnings,
            )

            # Fire pre-step hook
            await self.lifecycle.fire_pre_step(task_state, task_state.step_number)

            return "success"

        except Exception as e:
            print(f"Perception failed: {e}")
            return "failure"

    async def _state_think(self) -> str:
        """Call LLM to decide next action."""
        try:
            task_state = self.state_store.state

            # Build messages
            system_prompt = self.context_manager.build_system_prompt(
                task_state, self.config.max_steps
            )
            messages = self.context_manager.build_messages(
                system_prompt=system_prompt,
                observation=self._current_observation,
                task_state=task_state,
                max_steps=self.config.max_steps,
            )

            # Call LLM with tool schemas
            tool_schemas = self.tool_registry.get_tool_schemas()

            # On final step, only allow "done"
            if task_state.step_number >= self.config.max_steps - 1:
                tool_schemas = [t for t in tool_schemas if t["function"]["name"] == "done"]

            response = await self.retry_manager.execute_with_retry(
                self._call_llm_with_tools, messages, tool_schemas
            )

            # Parse response
            message = response.choices[0].message
            self._llm_response = {
                "raw_content": message.content or "",
                "tool_calls": [],
                "token_usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                },
            }

            if message.tool_calls:
                for tc in message.tool_calls:
                    self._llm_response["tool_calls"].append({
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    })

            # Determine action
            if message.tool_calls:
                action = self._llm_response["tool_calls"][0]
                if action["name"] == "done":
                    # Store done result
                    self._action_result = ToolResult(
                        success=True,
                        data=action["arguments"],
                    )
                    return "done"
                return "success"
            else:
                # Try to parse action from content
                parsed = self._parse_action_from_content(message.content or "")
                if parsed:
                    self._llm_response["tool_calls"] = [parsed]
                    if parsed["name"] == "done":
                        self._action_result = ToolResult(
                            success=True, data=parsed["arguments"]
                        )
                        return "done"
                    return "success"
                else:
                    # No action parsed — treat as thinking, retry
                    self.context_manager.add_to_history(
                        "assistant", message.content or ""
                    )
                    return "failure"

        except Exception as e:
            print(f"Think failed: {e}")
            return "failure"

    async def _state_act(self) -> str:
        """Execute the decided action."""
        try:
            task_state = self.state_store.state

            if not self._llm_response.get("tool_calls"):
                return "failure"

            action = self._llm_response["tool_calls"][0]
            action_type = action["name"]
            action_params = action["arguments"]

            # Fire pre-action hook
            pre_ctx = await self.lifecycle.fire_pre_action(action_type, action_params)
            action_params = pre_ctx.get("params", action_params)

            # Track action for stagnation detection
            rep_count = task_state.stagnation.record_action(action_type, action_params)
            warning = task_state.stagnation.get_repetition_warning(rep_count)
            if warning:
                self._current_warnings.append(warning)

            # If critical stagnation (12+), force strategy change
            if rep_count >= 12:
                self._action_result = ToolResult(
                    success=False,
                    error="Action repeated 12+ times. Forced strategy change required.",
                )
                return "failure"

            # Execute action
            start_time = time.time()

            if action_type == "done":
                self._action_result = ToolResult(
                    success=True, data=action_params
                )
                return "done"

            self._action_result = await self.tool_registry.dispatch(
                action_type, action_params
            )
            duration_ms = (time.time() - start_time) * 1000

            # Fire post-action hook
            await self.lifecycle.fire_post_action(
                action_type,
                action_params,
                {"success": self._action_result.success, "data": self._action_result.data},
            )

            # Update failure tracking
            if self._action_result.success:
                task_state.stagnation.reset_failures()
                self.recovery.reset()
            else:
                element_id = str(action_params.get("index", ""))
                task_state.stagnation.record_failure(element_id)

            # Add to context history
            result_summary = (
                f"Action {action_type}: {'OK' if self._action_result.success else 'FAILED'}"
            )
            if self._action_result.error:
                result_summary += f" - {self._action_result.error[:100]}"
            self.context_manager.add_to_history("assistant", json.dumps({
                "action": action_type,
                "params": action_params,
            }))
            self.context_manager.add_to_history("user", result_summary)

            return "success" if self._action_result.success else "failure"

        except Exception as e:
            self._action_result = ToolResult(success=False, error=str(e))
            print(f"Action execution error: {e}")
            return "failure"

    async def _state_evaluate(self) -> str:
        """Evaluate step outcome, record trajectory, update memory."""
        task_state = self.state_store.state

        # Increment step
        step = self.state_store.increment_step()

        # Get current page info
        page = self.tool_registry.page
        url_after = page.url
        try:
            title = await page.title()
        except Exception:
            title = ""

        # Determine action info for recording
        action_type = "unknown"
        action_params: dict[str, Any] = {}
        if self._llm_response.get("tool_calls"):
            action = self._llm_response["tool_calls"][0]
            action_type = action["name"]
            action_params = action["arguments"]

        # Record trajectory
        record = TrajectoryRecord(
            step=step,
            timestamp=time.time(),
            action_type=action_type,
            action_params=action_params,
            observation=self._current_observation[:2000],
            result=self._action_result.data if self._action_result else {},
            success=self._action_result.success if self._action_result else False,
            url_before=task_state.current_url,
            url_after=url_after,
            page_title=title,
            plan_state=task_state.plan.to_dict(),
            memory_summary=task_state.rolling_summary[:500],
            warnings=self._current_warnings,
            llm_response_raw=self._llm_response.get("raw_content", "")[:500],
            token_usage=self._llm_response.get("token_usage", {}),
            duration_ms=0,
            error=self._action_result.error if self._action_result else "",
        )
        self.recorder.record(record)

        # Update step memory
        success = self._action_result.success if self._action_result else False
        current_goal = task_state.plan.current_goal()
        memory = StepMemory(
            step_number=step,
            previous_action_success=success,
            memory_summary=f"Step {step}: {action_type} -> {'OK' if success else 'FAIL'}",
            next_goal=current_goal.description if current_goal else "Complete task",
        )
        self.state_store.add_step_memory(memory)

        # Handle extracted data from action
        if self._action_result and self._action_result.data.get("content"):
            self.state_store.add_extracted_data({
                "step": step,
                "type": action_type,
                "content": self._action_result.data["content"],
            })

        # Update URL
        self.state_store.update_url(url_after)

        # Fire post-step hook
        await self.lifecycle.fire_post_step(
            task_state, step, {"action": action_type, "success": success}
        )

        # Check if done action was executed
        if action_type == "done":
            return "done"

        # Check stagnation
        if self._current_warnings:
            for w in self._current_warnings:
                if "12+" in w or "CRITICAL" in w:
                    return "stagnation_critical"

        # Check if checkpoint needed
        if step % self.config.checkpoint_interval == 0:
            return "checkpoint"

        # Update rolling summary periodically
        if step % 5 == 0:
            await self._update_rolling_summary()

        return "continue"

    async def _state_checkpoint(self) -> str:
        """Save state checkpoint."""
        try:
            path = self.state_store.save_checkpoint()
            await self.lifecycle.fire_checkpoint(self.state_store.state, str(path))
            print(f"  [Checkpoint] Saved at step {self.state_store.state.step_number}")
            return "success"
        except Exception as e:
            print(f"  [Checkpoint] Failed: {e}")
            return "failure"

    async def _state_recover(self) -> str:
        """Attempt recovery from failure."""
        self._recovery_attempts += 1

        if self._recovery_attempts > self._max_recovery_attempts:
            return "max_retries"

        task_state = self.state_store.state

        # Get recovery instruction
        instruction = self.recovery.get_recovery_instruction(
            task_state.stagnation.consecutive_failures,
            max(task_state.stagnation.same_element_failures.values(), default=0),
        )

        # Add recovery instruction to warnings for next perception
        self._current_warnings.append(f"RECOVERY: {instruction}")

        # Fire recovery hooks
        await self.lifecycle.fire_failure(
            self._action_result.error if self._action_result else "Unknown failure",
            task_state,
            task_state.step_number,
        )

        # Try to re-stabilize the page
        try:
            page = self.tool_registry.page
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        return "success"

    async def _finalize(self) -> dict[str, Any]:
        """Finalize execution and produce result."""
        task_state = self.state_store.state
        stats = self.recorder.finish()

        # Determine status
        if self._fsm_state == FSMState.DONE:
            # Check if done action had a result
            done_data = {}
            if self._action_result and self._action_result.data:
                done_data = self._action_result.data
            status = "success"
            if not done_data.get("result") and not task_state.extracted_data:
                status = "partial"
            task_state.status = status
        elif self._fsm_state == FSMState.TIMEOUT:
            status = "partial" if task_state.extracted_data else "failed"
            task_state.status = status
            task_state.error_message = "Execution timed out"
        else:
            status = "failed"
            task_state.status = status

        # Save final checkpoint
        try:
            self.state_store.save_checkpoint()
        except Exception:
            pass

        result = {
            "status": status,
            "trajectory": str(self.recorder.trajectory_path),
            "steps_taken": task_state.step_number,
            "extracted_data": task_state.extracted_data,
            "plan_progress": task_state.plan.progress_str(),
            "rolling_summary": task_state.rolling_summary,
            "error": task_state.error_message,
            "stats": stats.to_dict(),
        }

        # Add done result if available
        if self._action_result and self._action_result.data.get("result"):
            result["agent_result"] = self._action_result.data["result"]
            if self._action_result.data.get("extracted_data"):
                result["extracted_data_final"] = self._action_result.data["extracted_data"]

        # Fire shutdown hooks
        await self.lifecycle.fire_shutdown(task_state, result)

        return result

    async def _cleanup(self) -> None:
        """Clean up browser and resources."""
        try:
            if self.browser_context:
                await self.browser_context.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass

    async def _call_llm(self, messages: list[dict[str, Any]]) -> Any:
        """Call LLM without tools."""
        if not self.llm_client:
            raise RuntimeError("LLM client not initialized")
        return await self.llm_client.chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=1000,
        )

    async def _call_llm_with_tools(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any:
        """Call LLM with tool/function calling."""
        if not self.llm_client:
            raise RuntimeError("LLM client not initialized")
        return await self.llm_client.chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="required" if tools else None,
            temperature=0.1,
            max_tokens=1500,
        )

    def _parse_plan(self, content: str) -> list[str]:
        """Parse plan sub-goals from LLM response."""
        # Try JSON array first
        try:
            # Find JSON array in content
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if match:
                goals = json.loads(match.group())
                if isinstance(goals, list) and all(isinstance(g, str) for g in goals):
                    return goals[:10]
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: parse numbered/bulleted list
        lines = content.strip().split("\n")
        goals = []
        for line in lines:
            line = line.strip()
            # Match "1. ...", "- ...", "* ..."
            match = re.match(r"^(?:\d+[\.\)]\s*|[-*]\s*)(.+)", line)
            if match:
                goal = match.group(1).strip().strip('"')
                if goal:
                    goals.append(goal)

        return goals[:10] if goals else []

    def _parse_action_from_content(self, content: str) -> dict[str, Any] | None:
        """Try to parse an action from free-text LLM response."""
        # Try to find JSON in content
        try:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if "action" in data:
                    return {
                        "name": data["action"],
                        "arguments": {k: v for k, v in data.items() if k != "action"},
                    }
                if "name" in data:
                    return {
                        "name": data["name"],
                        "arguments": data.get("arguments", data.get("params", {})),
                    }
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _get_contextual_warnings(self, task_state: TaskState) -> list[str]:
        """Generate contextual warnings based on current state."""
        warnings: list[str] = []
        budget_frac = task_state.budget_fraction(self.config.max_steps)

        if budget_frac >= 0.75:
            warnings.append(
                f"Budget at {int(budget_frac * 100)}%! Save any partial results soon."
            )

        # Check consecutive failures
        if task_state.stagnation.consecutive_failures >= 2:
            instruction = self.recovery.get_recovery_instruction(
                task_state.stagnation.consecutive_failures,
                max(task_state.stagnation.same_element_failures.values(), default=0),
            )
            warnings.append(instruction)

        return warnings

    async def _update_rolling_summary(self) -> None:
        """Update the rolling summary via LLM."""
        task_state = self.state_store.state
        recent_memories = task_state.step_memories[-5:]
        recent_actions = [m.memory_summary for m in recent_memories]

        if not recent_actions:
            return

        try:
            messages = self.context_manager.build_summary_prompt(
                task_state.rolling_summary, recent_actions
            )
            response = await self._call_llm(messages)
            summary = response.choices[0].message.content or ""
            self.state_store.update_rolling_summary(summary.strip())
        except Exception:
            # Non-critical failure
            pass

    def _on_new_page(self, page: Page) -> None:
        """Handle new page/tab detection."""
        # This is called synchronously by playwright event system
        # Update will be picked up in next perceive step
        pass
