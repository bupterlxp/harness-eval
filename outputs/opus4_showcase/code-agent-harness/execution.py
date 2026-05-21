"""Execution Loop — state-machine driven ReAct agent execution.

Implements an explicit FSM with state enum + transition function.
States: IDLE -> RUNNING -> FINISHED | STUCK | ERROR
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from openai import OpenAI

from harness.context import ContextManager
from harness.evaluation import TrajectoryRecorder
from harness.lifecycle import HookEvent, LifecycleManager
from harness.state import AgentPhase, AgentState, ResultStatus, StateStore, StepRecord
from harness.tools import ToolRegistry, ToolResult


# ─── FSM States ─────────────────────────────────────────────────────────────

class FSMState(str, Enum):
    """Explicit states for the execution FSM."""

    IDLE = "idle"
    THINKING = "thinking"          # Waiting for LLM response
    ACTING = "acting"              # Executing a tool
    OBSERVING = "observing"        # Processing tool result
    BUDGET_CHECK = "budget_check"  # Checking step/token budget
    RECOVERING = "recovering"      # Handling errors
    FINISHED = "finished"          # Task complete (success)
    STUCK = "stuck"                # Doom loop / cannot proceed
    ERROR = "error"                # Unrecoverable error


# ─── FSM Transition Table ───────────────────────────────────────────────────

# (current_state, event) -> next_state
TRANSITIONS: dict[tuple[FSMState, str], FSMState] = {
    (FSMState.IDLE, "start"): FSMState.BUDGET_CHECK,
    (FSMState.BUDGET_CHECK, "budget_ok"): FSMState.THINKING,
    (FSMState.BUDGET_CHECK, "budget_exhausted"): FSMState.FINISHED,
    (FSMState.BUDGET_CHECK, "doom_loop"): FSMState.STUCK,
    (FSMState.THINKING, "got_action"): FSMState.ACTING,
    (FSMState.THINKING, "got_done"): FSMState.FINISHED,
    (FSMState.THINKING, "parse_error"): FSMState.RECOVERING,
    (FSMState.THINKING, "llm_error"): FSMState.RECOVERING,
    (FSMState.ACTING, "tool_success"): FSMState.OBSERVING,
    (FSMState.ACTING, "tool_error"): FSMState.OBSERVING,
    (FSMState.OBSERVING, "continue"): FSMState.BUDGET_CHECK,
    (FSMState.RECOVERING, "retry"): FSMState.THINKING,
    (FSMState.RECOVERING, "max_retries"): FSMState.ERROR,
    (FSMState.RECOVERING, "fatal"): FSMState.ERROR,
}


def transition(current: FSMState, event: str) -> FSMState:
    """Look up the next state from the transition table."""
    key = (current, event)
    if key not in TRANSITIONS:
        raise ValueError(f"Invalid transition: ({current.value}, {event})")
    return TRANSITIONS[key]


# ─── Result ─────────────────────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    """Result of the agent execution."""

    status: ResultStatus
    message: str = ""
    steps_taken: int = 0


# ─── System Prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an autonomous code agent. You solve software engineering tasks by reading, understanding, modifying, and testing code.

## How to Respond

You must respond with a Thought and then an Action. Format:

Thought: <your reasoning about what to do next>

Action: <tool_name>
Action Input: <JSON object with tool parameters>

When you have completed the task successfully, use the `done` tool.

## Guidelines

1. Start by understanding the task and exploring the codebase structure.
2. Read relevant files to understand the code before making changes.
3. Make targeted edits using str_replace (requires exact string match).
4. Always read a file before editing it to get the exact current content.
5. Run tests after making changes to verify correctness.
6. If tests fail, analyze the error and fix iteratively.
7. Use the `done` tool when the task is complete.

## Important Rules

- NEVER guess file contents. Always read first.
- str_replace requires the old_string to be UNIQUE in the file.
- If you get a "not unique" error, include more surrounding context.
- If you're stuck in a loop, try a completely different approach.
- Focus on solving the specific task, don't refactor unrelated code.
"""


# ─── Execution Engine ───────────────────────────────────────────────────────

class ExecutionEngine:
    """State-machine driven execution engine for the code agent."""

    def __init__(
        self,
        prompt: str,
        workspace: Path,
        model_name: str,
        base_url: str,
        api_key: str,
        max_steps: int,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        state_store: StateStore,
        lifecycle: LifecycleManager,
        recorder: TrajectoryRecorder,
    ) -> None:
        self.prompt = prompt
        self.workspace = workspace
        self.model_name = model_name
        self.max_steps = max_steps
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.state_store = state_store
        self.lifecycle = lifecycle
        self.recorder = recorder

        # OpenAI client
        self.client = OpenAI(base_url=base_url, api_key=api_key)

        # FSM state
        self._fsm_state = FSMState.IDLE
        self._current_step = 0
        self._parse_retries = 0
        self._max_parse_retries = 3
        self._last_parse_error = ""

        # Initialize agent state
        self.state_store.state.prompt = prompt
        self.state_store.state.workspace = str(workspace)
        self.state_store.state.max_steps = max_steps

    def run(self) -> ExecutionResult:
        """Run the agent execution loop driven by the FSM."""
        self.lifecycle.trigger(HookEvent.RUN_START)

        # Generate repo map for context
        self.context_manager.generate_repo_map(self.workspace)

        # Initialize state
        self.state_store.state.phase = AgentPhase.RUNNING
        self._fsm_state = transition(FSMState.IDLE, "start")

        result = self._run_loop()

        # Write trajectory summary
        self.recorder.write_summary(
            status=result.status.value,
            files_modified=self.state_store.state.files_modified,
            final_message=result.message,
        )
        self.recorder.close()

        # Save final checkpoint
        self.state_store.save_checkpoint("final")
        self.lifecycle.trigger(HookEvent.RUN_END, data={"status": result.status.value})

        return result

    def restore_from_checkpoint(self, path: Path) -> None:
        """Restore engine state from a checkpoint."""
        state = self.state_store.load_checkpoint(path)
        self._current_step = state.current_step
        self.lifecycle.trigger(HookEvent.CHECKPOINT_RESTORED)

    def _run_loop(self) -> ExecutionResult:
        """The main FSM loop."""
        while self._fsm_state not in (FSMState.FINISHED, FSMState.STUCK, FSMState.ERROR):
            if self._fsm_state == FSMState.BUDGET_CHECK:
                event = self._check_budget()
                self._fsm_state = transition(FSMState.BUDGET_CHECK, event)

            elif self._fsm_state == FSMState.THINKING:
                event = self._think()
                self._fsm_state = transition(FSMState.THINKING, event)

            elif self._fsm_state == FSMState.ACTING:
                event = self._act()
                self._fsm_state = transition(FSMState.ACTING, event)

            elif self._fsm_state == FSMState.OBSERVING:
                event = self._observe()
                self._fsm_state = transition(FSMState.OBSERVING, event)

            elif self._fsm_state == FSMState.RECOVERING:
                event = self._recover()
                self._fsm_state = transition(FSMState.RECOVERING, event)

        # Determine final result
        return self._finalize()

    def _check_budget(self) -> str:
        """Check step budget and doom loop detection."""
        self._current_step += 1
        self.lifecycle.trigger(HookEvent.STEP_START, step_number=self._current_step)

        # Budget exhaustion
        if self._current_step > self.max_steps:
            self.state_store.state.error_message = "Step budget exhausted"
            return "budget_exhausted"

        # Doom loop detection
        doom = self.state_store.detect_doom_loop()
        if doom:
            # First doom detection triggers a strategy switch prompt (not immediate STUCK)
            if "force_stuck" in self.state_store.state.metadata:
                self.state_store.state.error_message = doom
                self.lifecycle.trigger(HookEvent.DOOM_LOOP, step_number=self._current_step, reason=doom)
                return "doom_loop"
            else:
                # Mark for next time; inject warning into context
                self.state_store.state.metadata["doom_warning"] = doom
                self.state_store.state.metadata["doom_count"] = self.state_store.state.metadata.get("doom_count", 0) + 1
                if self.state_store.state.metadata["doom_count"] >= 2:
                    self.state_store.state.metadata["force_stuck"] = True
                self.lifecycle.trigger(HookEvent.DOOM_LOOP, step_number=self._current_step, reason=doom)

        # Budget warning at 75%
        if self._current_step >= int(self.max_steps * 0.75):
            self.lifecycle.trigger(HookEvent.BUDGET_WARNING, step_number=self._current_step)

        return "budget_ok"

    def _think(self) -> str:
        """Call the LLM to get the next action."""
        self.lifecycle.trigger(HookEvent.PRE_LLM_CALL, step_number=self._current_step)

        # Build budget warning
        budget_warning = ""
        if self._current_step >= int(self.max_steps * 0.75):
            remaining = self.max_steps - self._current_step
            budget_warning = f"You have used {self._current_step}/{self.max_steps} steps. Only {remaining} steps remaining. Prioritize completing the task."

        # Build doom loop warning
        doom_warning = self.state_store.state.metadata.get("doom_warning", "")

        # Build messages
        messages = self.context_manager.build_messages(
            system_prompt=SYSTEM_PROMPT,
            task_prompt=self.prompt,
            history=self.state_store.state.history,
            budget_warning=budget_warning,
            doom_loop_warning=doom_warning,
        )

        # Call LLM with retry
        response_text = self._call_llm(messages)
        if response_text is None:
            return "llm_error"

        self.lifecycle.trigger(HookEvent.POST_LLM_CALL, step_number=self._current_step)

        # Parse response
        parsed = self._parse_response(response_text)
        if parsed is None:
            return "parse_error"

        thought, action, action_input = parsed

        # Store for the acting phase
        self._pending_thought = thought
        self._pending_action = action
        self._pending_action_input = action_input

        # Check if done signal
        if action == "done":
            return "got_done"

        return "got_action"

    def _act(self) -> str:
        """Execute the pending tool action."""
        action = self._pending_action
        action_input = self._pending_action_input

        self.lifecycle.trigger(
            HookEvent.PRE_TOOL_CALL,
            step_number=self._current_step,
            tool_name=action,
        )

        start_time = time.time()
        result = self.tool_registry.dispatch(action, action_input)
        duration_ms = (time.time() - start_time) * 1000

        self.lifecycle.trigger(
            HookEvent.POST_TOOL_CALL,
            step_number=self._current_step,
            tool_name=action,
            duration_ms=duration_ms,
            success=result.success,
        )

        # Store result for observing phase
        self._pending_result = result
        self._pending_duration = duration_ms

        # Track file modifications
        if result.success and result.metadata.get("file"):
            self.state_store.mark_file_modified(result.metadata["file"])

        if result.success:
            return "tool_success"
        else:
            self.lifecycle.trigger(
                HookEvent.TOOL_ERROR,
                step_number=self._current_step,
                tool_name=action,
                error=result.error,
            )
            return "tool_error"

    def _observe(self) -> str:
        """Process the tool result and record the step."""
        result = self._pending_result
        thought = self._pending_thought
        action = self._pending_action
        action_input = self._pending_action_input

        # Build observation string
        if result.success:
            observation = result.output
        else:
            observation = f"ERROR: {result.error}"
            if result.output:
                observation += f"\nOutput: {result.output}"

        # Truncate if needed
        observation = self.context_manager.truncate_output(observation, self._current_step)

        # Record in state
        step_record = StepRecord(
            step_number=self._current_step,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation,
        )
        self.state_store.record_step(step_record)

        # Record in trajectory
        self.recorder.record_step(
            step=self._current_step,
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation,
            success=result.success,
            duration_ms=self._pending_duration,
        )

        # Save checkpoint periodically
        if self._current_step % 5 == 0:
            self.state_store.save_checkpoint()
            self.lifecycle.trigger(HookEvent.CHECKPOINT_SAVED, step_number=self._current_step)

        # Clear doom warning after a successful different action
        if result.success and "doom_warning" in self.state_store.state.metadata:
            del self.state_store.state.metadata["doom_warning"]
            if "doom_count" in self.state_store.state.metadata:
                del self.state_store.state.metadata["doom_count"]
            if "force_stuck" in self.state_store.state.metadata:
                del self.state_store.state.metadata["force_stuck"]

        self.lifecycle.trigger(HookEvent.STEP_END, step_number=self._current_step)
        self._parse_retries = 0  # Reset parse retries on successful step
        return "continue"

    def _recover(self) -> str:
        """Handle parse errors with retry."""
        self._parse_retries += 1
        if self._parse_retries > self._max_parse_retries:
            self.state_store.state.error_message = f"Max parse retries exceeded: {self._last_parse_error}"
            return "max_retries"

        self.lifecycle.trigger(
            HookEvent.PARSE_ERROR,
            step_number=self._current_step,
            error=self._last_parse_error,
        )

        # Inject parse error feedback into history as a synthetic step
        error_step = StepRecord(
            step_number=self._current_step,
            thought="(system: format error detected)",
            action="system_feedback",
            action_input={},
            observation=f"FORMAT ERROR: {self._last_parse_error}\n\nPlease respond with the correct format:\nThought: <reasoning>\n\nAction: <tool_name>\nAction Input: <json>",
        )
        self.state_store.record_step(error_step)
        self._current_step += 1

        return "retry"

    def _finalize(self) -> ExecutionResult:
        """Determine final result based on FSM terminal state."""
        if self._fsm_state == FSMState.FINISHED:
            # Check if it was a done signal or budget exhaustion
            if hasattr(self, "_pending_action") and self._pending_action == "done":
                # Record the done step
                done_input = self._pending_action_input
                summary = done_input.get("summary", "Task completed")

                step_record = StepRecord(
                    step_number=self._current_step,
                    thought=self._pending_thought,
                    action="done",
                    action_input=done_input,
                    observation=f"TASK_COMPLETE: {summary}",
                )
                self.state_store.record_step(step_record)
                self.recorder.record_step(
                    step=self._current_step,
                    thought=self._pending_thought,
                    action="done",
                    action_input=done_input,
                    observation=f"TASK_COMPLETE: {summary}",
                    success=True,
                )

                self.state_store.state.phase = AgentPhase.FINISHED
                self.state_store.state.result_status = ResultStatus.SUCCESS
                return ExecutionResult(
                    status=ResultStatus.SUCCESS,
                    message=summary,
                    steps_taken=self._current_step,
                )
            else:
                # Budget exhausted
                self.state_store.state.phase = AgentPhase.FINISHED
                self.state_store.state.result_status = ResultStatus.PARTIAL
                return ExecutionResult(
                    status=ResultStatus.PARTIAL,
                    message="Step budget exhausted before task completion",
                    steps_taken=self._current_step,
                )

        elif self._fsm_state == FSMState.STUCK:
            self.state_store.state.phase = AgentPhase.STUCK
            self.state_store.state.result_status = ResultStatus.PARTIAL
            return ExecutionResult(
                status=ResultStatus.PARTIAL,
                message=f"Agent stuck in loop: {self.state_store.state.error_message}",
                steps_taken=self._current_step,
            )

        else:  # ERROR
            self.state_store.state.phase = AgentPhase.ERROR
            self.state_store.state.result_status = ResultStatus.FAILED
            return ExecutionResult(
                status=ResultStatus.FAILED,
                message=f"Unrecoverable error: {self.state_store.state.error_message}",
                steps_taken=self._current_step,
            )

    def _call_llm(self, messages: list[dict[str, Any]]) -> str | None:
        """Call the LLM with exponential backoff retry."""
        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=4096,
                )
                content = response.choices[0].message.content
                if content:
                    return content
                return None
            except Exception as e:
                error_str = str(e)
                self.lifecycle.trigger(
                    HookEvent.LLM_ERROR,
                    step_number=self._current_step,
                    error=error_str,
                    attempt=attempt + 1,
                )
                if attempt == max_retries - 1:
                    self.state_store.state.error_message = f"LLM API failed after {max_retries} retries: {error_str}"
                    return None
                # Exponential backoff
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)

        return None

    def _parse_response(self, text: str) -> tuple[str, str, dict[str, Any]] | None:
        """Parse the LLM response into (thought, action, action_input).

        Expected format:
            Thought: <reasoning>

            Action: <tool_name>
            Action Input: <json>
        """
        # Try structured parsing first
        thought_match = re.search(r"Thought:\s*(.*?)(?=\n\s*Action:)", text, re.DOTALL)
        action_match = re.search(r"Action:\s*(\w+)", text)
        input_match = re.search(r"Action Input:\s*(\{.*\})", text, re.DOTALL)

        if not action_match:
            # Try alternative: maybe model used function calling style
            # Or maybe it just provided a thought without action
            self._last_parse_error = "Could not find 'Action: <tool_name>' in response. Please use the format: Action: <tool_name>"
            return None

        thought = thought_match.group(1).strip() if thought_match else text.split("Action:")[0].strip()
        action = action_match.group(1).strip()

        # Parse action input
        action_input: dict[str, Any] = {}
        if input_match:
            raw_json = input_match.group(1).strip()
            try:
                action_input = json.loads(raw_json)
            except json.JSONDecodeError:
                # Try to fix common issues
                fixed = self._try_fix_json(raw_json)
                if fixed is not None:
                    action_input = fixed
                else:
                    self._last_parse_error = f"Could not parse Action Input as JSON: {raw_json[:200]}"
                    return None
        else:
            # Check if there's inline text after Action Input:
            input_text_match = re.search(r"Action Input:\s*(.*)", text, re.DOTALL)
            if input_text_match:
                raw = input_text_match.group(1).strip()
                # Maybe it's just a non-JSON simple string for some tools
                if raw.startswith("{"):
                    # Multi-line JSON
                    try:
                        action_input = json.loads(raw)
                    except json.JSONDecodeError:
                        # Try to extract JSON block
                        brace_count = 0
                        end_idx = 0
                        for i, ch in enumerate(raw):
                            if ch == "{":
                                brace_count += 1
                            elif ch == "}":
                                brace_count -= 1
                                if brace_count == 0:
                                    end_idx = i + 1
                                    break
                        if end_idx > 0:
                            try:
                                action_input = json.loads(raw[:end_idx])
                            except json.JSONDecodeError:
                                self._last_parse_error = f"Could not parse Action Input JSON"
                                return None
                        else:
                            self._last_parse_error = f"Malformed JSON in Action Input"
                            return None

        # Validate tool exists
        if action != "done" and action not in self.tool_registry.get_tool_names():
            self._last_parse_error = f"Unknown tool '{action}'. Available tools: {', '.join(self.tool_registry.get_tool_names())}"
            return None

        return (thought, action, action_input)

    def _try_fix_json(self, raw: str) -> dict[str, Any] | None:
        """Attempt to fix common JSON issues in LLM output."""
        # Remove trailing commas before }
        fixed = re.sub(r",\s*}", "}", raw)
        # Remove trailing commas before ]
        fixed = re.sub(r",\s*]", "]", fixed)
        # Try parsing
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Try wrapping in braces
        if not raw.startswith("{"):
            try:
                return json.loads("{" + raw + "}")
            except json.JSONDecodeError:
                pass

        return None
