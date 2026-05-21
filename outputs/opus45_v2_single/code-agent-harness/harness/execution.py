"""
Execution Loop (E) - State machine that drives task execution.

Responsibilities:
- Explicit state machine (no while True + if chains)
- Support nested sub-loops (edit -> test -> fail -> re-edit)
- Drive understand -> locate -> plan -> edit -> verify cycle
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from harness.context import ContextManager
from harness.evaluation import TrajectoryLogger, StepType
from harness.lifecycle import LifecycleManager, HookEvent
from harness.state import AgentPhase, StateStore
from harness.tools import ToolRegistry, ToolResult


class TransitionResult(Enum):
    """Result of a state transition."""
    CONTINUE = auto()
    COMPLETE = auto()
    FAILED = auto()
    RETRY = auto()


@dataclass
class PhaseResult:
    """Result of executing a phase."""
    transition: TransitionResult
    next_phase: AgentPhase | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class PhaseHandler(ABC):
    """Abstract base class for phase handlers."""

    @abstractmethod
    def execute(self, context: ExecutionContext) -> PhaseResult:
        """Execute this phase and return the result."""
        pass


@dataclass
class ExecutionContext:
    """Context available during phase execution."""
    state_store: StateStore
    tool_registry: ToolRegistry
    context_manager: ContextManager
    lifecycle: LifecycleManager
    trajectory: TrajectoryLogger
    llm_client: OpenAI
    model_name: str

    def call_llm(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Make an LLM call with tracking."""
        self.state_store.increment_llm_calls()
        self.trajectory.start_step()

        try:
            kwargs: dict[str, Any] = {
                "model": self.model_name,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = self.llm_client.chat.completions.create(**kwargs)
            result = {
                "content": response.choices[0].message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in (response.choices[0].message.tool_calls or [])
                ],
                "finish_reason": response.choices[0].finish_reason,
            }

            self.trajectory.log_llm_call(messages, result, success=True, model=self.model_name)
            return result

        except Exception as e:
            self.trajectory.log_llm_call(messages, {"error": str(e)}, success=False, model=self.model_name)
            raise

    def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool with tracking."""
        self.trajectory.start_step()

        result = self.tool_registry.execute(tool_name, **arguments)

        self.trajectory.log_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            result=result.output if result.success else result.error,
            success=result.success,
        )

        return result


class InitPhase(PhaseHandler):
    """Initialize the agent and understand the task."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("INIT")

        # Scan repository structure
        repo_path = ctx.state_store.state.repo_path or "."
        result = ctx.execute_tool("list_directory", {"path": repo_path, "recursive": True, "pattern": "*.py"})

        if not result.success:
            return PhaseResult(
                transition=TransitionResult.FAILED,
                error=f"Failed to scan repository: {result.error}",
            )

        files = result.output[:100] if result.output else []
        ctx.state_store.state.understanding = f"Repository has {len(files)} Python files"

        return PhaseResult(
            transition=TransitionResult.CONTINUE,
            next_phase=AgentPhase.UNDERSTAND,
            data={"files_found": len(files)},
        )


class UnderstandPhase(PhaseHandler):
    """Understand the task and codebase."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("UNDERSTAND")

        task = ctx.state_store.state.task_description
        repo_path = ctx.state_store.state.repo_path or "."

        # Build understanding prompt
        ctx.context_manager.set_system_prompt(
            "You are a code analysis assistant. Analyze the task and identify key areas to investigate."
        )

        ctx.context_manager.add_message("user", f"""Task: {task}

Repository path: {repo_path}

Please analyze this task and identify:
1. What needs to be changed or fixed
2. Key files or components likely involved
3. What patterns or keywords to search for

Respond with a JSON object containing:
- "summary": brief understanding of the task
- "search_patterns": list of patterns to search for
- "likely_files": list of file patterns that might be relevant
""")

        messages = ctx.context_manager.get_messages()

        try:
            response = ctx.call_llm(messages)
            content = response.get("content", "")

            # Parse response
            try:
                json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
                if json_match:
                    analysis = json.loads(json_match.group())
                else:
                    analysis = {"summary": content, "search_patterns": [], "likely_files": []}
            except json.JSONDecodeError:
                analysis = {"summary": content, "search_patterns": [], "likely_files": []}

            ctx.state_store.state.understanding = analysis.get("summary", content)

            ctx.trajectory.log_decision(
                decision="Proceed to locate phase",
                reasoning=analysis.get("summary", "Task analyzed")[:200],
                options_considered=["locate files", "request clarification"],
            )

            return PhaseResult(
                transition=TransitionResult.CONTINUE,
                next_phase=AgentPhase.LOCATE,
                data={"analysis": analysis},
            )

        except Exception as e:
            return PhaseResult(
                transition=TransitionResult.FAILED,
                error=f"Failed to understand task: {e}",
            )


class LocatePhase(PhaseHandler):
    """Locate relevant files and code sections."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("LOCATE")

        task = ctx.state_store.state.task_description
        repo_path = ctx.state_store.state.repo_path or "."

        # Use LLM to guide search
        ctx.context_manager.add_message("user", f"""Based on the task: {task}

Use the search tools to find relevant code. Available tools:
- search_code: Search for patterns in files
- find_definition: Find function/class definitions
- list_directory: List files in directories

Identify the specific files and code locations that need to be modified.""")

        tools = ctx.tool_registry.get_tools_for_llm()
        messages = ctx.context_manager.get_messages()

        located_files = []
        max_tool_rounds = 5

        for round_num in range(max_tool_rounds):
            response = ctx.call_llm(messages, tools=tools)

            if not response.get("tool_calls"):
                break

            # Process tool calls
            for tool_call in response["tool_calls"]:
                func_name = tool_call["function"]["name"]
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                result = ctx.execute_tool(func_name, args)

                # Track located files
                if func_name in ("search_code", "find_definition") and result.success:
                    for item in result.output or []:
                        if isinstance(item, dict) and "file" in item:
                            if item["file"] not in located_files:
                                located_files.append(item["file"])

                # Summarize result for context
                if result.success and result.output:
                    summary = ctx.context_manager.summarize_search_results(result.output) \
                        if isinstance(result.output, list) else str(result.output)[:500]
                else:
                    summary = f"Error: {result.error}"

                ctx.context_manager.add_message("tool", summary, tool_call_id=tool_call["id"])

            messages = ctx.context_manager.get_messages()

        ctx.state_store.state.located_files = located_files[:20]

        if not located_files:
            return PhaseResult(
                transition=TransitionResult.RETRY,
                next_phase=AgentPhase.UNDERSTAND,
                error="No relevant files found",
            )

        return PhaseResult(
            transition=TransitionResult.CONTINUE,
            next_phase=AgentPhase.PLAN,
            data={"located_files": located_files},
        )


class PlanPhase(PhaseHandler):
    """Plan the modifications."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("PLAN")

        task = ctx.state_store.state.task_description
        located_files = ctx.state_store.state.located_files

        # Read located files (summarized)
        file_summaries = []
        for file_path in located_files[:5]:
            result = ctx.execute_tool("read_file", {"path": file_path})
            if result.success:
                content = result.output.get("content", "")
                summary = ctx.context_manager.summarize_file_content(file_path, content)
                file_summaries.append(summary)

        ctx.context_manager.add_message("user", f"""Task: {task}

Located files:
{chr(10).join(f'- {f}' for f in located_files)}

File summaries:
{chr(10).join(file_summaries[:3])}

Create a plan for implementing this task. Specify:
1. Which files to modify
2. What changes to make in each file
3. Order of changes

Respond with a JSON object:
{{
  "plan_steps": [
    {{"file": "path", "action": "modify|create|delete", "description": "what to change"}}
  ]
}}""")

        messages = ctx.context_manager.get_messages()
        response = ctx.call_llm(messages)
        content = response.get("content", "")

        # Parse plan
        try:
            json_match = re.search(r"\{[^{}]*\"plan_steps\"[^{}]*\[.*?\][^{}]*\}", content, re.DOTALL)
            if json_match:
                plan_data = json.loads(json_match.group())
                steps = plan_data.get("plan_steps", [])
            else:
                steps = [{"file": f, "action": "modify", "description": "Apply changes"} for f in located_files[:3]]
        except json.JSONDecodeError:
            steps = [{"file": f, "action": "modify", "description": "Apply changes"} for f in located_files[:3]]

        ctx.state_store.state.current_plan = [
            f"{s.get('action', 'modify')} {s.get('file', 'unknown')}: {s.get('description', '')}"
            for s in steps
        ]

        ctx.trajectory.log_decision(
            decision=f"Plan with {len(steps)} steps",
            reasoning=f"Will modify: {', '.join(s.get('file', 'unknown') for s in steps[:3])}",
            options_considered=[f"Step: {s.get('description', '')[:50]}" for s in steps[:3]],
        )

        return PhaseResult(
            transition=TransitionResult.CONTINUE,
            next_phase=AgentPhase.EDIT,
            data={"plan": steps},
        )


class EditPhase(PhaseHandler):
    """Execute the planned edits."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("EDIT")

        task = ctx.state_store.state.task_description
        plan = ctx.state_store.state.current_plan
        located_files = ctx.state_store.state.located_files

        # Read files that will be edited
        file_contents = {}
        for file_path in located_files[:5]:
            result = ctx.execute_tool("read_file", {"path": file_path})
            if result.success:
                file_contents[file_path] = result.output.get("content", "")

        ctx.context_manager.add_message("user", f"""Task: {task}

Plan:
{chr(10).join(f'- {step}' for step in plan)}

Now implement the changes. Use the edit_file or write_file tools to make modifications.
Make precise, minimal changes that accomplish the task.""")

        tools = ctx.tool_registry.get_tools_for_llm()
        messages = ctx.context_manager.get_messages()

        edits_made = []
        max_edit_rounds = 10

        for round_num in range(max_edit_rounds):
            response = ctx.call_llm(messages, tools=tools)

            if not response.get("tool_calls"):
                # LLM finished editing
                break

            for tool_call in response["tool_calls"]:
                func_name = tool_call["function"]["name"]
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                # Backup before edit
                if func_name in ("write_file", "edit_file"):
                    file_path = args.get("path", "")
                    ctx.lifecycle.trigger(HookEvent.PRE_EDIT, file=file_path)

                result = ctx.execute_tool(func_name, args)

                if func_name in ("write_file", "edit_file") and result.success:
                    file_path = args.get("path", "")
                    if file_path not in ctx.state_store.state.modified_files:
                        ctx.state_store.state.modified_files.append(file_path)

                    edits_made.append({
                        "file": file_path,
                        "tool": func_name,
                        "success": result.success,
                    })

                    ctx.trajectory.log_file_edit(
                        file_path=file_path,
                        edit_type=func_name,
                        diff_preview=str(args.get("new_content", args.get("content", "")))[:200],
                        success=result.success,
                    )

                # Add result to context
                result_str = json.dumps(result.output) if result.success else f"Error: {result.error}"
                ctx.context_manager.add_message("tool", result_str[:500], tool_call_id=tool_call["id"])

            messages = ctx.context_manager.get_messages()

        if not edits_made:
            return PhaseResult(
                transition=TransitionResult.RETRY,
                next_phase=AgentPhase.PLAN,
                error="No edits were made",
            )

        return PhaseResult(
            transition=TransitionResult.CONTINUE,
            next_phase=AgentPhase.VERIFY,
            data={"edits": edits_made},
        )


class VerifyPhase(PhaseHandler):
    """Verify changes by running tests."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("VERIFY")

        test_command = ctx.state_store.state.test_command

        if not test_command:
            # No test command, consider it success
            return PhaseResult(
                transition=TransitionResult.COMPLETE,
                next_phase=AgentPhase.COMPLETE,
                data={"test_results": {"passed": 0, "failed": 0, "errors": [], "skipped": True}},
            )

        # Run tests
        ctx.lifecycle.trigger(HookEvent.PRE_TEST, command=test_command)
        result = ctx.execute_tool("execute_command", {
            "command": test_command,
            "cwd": ctx.state_store.state.repo_path or ".",
            "timeout": 120,
        })

        test_results = self._parse_test_output(result)
        ctx.state_store.state.test_results = test_results

        ctx.trajectory.log_test_run(
            command=test_command,
            passed=test_results.get("passed", 0),
            failed=test_results.get("failed", 0),
            errors=test_results.get("errors", []),
        )

        ctx.lifecycle.trigger(HookEvent.POST_TEST, command=test_command, results=test_results)

        if test_results.get("failed", 0) > 0 or test_results.get("errors"):
            # Tests failed, need to retry
            if ctx.state_store.can_continue():
                ctx.state_store.increment_retry()
                ctx.lifecycle.trigger(HookEvent.RETRY, reason="test_failure")

                return PhaseResult(
                    transition=TransitionResult.RETRY,
                    next_phase=AgentPhase.EDIT,
                    data={"test_results": test_results},
                    error=f"Tests failed: {test_results.get('failed', 0)} failures",
                )
            else:
                return PhaseResult(
                    transition=TransitionResult.FAILED,
                    error="Tests failed and retry limit reached",
                    data={"test_results": test_results},
                )

        return PhaseResult(
            transition=TransitionResult.COMPLETE,
            next_phase=AgentPhase.COMPLETE,
            data={"test_results": test_results},
        )

    @staticmethod
    def _parse_test_output(result: ToolResult) -> dict[str, Any]:
        """Parse test command output to extract results."""
        if not result.success:
            return {"passed": 0, "failed": 0, "errors": [result.error or "Test command failed"]}

        output = result.output or {}
        stdout = output.get("stdout", "")
        stderr = output.get("stderr", "")
        returncode = output.get("returncode", 1)

        passed = 0
        failed = 0
        errors = []

        # Try to parse pytest output
        pytest_match = re.search(r"(\d+) passed", stdout)
        if pytest_match:
            passed = int(pytest_match.group(1))

        failed_match = re.search(r"(\d+) failed", stdout)
        if failed_match:
            failed = int(failed_match.group(1))

        error_match = re.search(r"(\d+) error", stdout)
        if error_match:
            errors.append(f"{error_match.group(1)} errors")

        # Capture error messages
        if stderr:
            errors.extend(stderr.splitlines()[:5])

        if returncode != 0 and not passed and not failed:
            errors.append(f"Test command exited with code {returncode}")

        return {"passed": passed, "failed": failed, "errors": errors}


class RetryPhase(PhaseHandler):
    """Handle retry logic."""

    def execute(self, ctx: ExecutionContext) -> PhaseResult:
        ctx.trajectory.set_phase("RETRY")

        if not ctx.state_store.can_continue():
            return PhaseResult(
                transition=TransitionResult.FAILED,
                error="Exceeded retry or LLM call limits",
            )

        # Analyze failure and decide next action
        test_results = ctx.state_store.state.test_results
        error_messages = ctx.state_store.state.error_messages

        ctx.context_manager.add_message("user", f"""The previous attempt failed.

Test results: {json.dumps(test_results)}
Errors: {chr(10).join(error_messages[-3:])}

Analyze what went wrong and suggest how to fix it.
Should we:
1. Modify the edit approach
2. Rollback and try a different strategy
3. Give up

Respond with JSON: {{"action": "modify|rollback|give_up", "reasoning": "..."}}""")

        messages = ctx.context_manager.get_messages()
        response = ctx.call_llm(messages)
        content = response.get("content", "")

        # Parse decision
        try:
            json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group())
            else:
                decision = {"action": "modify", "reasoning": "Attempting modification"}
        except json.JSONDecodeError:
            decision = {"action": "modify", "reasoning": "Attempting modification"}

        action = decision.get("action", "modify")

        ctx.trajectory.log_decision(
            decision=action,
            reasoning=decision.get("reasoning", "")[:200],
            options_considered=["modify", "rollback", "give_up"],
        )

        if action == "give_up":
            return PhaseResult(
                transition=TransitionResult.FAILED,
                error="Agent decided to give up",
            )
        elif action == "rollback":
            ctx.lifecycle.trigger(HookEvent.ROLLBACK)
            return PhaseResult(
                transition=TransitionResult.CONTINUE,
                next_phase=AgentPhase.PLAN,
                data={"rolled_back": True},
            )
        else:
            return PhaseResult(
                transition=TransitionResult.CONTINUE,
                next_phase=AgentPhase.EDIT,
                data={"retry_modification": True},
            )


class ExecutionLoop:
    """Main execution loop implementing an explicit state machine."""

    PHASE_HANDLERS: dict[AgentPhase, type[PhaseHandler]] = {
        AgentPhase.INIT: InitPhase,
        AgentPhase.UNDERSTAND: UnderstandPhase,
        AgentPhase.LOCATE: LocatePhase,
        AgentPhase.PLAN: PlanPhase,
        AgentPhase.EDIT: EditPhase,
        AgentPhase.VERIFY: VerifyPhase,
        AgentPhase.RETRY: RetryPhase,
    }

    def __init__(
        self,
        state_store: StateStore,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        lifecycle: LifecycleManager,
        trajectory: TrajectoryLogger,
    ):
        self.state_store = state_store
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.lifecycle = lifecycle
        self.trajectory = trajectory

        # Initialize LLM client
        self.llm_client = OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
        )
        self.model_name = os.environ.get("MODEL_NAME", "gpt-4")

        self._handlers: dict[AgentPhase, PhaseHandler] = {
            phase: handler_class()
            for phase, handler_class in self.PHASE_HANDLERS.items()
        }

    def run(self) -> dict[str, Any]:
        """Run the execution loop until completion or failure."""
        self.lifecycle.trigger(HookEvent.TASK_START)
        self.trajectory.start_session(
            task_description=self.state_store.state.task_description,
            metadata={"repo_path": self.state_store.state.repo_path},
        )

        current_phase = self.state_store.state.phase

        while current_phase not in (AgentPhase.COMPLETE, AgentPhase.FAILED):
            if not self.state_store.can_continue():
                current_phase = AgentPhase.FAILED
                self.state_store.state.error_messages.append("Budget exceeded")
                break

            handler = self._handlers.get(current_phase)
            if not handler:
                current_phase = AgentPhase.FAILED
                self.state_store.state.error_messages.append(f"No handler for phase: {current_phase}")
                break

            ctx = ExecutionContext(
                state_store=self.state_store,
                tool_registry=self.tool_registry,
                context_manager=self.context_manager,
                lifecycle=self.lifecycle,
                trajectory=self.trajectory,
                llm_client=self.llm_client,
                model_name=self.model_name,
            )

            try:
                with self.lifecycle.phase_guard(current_phase.name):
                    result = handler.execute(ctx)

                if result.transition == TransitionResult.COMPLETE:
                    current_phase = AgentPhase.COMPLETE
                elif result.transition == TransitionResult.FAILED:
                    current_phase = AgentPhase.FAILED
                    if result.error:
                        self.state_store.state.error_messages.append(result.error)
                elif result.transition == TransitionResult.RETRY:
                    current_phase = result.next_phase or AgentPhase.RETRY
                else:
                    current_phase = result.next_phase or AgentPhase.FAILED

                self.state_store.set_phase(current_phase)
                self.state_store.create_snapshot(f"phase_{current_phase.name}")

            except Exception as e:
                self.lifecycle.trigger_error(e, phase=current_phase.name)
                self.state_store.state.error_messages.append(str(e))
                current_phase = AgentPhase.FAILED
                self.state_store.set_phase(current_phase)

        self.lifecycle.trigger(HookEvent.TASK_END)
        self.state_store.save_state()

        status = "success" if current_phase == AgentPhase.COMPLETE else "failed"
        trajectory_path = self.trajectory.end_session(status, self._build_result())

        return self._build_result(trajectory_path)

    def _build_result(self, trajectory_path: str | None = None) -> dict[str, Any]:
        """Build the final result object."""
        state = self.state_store.state

        # Compute diffs for modified files
        edits = []
        for file_path in state.modified_files:
            backup = self.state_store.file_backups.get(file_path)
            if backup:
                original = backup.original_content or ""
                try:
                    current = Path(file_path).read_text(encoding="utf-8")
                except Exception:
                    current = ""

                # Simple diff representation
                diff = self._compute_diff(original, current)
                edits.append({"file": file_path, "diff": diff})

        return {
            "status": "success" if state.phase == AgentPhase.COMPLETE else (
                "partial" if state.modified_files else "failed"
            ),
            "edits": edits,
            "test_results": {
                "passed": state.test_results.get("passed", 0),
                "failed": state.test_results.get("failed", 0),
                "errors": state.test_results.get("errors", []),
            },
            "trajectory": trajectory_path or str(self.trajectory.trajectory_path),
        }

    @staticmethod
    def _compute_diff(original: str, current: str) -> str:
        """Compute a simple unified diff."""
        import difflib

        original_lines = original.splitlines(keepends=True)
        current_lines = current.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            current_lines,
            fromfile="original",
            tofile="modified",
        )

        return "".join(diff)
