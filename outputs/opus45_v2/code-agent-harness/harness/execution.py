"""Execution Loop (E) - State machine that drives task progression."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from harness.context import ContextManager
    from harness.evaluation import TrajectoryRecorder
    from harness.lifecycle import LifecycleManager
    from harness.state import StateStore
    from harness.tools import ToolRegistry


class ExecutionState(Enum):
    """States in the execution state machine."""
    INIT = auto()
    UNDERSTAND = auto()
    LOCATE = auto()
    PLAN = auto()
    EDIT = auto()
    VALIDATE = auto()
    RETRY = auto()
    ROLLBACK = auto()
    SUCCESS = auto()
    FAILED = auto()


@dataclass
class StateTransition:
    """Defines a valid state transition."""
    from_state: ExecutionState
    to_state: ExecutionState
    condition: Callable[[ExecutionContext], bool] | None = None


@dataclass
class ExecutionContext:
    """Runtime context passed through the state machine."""
    task_type: str
    description: str
    repo_path: str
    test_command: str | None
    constraints: list[str]

    current_state: ExecutionState = ExecutionState.INIT
    iteration: int = 0
    max_iterations: int = 10
    max_llm_calls: int = 50
    llm_calls: int = 0

    understanding: dict[str, Any] = field(default_factory=dict)
    located_files: list[str] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    edits: list[dict[str, str]] = field(default_factory=list)
    test_results: dict[str, Any] = field(default_factory=lambda: {"passed": 0, "failed": 0, "errors": []})
    last_error: str | None = None
    retry_count: int = 0
    max_retries: int = 3


class StateMachine:
    """Explicit state machine for execution control."""

    TRANSITIONS: list[StateTransition] = [
        StateTransition(ExecutionState.INIT, ExecutionState.UNDERSTAND),
        StateTransition(ExecutionState.UNDERSTAND, ExecutionState.LOCATE),
        StateTransition(ExecutionState.LOCATE, ExecutionState.PLAN),
        StateTransition(ExecutionState.PLAN, ExecutionState.EDIT),
        StateTransition(ExecutionState.EDIT, ExecutionState.VALIDATE),
        StateTransition(ExecutionState.VALIDATE, ExecutionState.SUCCESS),
        StateTransition(ExecutionState.VALIDATE, ExecutionState.RETRY),
        StateTransition(ExecutionState.RETRY, ExecutionState.EDIT),
        StateTransition(ExecutionState.RETRY, ExecutionState.ROLLBACK),
        StateTransition(ExecutionState.ROLLBACK, ExecutionState.PLAN),
        StateTransition(ExecutionState.ROLLBACK, ExecutionState.FAILED),
        StateTransition(ExecutionState.UNDERSTAND, ExecutionState.FAILED),
        StateTransition(ExecutionState.LOCATE, ExecutionState.FAILED),
        StateTransition(ExecutionState.PLAN, ExecutionState.FAILED),
        StateTransition(ExecutionState.EDIT, ExecutionState.FAILED),
    ]

    def __init__(self) -> None:
        self._transition_map: dict[ExecutionState, list[ExecutionState]] = {}
        for t in self.TRANSITIONS:
            if t.from_state not in self._transition_map:
                self._transition_map[t.from_state] = []
            self._transition_map[t.from_state].append(t.to_state)

    def can_transition(self, from_state: ExecutionState, to_state: ExecutionState) -> bool:
        """Check if a transition is valid."""
        return to_state in self._transition_map.get(from_state, [])

    def get_valid_transitions(self, state: ExecutionState) -> list[ExecutionState]:
        """Get all valid transitions from a state."""
        return self._transition_map.get(state, [])

    def is_terminal(self, state: ExecutionState) -> bool:
        """Check if a state is terminal."""
        return state in (ExecutionState.SUCCESS, ExecutionState.FAILED)


class ExecutionLoop:
    """Main execution loop that drives task progression using explicit state machine."""

    def __init__(
        self,
        tools: ToolRegistry,
        context_manager: ContextManager,
        state_store: StateStore,
        lifecycle: LifecycleManager,
        trajectory: TrajectoryRecorder,
        llm_client: Any,
    ) -> None:
        self.tools = tools
        self.context_manager = context_manager
        self.state_store = state_store
        self.lifecycle = lifecycle
        self.trajectory = trajectory
        self.llm_client = llm_client
        self.state_machine = StateMachine()

        self._state_handlers: dict[ExecutionState, Callable[[ExecutionContext], ExecutionState]] = {
            ExecutionState.INIT: self._handle_init,
            ExecutionState.UNDERSTAND: self._handle_understand,
            ExecutionState.LOCATE: self._handle_locate,
            ExecutionState.PLAN: self._handle_plan,
            ExecutionState.EDIT: self._handle_edit,
            ExecutionState.VALIDATE: self._handle_validate,
            ExecutionState.RETRY: self._handle_retry,
            ExecutionState.ROLLBACK: self._handle_rollback,
        }

    def run(self, ctx: ExecutionContext) -> ExecutionContext:
        """Run the execution loop until terminal state."""
        self.lifecycle.on_start(ctx)

        while not self.state_machine.is_terminal(ctx.current_state):
            if ctx.iteration >= ctx.max_iterations:
                self.trajectory.record_step(ctx, "budget_exceeded", {"reason": "max_iterations"})
                ctx.current_state = ExecutionState.FAILED
                ctx.last_error = "Maximum iterations exceeded"
                break

            if ctx.llm_calls >= ctx.max_llm_calls:
                self.trajectory.record_step(ctx, "budget_exceeded", {"reason": "max_llm_calls"})
                ctx.current_state = ExecutionState.FAILED
                ctx.last_error = "Maximum LLM calls exceeded"
                break

            start_time = time.time()
            prev_state = ctx.current_state

            handler = self._state_handlers.get(ctx.current_state)
            if handler is None:
                ctx.current_state = ExecutionState.FAILED
                ctx.last_error = f"No handler for state {ctx.current_state}"
                break

            try:
                next_state = handler(ctx)

                if not self.state_machine.can_transition(prev_state, next_state):
                    ctx.current_state = ExecutionState.FAILED
                    ctx.last_error = f"Invalid transition: {prev_state} -> {next_state}"
                    break

                elapsed = time.time() - start_time
                self.trajectory.record_step(
                    ctx,
                    f"transition_{prev_state.name}_to_{next_state.name}",
                    {"elapsed": elapsed}
                )

                ctx.current_state = next_state
                ctx.iteration += 1

                self.state_store.snapshot(ctx)

            except Exception as e:
                ctx.last_error = str(e)
                self.trajectory.record_step(ctx, "error", {"error": str(e)})
                self.lifecycle.on_error(ctx, e)
                ctx.current_state = ExecutionState.FAILED

        if ctx.current_state == ExecutionState.SUCCESS:
            self.lifecycle.on_success(ctx)
        else:
            self.lifecycle.on_failure(ctx)

        return ctx

    def _handle_init(self, ctx: ExecutionContext) -> ExecutionState:
        """Initialize execution context."""
        self.lifecycle.on_backup(ctx)
        self.state_store.snapshot(ctx)
        return ExecutionState.UNDERSTAND

    def _handle_understand(self, ctx: ExecutionContext) -> ExecutionState:
        """Understand the task and repository structure."""
        repo_structure = self.tools.call("scan_repo", {"path": ctx.repo_path})

        prompt = self.context_manager.build_prompt(
            "understand",
            task_description=ctx.description,
            task_type=ctx.task_type,
            repo_structure=repo_structure,
            constraints=ctx.constraints,
        )

        response = self._call_llm(ctx, prompt)
        ctx.understanding = self._parse_understanding(response)

        if not ctx.understanding:
            ctx.last_error = "Failed to understand task"
            return ExecutionState.FAILED

        return ExecutionState.LOCATE

    def _handle_locate(self, ctx: ExecutionContext) -> ExecutionState:
        """Locate relevant files for the task."""
        search_queries = ctx.understanding.get("search_queries", [])

        located_files: set[str] = set()
        for query in search_queries:
            results = self.tools.call("search_code", {
                "path": ctx.repo_path,
                "pattern": query,
            })
            located_files.update(results.get("files", []))

        if ctx.understanding.get("target_files"):
            located_files.update(ctx.understanding["target_files"])

        ctx.located_files = list(located_files)

        if not ctx.located_files:
            ctx.last_error = "No relevant files found"
            return ExecutionState.FAILED

        return ExecutionState.PLAN

    def _handle_plan(self, ctx: ExecutionContext) -> ExecutionState:
        """Plan the modifications."""
        file_summaries = {}
        for fpath in ctx.located_files[:10]:
            content = self.tools.call("read_file", {"path": fpath})
            summary = self.context_manager.summarize_file(fpath, content.get("content", ""))
            file_summaries[fpath] = summary

        prompt = self.context_manager.build_prompt(
            "plan",
            task_description=ctx.description,
            task_type=ctx.task_type,
            understanding=ctx.understanding,
            file_summaries=file_summaries,
            constraints=ctx.constraints,
            previous_errors=ctx.last_error if ctx.retry_count > 0 else None,
        )

        response = self._call_llm(ctx, prompt)
        ctx.plan = self._parse_plan(response)

        if not ctx.plan:
            ctx.last_error = "Failed to create plan"
            return ExecutionState.FAILED

        return ExecutionState.EDIT

    def _handle_edit(self, ctx: ExecutionContext) -> ExecutionState:
        """Execute the planned edits."""
        for step in ctx.plan:
            file_path = step.get("file")
            if not file_path:
                continue

            current_content = self.tools.call("read_file", {"path": file_path})

            prompt = self.context_manager.build_prompt(
                "edit",
                task_description=ctx.description,
                file_path=file_path,
                current_content=self.context_manager.truncate_content(
                    current_content.get("content", "")
                ),
                edit_instruction=step.get("instruction", ""),
                constraints=ctx.constraints,
            )

            response = self._call_llm(ctx, prompt)
            edit_result = self._parse_edit(response)

            if edit_result:
                write_result = self.tools.call("write_file", {
                    "path": file_path,
                    "content": edit_result["new_content"],
                })

                if write_result.get("success"):
                    diff = self.tools.call("generate_diff", {
                        "old_content": current_content.get("content", ""),
                        "new_content": edit_result["new_content"],
                        "file_path": file_path,
                    })
                    ctx.edits.append({
                        "file": file_path,
                        "diff": diff.get("diff", ""),
                    })

        return ExecutionState.VALIDATE

    def _handle_validate(self, ctx: ExecutionContext) -> ExecutionState:
        """Validate changes by running tests."""
        if not ctx.test_command:
            return ExecutionState.SUCCESS

        test_result = self.tools.call("run_command", {
            "command": ctx.test_command,
            "cwd": ctx.repo_path,
            "timeout": 300,
        })

        ctx.test_results = self._parse_test_results(test_result)

        if ctx.test_results["failed"] == 0 and not ctx.test_results["errors"]:
            return ExecutionState.SUCCESS

        return ExecutionState.RETRY

    def _handle_retry(self, ctx: ExecutionContext) -> ExecutionState:
        """Handle retry logic after validation failure."""
        ctx.retry_count += 1

        if ctx.retry_count > ctx.max_retries:
            return ExecutionState.ROLLBACK

        ctx.last_error = f"Test failures: {ctx.test_results}"
        return ExecutionState.EDIT

    def _handle_rollback(self, ctx: ExecutionContext) -> ExecutionState:
        """Rollback changes and optionally retry with new plan."""
        self.lifecycle.on_rollback(ctx)
        self.state_store.rollback(ctx)

        ctx.edits.clear()
        ctx.retry_count = 0

        if ctx.iteration < ctx.max_iterations - 2:
            return ExecutionState.PLAN

        ctx.last_error = "Failed after rollback attempts"
        return ExecutionState.FAILED

    def _call_llm(self, ctx: ExecutionContext, prompt: str) -> str:
        """Call LLM and track usage."""
        ctx.llm_calls += 1

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            self.trajectory.record_step(ctx, "llm_error", {"error": str(e)})
            raise

    def _parse_understanding(self, response: str) -> dict[str, Any]:
        """Parse understanding response from LLM."""
        import json
        import re

        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        return {
            "summary": response[:500],
            "search_queries": self._extract_keywords(response),
            "target_files": [],
        }

    def _parse_plan(self, response: str) -> list[dict[str, Any]]:
        """Parse plan response from LLM."""
        import json
        import re

        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "steps" in data:
                    return data["steps"]
            except json.JSONDecodeError:
                pass

        return [{"instruction": response, "file": None}]

    def _parse_edit(self, response: str) -> dict[str, Any] | None:
        """Parse edit response from LLM."""
        import re

        code_match = re.search(r'```(?:\w+)?\s*(.*?)\s*```', response, re.DOTALL)
        if code_match:
            return {"new_content": code_match.group(1)}

        if len(response) > 50:
            return {"new_content": response}

        return None

    def _parse_test_results(self, result: dict[str, Any]) -> dict[str, Any]:
        """Parse test execution results."""
        output = result.get("stdout", "") + result.get("stderr", "")
        exit_code = result.get("exit_code", 1)

        import re

        passed = 0
        failed = 0
        errors: list[str] = []

        pytest_match = re.search(r'(\d+) passed', output)
        if pytest_match:
            passed = int(pytest_match.group(1))

        failed_match = re.search(r'(\d+) failed', output)
        if failed_match:
            failed = int(failed_match.group(1))

        error_match = re.search(r'(\d+) error', output)
        if error_match:
            errors.append(f"{error_match.group(1)} errors in test execution")

        if exit_code != 0 and not errors and failed == 0:
            errors.append(f"Test command exited with code {exit_code}")
            if output:
                errors.append(output[:500])

        return {"passed": passed, "failed": failed, "errors": errors}

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract search keywords from text."""
        import re

        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', text)
        common_words = {'the', 'and', 'for', 'with', 'that', 'this', 'from', 'should', 'would', 'could'}
        keywords = [w for w in words if w.lower() not in common_words]

        seen: set[str] = set()
        unique: list[str] = []
        for k in keywords:
            if k.lower() not in seen:
                seen.add(k.lower())
                unique.append(k)

        return unique[:10]
