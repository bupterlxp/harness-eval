"""
Execution Loop (E) - Explicit state machine for task execution.

Implements:
- Explicit state machine (no while True + if chains)
- Nested sub-loops for edit→test→retry cycles
- Phase transitions with clear conditions
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from enum import Enum, auto

from openai import OpenAI

from harness.state import StateStore, AgentPhase
from harness.context import ContextManager, ContextRole
from harness.tools import ToolRegistry, ToolResult
from harness.evaluation import TrajectoryLogger, EvaluationMetrics
from harness.lifecycle import LifecycleManager, BudgetManager, LifecycleEvent


class TransitionCondition(Enum):
    """Conditions that trigger state transitions."""
    UNDERSTANDING_COMPLETE = auto()
    LOCATION_FOUND = auto()
    PLAN_READY = auto()
    EDIT_COMPLETE = auto()
    TESTS_PASSED = auto()
    TESTS_FAILED = auto()
    RETRY_NEEDED = auto()
    RETRY_EXHAUSTED = auto()
    BUDGET_EXCEEDED = auto()
    ERROR_FATAL = auto()
    TASK_COMPLETE = auto()


@dataclass
class StateTransition:
    """Defines a valid state transition."""
    from_phase: AgentPhase
    to_phase: AgentPhase
    condition: TransitionCondition


@dataclass
class ExecutionResult:
    """Result of a single execution step."""
    phase: AgentPhase
    action_taken: str
    output: Any
    next_condition: TransitionCondition | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class StateMachine:
    """
    Explicit state machine for agent execution.

    Defines valid transitions and handles phase execution.
    """

    VALID_TRANSITIONS: list[StateTransition] = [
        StateTransition(AgentPhase.INIT, AgentPhase.UNDERSTAND, TransitionCondition.UNDERSTANDING_COMPLETE),

        StateTransition(AgentPhase.UNDERSTAND, AgentPhase.LOCATE, TransitionCondition.UNDERSTANDING_COMPLETE),
        StateTransition(AgentPhase.UNDERSTAND, AgentPhase.FAILED, TransitionCondition.ERROR_FATAL),

        StateTransition(AgentPhase.LOCATE, AgentPhase.PLAN, TransitionCondition.LOCATION_FOUND),
        StateTransition(AgentPhase.LOCATE, AgentPhase.FAILED, TransitionCondition.ERROR_FATAL),

        StateTransition(AgentPhase.PLAN, AgentPhase.EDIT, TransitionCondition.PLAN_READY),
        StateTransition(AgentPhase.PLAN, AgentPhase.FAILED, TransitionCondition.ERROR_FATAL),

        StateTransition(AgentPhase.EDIT, AgentPhase.VERIFY, TransitionCondition.EDIT_COMPLETE),
        StateTransition(AgentPhase.EDIT, AgentPhase.RETRY, TransitionCondition.RETRY_NEEDED),
        StateTransition(AgentPhase.EDIT, AgentPhase.FAILED, TransitionCondition.ERROR_FATAL),

        StateTransition(AgentPhase.VERIFY, AgentPhase.COMPLETE, TransitionCondition.TESTS_PASSED),
        StateTransition(AgentPhase.VERIFY, AgentPhase.RETRY, TransitionCondition.TESTS_FAILED),
        StateTransition(AgentPhase.VERIFY, AgentPhase.FAILED, TransitionCondition.ERROR_FATAL),

        StateTransition(AgentPhase.RETRY, AgentPhase.EDIT, TransitionCondition.RETRY_NEEDED),
        StateTransition(AgentPhase.RETRY, AgentPhase.LOCATE, TransitionCondition.RETRY_NEEDED),
        StateTransition(AgentPhase.RETRY, AgentPhase.FAILED, TransitionCondition.RETRY_EXHAUSTED),
        StateTransition(AgentPhase.RETRY, AgentPhase.FAILED, TransitionCondition.BUDGET_EXCEEDED),
    ]

    def __init__(self):
        self._transition_map: dict[AgentPhase, list[StateTransition]] = {}
        for t in self.VALID_TRANSITIONS:
            if t.from_phase not in self._transition_map:
                self._transition_map[t.from_phase] = []
            self._transition_map[t.from_phase].append(t)

    def get_valid_transitions(self, phase: AgentPhase) -> list[StateTransition]:
        """Get all valid transitions from a phase."""
        return self._transition_map.get(phase, [])

    def can_transition(self, from_phase: AgentPhase, to_phase: AgentPhase, condition: TransitionCondition) -> bool:
        """Check if a transition is valid."""
        for t in self._transition_map.get(from_phase, []):
            if t.to_phase == to_phase and t.condition == condition:
                return True
        return False

    def get_next_phase(self, current_phase: AgentPhase, condition: TransitionCondition) -> AgentPhase | None:
        """Get the next phase for a given condition."""
        for t in self._transition_map.get(current_phase, []):
            if t.condition == condition:
                return t.to_phase
        return None


class ExecutionLoop:
    """
    Main execution loop driving the agent.

    Uses explicit state machine rather than while True + if chains.
    """

    SYSTEM_PROMPT = """You are a code agent that helps fix bugs and implement features.
You have access to tools for reading files, searching code, and making edits.

When you need to take an action, respond with a JSON object in this format:
{
    "thought": "your reasoning about what to do",
    "action": "tool_name",
    "action_input": {"param": "value"}
}

When you have completed a phase, respond with:
{
    "thought": "reasoning",
    "action": "phase_complete",
    "action_input": {"summary": "what was accomplished", "findings": [...]}
}

Available tools will be provided. Always explain your reasoning before acting."""

    def __init__(
        self,
        repo_path: Path,
        task_spec: dict[str, Any],
        output_dir: Path | None = None
    ):
        self.repo_path = Path(repo_path).resolve()
        self.task_spec = task_spec
        self.output_dir = output_dir or self.repo_path / ".harness_output"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.state_store = StateStore(self.repo_path, self.output_dir / "state")
        self.tools = ToolRegistry(self.repo_path)
        self.context = ContextManager(max_tokens=8000, system_prompt=self.SYSTEM_PROMPT)
        self.trajectory = TrajectoryLogger(self.output_dir / "trajectory.jsonl")
        self.metrics = EvaluationMetrics()
        self.lifecycle = LifecycleManager(self.state_store)
        self.budget = BudgetManager(
            max_llm_calls=50,
            max_retries=5,
            max_iterations=100,
            max_duration_seconds=600
        )
        self.state_machine = StateMachine()

        self._llm_client: OpenAI | None = None
        self._model_name = os.environ.get("MODEL_NAME", "gpt-4")
        self._retry_context: dict[str, Any] = {}

    def _get_llm_client(self) -> OpenAI:
        """Lazy initialization of LLM client."""
        if self._llm_client is None:
            self._llm_client = OpenAI(
                base_url=os.environ.get("OPENAI_BASE_URL"),
                api_key=os.environ.get("OPENAI_API_KEY", "")
            )
        return self._llm_client

    def _call_llm(self, messages: list[dict]) -> str:
        """Make an LLM call with tracking."""
        self.budget.record_llm_call()

        within_budget, reason = self.budget.check_budget()
        if not within_budget:
            raise RuntimeError(f"Budget exceeded: {reason}")

        start_time = time.time()
        client = self._get_llm_client()

        self.lifecycle.trigger(LifecycleEvent.BEFORE_LLM_CALL, {"messages": messages})

        response = client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            temperature=0.2,
            max_tokens=2000
        )

        content = response.choices[0].message.content or ""
        duration_ms = (time.time() - start_time) * 1000

        if response.usage:
            self.metrics.record_token_usage(
                response.usage.prompt_tokens,
                response.usage.completion_tokens
            )

        self.trajectory.log_step(
            phase=self.state_store.current_phase.value,
            action="llm_call",
            action_input={"message_count": len(messages)},
            result=content[:500],
            success=True,
            duration_ms=duration_ms
        )

        self.lifecycle.trigger(LifecycleEvent.AFTER_LLM_CALL, {"response": content})

        return content

    def _parse_llm_response(self, response: str) -> dict[str, Any]:
        """Parse LLM response to extract action."""
        response = response.strip()

        if response.startswith('{'):
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        start = response.find('{')
        if start != -1:
            depth = 0
            for i, c in enumerate(response[start:], start):
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(response[start:i+1])
                        except json.JSONDecodeError:
                            break

        return {
            "thought": response,
            "action": "continue",
            "action_input": {}
        }

    def _execute_tool(self, action: str, action_input: dict) -> ToolResult:
        """Execute a tool and track it."""
        start_time = time.time()

        if action in ["phase_complete", "continue"]:
            return ToolResult(success=True, output=action_input)

        result = self.tools.invoke(action, **action_input)
        duration_ms = (time.time() - start_time) * 1000

        self.trajectory.log_step(
            phase=self.state_store.current_phase.value,
            action=f"tool:{action}",
            action_input=action_input,
            result=result.output if result.success else result.error,
            success=result.success,
            duration_ms=duration_ms
        )

        return result

    def _build_phase_prompt(self, phase: AgentPhase) -> str:
        """Build the prompt for a specific phase."""
        task_desc = self.task_spec.get("description", "")
        task_type = self.task_spec.get("task_type", "unknown")
        constraints = self.task_spec.get("constraints", [])

        base_prompt = f"""Task Type: {task_type}
Task Description: {task_desc}
Constraints: {', '.join(constraints) if constraints else 'None'}

"""
        tools_desc = self.tools.get_tools_description()

        phase_instructions = {
            AgentPhase.UNDERSTAND: f"""Phase: UNDERSTAND
Your goal is to understand the task and the codebase context.

{tools_desc}

Actions to take:
1. Use get_repo_structure to understand the project layout
2. Search for relevant files and code patterns
3. Read key files to understand the context

When you understand the task, respond with action="phase_complete" and summarize your understanding.""",

            AgentPhase.LOCATE: f"""Phase: LOCATE
Your goal is to find the specific location(s) that need to be modified.

{tools_desc}

Actions to take:
1. Use search_code to find relevant code patterns
2. Use find_definition to locate functions/classes
3. Read the relevant file sections

When you've found the locations, respond with action="phase_complete" and list the files and line numbers.""",

            AgentPhase.PLAN: f"""Phase: PLAN
Your goal is to create a plan for the changes needed.

Based on your understanding and the locations found, create a detailed plan.

When ready, respond with action="phase_complete" and include:
- Files to modify
- Changes to make
- Order of operations""",

            AgentPhase.EDIT: f"""Phase: EDIT
Your goal is to make the necessary code changes.

{tools_desc}

Use edit_file or write_file to make changes. Make one change at a time and verify.

When done editing, respond with action="phase_complete".""",

            AgentPhase.VERIFY: f"""Phase: VERIFY
Your goal is to verify the changes work correctly.

Test command: {self.task_spec.get('test_command', 'None specified')}

{tools_desc}

Use run_command to execute tests and verify the changes.

If tests pass, respond with action="phase_complete" and success=true.
If tests fail, respond with action="phase_complete" and success=false, including the failures.""",

            AgentPhase.RETRY: f"""Phase: RETRY
Previous attempt failed. Analyzing what went wrong.

Previous context: {json.dumps(self._retry_context)}

{tools_desc}

Determine what needs to be fixed and respond with action="phase_complete" indicating whether to retry editing or re-locate."""
        }

        return base_prompt + phase_instructions.get(phase, "Unknown phase")

    def _execute_phase(self, phase: AgentPhase) -> ExecutionResult:
        """Execute a single phase of the state machine."""
        with self.lifecycle.phase_scope(phase):
            prompt = self._build_phase_prompt(phase)
            self.context.add_message(ContextRole.USER, prompt)

            max_steps = 20
            for step in range(max_steps):
                self.budget.record_iteration()

                within_budget, reason = self.budget.check_budget()
                if not within_budget:
                    return ExecutionResult(
                        phase=phase,
                        action_taken="budget_exceeded",
                        output=reason,
                        next_condition=TransitionCondition.BUDGET_EXCEEDED
                    )

                messages = self.context.get_messages_for_llm()
                response = self._call_llm(messages)
                self.context.add_message(ContextRole.ASSISTANT, response)

                parsed = self._parse_llm_response(response)
                action = parsed.get("action", "continue")
                action_input = parsed.get("action_input", {})

                if action == "phase_complete":
                    return self._handle_phase_completion(phase, action_input)

                if action not in ["continue", "phase_complete"]:
                    result = self._execute_tool(action, action_input)

                    if action == "edit_file" and result.success:
                        file_path = action_input.get("path", "")
                        diff = f"-{action_input.get('old_content', '')[:100]}\n+{action_input.get('new_content', '')[:100]}"
                        self.metrics.record_edit(file_path, diff)

                    result_text = f"Result: {result.output}" if result.success else f"Error: {result.error}"
                    self.context.add_tool_result(action, result_text)

            return ExecutionResult(
                phase=phase,
                action_taken="max_steps_reached",
                output="Phase did not complete within step limit",
                next_condition=TransitionCondition.RETRY_NEEDED
            )

    def _handle_phase_completion(self, phase: AgentPhase, action_input: dict) -> ExecutionResult:
        """Handle phase completion and determine next condition."""
        if phase == AgentPhase.UNDERSTAND:
            return ExecutionResult(
                phase=phase,
                action_taken="phase_complete",
                output=action_input,
                next_condition=TransitionCondition.UNDERSTANDING_COMPLETE
            )

        elif phase == AgentPhase.LOCATE:
            return ExecutionResult(
                phase=phase,
                action_taken="phase_complete",
                output=action_input,
                next_condition=TransitionCondition.LOCATION_FOUND
            )

        elif phase == AgentPhase.PLAN:
            return ExecutionResult(
                phase=phase,
                action_taken="phase_complete",
                output=action_input,
                next_condition=TransitionCondition.PLAN_READY
            )

        elif phase == AgentPhase.EDIT:
            return ExecutionResult(
                phase=phase,
                action_taken="phase_complete",
                output=action_input,
                next_condition=TransitionCondition.EDIT_COMPLETE
            )

        elif phase == AgentPhase.VERIFY:
            success = action_input.get("success", False)
            if success:
                return ExecutionResult(
                    phase=phase,
                    action_taken="phase_complete",
                    output=action_input,
                    next_condition=TransitionCondition.TESTS_PASSED
                )
            else:
                self._retry_context = action_input
                return ExecutionResult(
                    phase=phase,
                    action_taken="phase_complete",
                    output=action_input,
                    next_condition=TransitionCondition.TESTS_FAILED
                )

        elif phase == AgentPhase.RETRY:
            self.budget.record_retry()
            within_budget, reason = self.budget.check_budget()
            if not within_budget:
                return ExecutionResult(
                    phase=phase,
                    action_taken="retry_exhausted",
                    output=reason,
                    next_condition=TransitionCondition.RETRY_EXHAUSTED
                )
            return ExecutionResult(
                phase=phase,
                action_taken="phase_complete",
                output=action_input,
                next_condition=TransitionCondition.RETRY_NEEDED
            )

        return ExecutionResult(
            phase=phase,
            action_taken="unknown",
            output=action_input,
            next_condition=TransitionCondition.ERROR_FATAL
        )

    def _run_tests(self) -> dict[str, Any]:
        """Run test command and parse results."""
        test_cmd = self.task_spec.get("test_command")
        if not test_cmd:
            return {"passed": 0, "failed": 0, "errors": ["No test command specified"]}

        with self.lifecycle.test_scope(test_cmd):
            result = self.tools.invoke("run_command", command=test_cmd, timeout=120)

            if not result.success:
                return {"passed": 0, "failed": 1, "errors": [result.error or "Command failed"]}

            output = result.output
            stdout = output.get("stdout", "")
            stderr = output.get("stderr", "")
            returncode = output.get("returncode", 1)

            passed = 0
            failed = 0
            errors = []

            pytest_match = re.search(r'(\d+) passed', stdout)
            if pytest_match:
                passed = int(pytest_match.group(1))

            fail_match = re.search(r'(\d+) failed', stdout)
            if fail_match:
                failed = int(fail_match.group(1))

            if returncode != 0:
                if failed == 0:
                    failed = 1
                if stderr:
                    errors.append(stderr[:500])

            return {"passed": passed, "failed": failed, "errors": errors}

    def run(self) -> dict[str, Any]:
        """
        Execute the main loop using the state machine.

        Returns the final result dictionary.
        """
        self.lifecycle.task_start(self.task_spec)

        current_phase = AgentPhase.INIT
        self.state_store.set_phase(current_phase)

        self.trajectory.log_phase_transition("none", current_phase.value, "task_start")

        current_phase = AgentPhase.UNDERSTAND
        self.state_store.set_phase(current_phase)

        terminal_phases = {AgentPhase.COMPLETE, AgentPhase.FAILED}

        while current_phase not in terminal_phases:
            within_budget, reason = self.budget.check_budget()
            if not within_budget:
                self.trajectory.log_step(
                    phase=current_phase.value,
                    action="budget_exceeded",
                    action_input={},
                    result=reason,
                    success=False,
                    duration_ms=0
                )
                current_phase = AgentPhase.FAILED
                break

            try:
                with self.lifecycle.error_boundary(rollback=False):
                    result = self._execute_phase(current_phase)

                    if result.next_condition:
                        next_phase = self.state_machine.get_next_phase(current_phase, result.next_condition)

                        if next_phase:
                            self.trajectory.log_phase_transition(
                                current_phase.value,
                                next_phase.value,
                                result.next_condition.name
                            )
                            current_phase = next_phase
                            self.state_store.set_phase(current_phase)
                        else:
                            current_phase = AgentPhase.FAILED

            except Exception as e:
                self.trajectory.log_step(
                    phase=current_phase.value,
                    action="error",
                    action_input={},
                    result=str(e),
                    success=False,
                    duration_ms=0
                )
                current_phase = AgentPhase.FAILED

        status = "success" if current_phase == AgentPhase.COMPLETE else "failed"

        if current_phase == AgentPhase.COMPLETE and self.task_spec.get("test_command"):
            test_results = self._run_tests()
            self.metrics.record_test_result(
                test_results["passed"],
                test_results["failed"],
                test_results["errors"]
            )
            if test_results["failed"] > 0:
                status = "partial"
        else:
            test_results = self.metrics.test_results

        trajectory_path = self.trajectory.finalize()

        result = {
            "status": status,
            "edits": self.metrics.edits,
            "test_results": test_results,
            "trajectory": str(trajectory_path)
        }

        self.lifecycle.task_end(status, result)

        return result
