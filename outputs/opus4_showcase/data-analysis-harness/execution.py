"""Execution Loop — state-machine driven ReAct execution engine.

Implements a Plan-Code-Observe loop with explicit FSM states and
transition functions. The engine decomposes tasks, executes code,
observes results, and iterates until completion or termination.

States:
  INIT       -> PLANNING
  PLANNING   -> EXECUTING
  EXECUTING  -> OBSERVING
  OBSERVING  -> EXECUTING | PLANNING | VERIFYING | TERMINATED
  VERIFYING  -> EXECUTING | TERMINATED
  TERMINATED -> (end)
"""

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any

from openai import OpenAI

from harness.context import ContextConfig, ContextManager, Artifact
from harness.evaluation import TrajectoryRecorder
from harness.lifecycle import LifecycleManager
from harness.state import ExecutionSnapshot, StateStore
from harness.tools import ToolRegistry, ToolResult


class FSMState(str, Enum):
    """Explicit state enum for the execution FSM."""

    INIT = "INIT"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


# Transition table: maps (current_state, signal) -> next_state
TRANSITIONS: dict[tuple[FSMState, str], FSMState] = {
    # From INIT
    (FSMState.INIT, "start"): FSMState.PLANNING,
    # From PLANNING
    (FSMState.PLANNING, "plan_ready"): FSMState.EXECUTING,
    (FSMState.PLANNING, "error"): FSMState.FAILED,
    # From EXECUTING
    (FSMState.EXECUTING, "code_generated"): FSMState.OBSERVING,
    (FSMState.EXECUTING, "terminate"): FSMState.TERMINATED,
    (FSMState.EXECUTING, "error"): FSMState.OBSERVING,
    # From OBSERVING
    (FSMState.OBSERVING, "continue"): FSMState.EXECUTING,
    (FSMState.OBSERVING, "replan"): FSMState.PLANNING,
    (FSMState.OBSERVING, "verify"): FSMState.VERIFYING,
    (FSMState.OBSERVING, "terminate"): FSMState.TERMINATED,
    (FSMState.OBSERVING, "max_retries"): FSMState.EXECUTING,
    # From VERIFYING
    (FSMState.VERIFYING, "pass"): FSMState.TERMINATED,
    (FSMState.VERIFYING, "fail"): FSMState.EXECUTING,
    (FSMState.VERIFYING, "terminate"): FSMState.TERMINATED,
}


def transition(current: FSMState, signal: str) -> FSMState:
    """Apply a transition given current state and signal.

    Raises ValueError if the transition is invalid.
    """
    key = (current, signal)
    if key not in TRANSITIONS:
        raise ValueError(
            f"Invalid transition: ({current.value}, {signal!r}). "
            f"Valid signals from {current.value}: "
            f"{[s for (st, s) in TRANSITIONS if st == current]}"
        )
    return TRANSITIONS[key]


SYSTEM_PROMPT = """You are a data analysis agent. You perform systematic data analysis by writing and executing Python code step by step.

## Your Capabilities
- Load and explore data files (CSV, Excel, Parquet, JSON)
- Perform statistical analysis using pandas, numpy, scipy, scikit-learn
- Create visualizations using matplotlib and seaborn
- Write SQL queries for data engineering tasks
- Generate analysis reports with findings and recommendations

## How You Work
You operate in a ReAct loop. For each step, you output:
1. **Thought**: Your reasoning about what to do next
2. **Action**: Python code to execute

## Rules
- All code runs in a persistent Python namespace — variables survive across steps
- pandas is imported as `pd`, numpy as `np`, matplotlib.pyplot as `plt`, seaborn as `sns`
- Save charts with `plt.savefig()` to the output directory
- The working directory contains the data files
- Output directory is available as a variable: use `__output_dir__` in your code
- When you are done with the entire analysis, output EXACTLY: `[TERMINATE]` in your Thought
- When you encounter errors, analyze and fix them — do not give up easily
- Always print results so they appear in the observation
- For DataFrames, print `.head()`, `.shape`, `.describe()` — never dump full raw data
- After finishing analysis, create a summary report

## Output Format
Always respond in this exact format:

Thought: <your reasoning>

Action:
```python
<your python code>
```

OR when done:

Thought: [TERMINATE] <reason for termination>
"""


class ExecutionEngine:
    """FSM-driven execution engine for the Data Analysis Agent.

    Implements the Plan-Code-Observe ReAct loop with explicit state
    transitions, context management, and checkpoint support.
    """

    def __init__(
        self,
        prompt: str,
        output_dir: Path,
        work_dir: Path,
        max_steps: int = 20,
        token_budget: int = 120000,
        recorder: TrajectoryRecorder | None = None,
        state_store: StateStore | None = None,
        lifecycle: LifecycleManager | None = None,
        resume_from: str | None = None,
    ) -> None:
        self.prompt = prompt
        self.output_dir = output_dir
        self.work_dir = work_dir
        self.max_steps = max_steps

        # Components
        self.tools = ToolRegistry(work_dir=work_dir, output_dir=output_dir)
        self.context = ContextManager(
            config=ContextConfig(token_budget=token_budget)
        )
        self.recorder = recorder or TrajectoryRecorder(output_dir / "trajectory.jsonl")
        self.state_store = state_store or StateStore(output_dir / "checkpoints")
        self.lifecycle = lifecycle or LifecycleManager()

        # FSM state
        self._state = FSMState.INIT
        self._step_count = 0
        self._retry_count = 0
        self._max_retries = 3
        self._plan: list[dict[str, Any]] = []
        self._current_task_index = 0
        self._findings: list[str] = []
        self._progress_summary = ""

        # LLM client
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self._model = os.environ.get("MODEL_NAME", "gpt-4o")
        self._client = OpenAI(base_url=base_url, api_key=api_key)

        # Resume from checkpoint if specified
        if resume_from:
            self._restore_from_checkpoint(resume_from)

    def run(self) -> dict[str, Any]:
        """Run the execution loop until termination.

        Returns the result dict for result.json.
        """
        # Transition: INIT -> PLANNING
        self._state = transition(self._state, "start")

        # Run planning phase
        self._run_planning()

        # Main execution loop
        while self._state not in (FSMState.TERMINATED, FSMState.FAILED):
            # Check max steps
            if self._step_count >= self.max_steps:
                self.lifecycle.on_terminate(
                    reason=f"Max steps reached ({self.max_steps})",
                    step_number=self._step_count,
                )
                self._state = FSMState.TERMINATED
                break

            # Execute current state
            self.lifecycle.pre_step(self._step_count, self._state.value)

            try:
                if self._state == FSMState.PLANNING:
                    self._run_planning()
                elif self._state == FSMState.EXECUTING:
                    self._run_executing()
                elif self._state == FSMState.OBSERVING:
                    # Observing is handled within _run_executing
                    pass
                elif self._state == FSMState.VERIFYING:
                    self._run_verifying()
            except Exception as e:
                self.lifecycle.post_step(
                    self._step_count, self._state.value, success=False, error=str(e)
                )
                self.lifecycle.on_failure(error=e)
                self._state = FSMState.FAILED
                break

            # Periodic checkpoint
            if self._step_count % 5 == 0 and self._step_count > 0:
                snapshot = self.get_snapshot()
                path = self.state_store.save_checkpoint(snapshot)
                self.lifecycle.on_checkpoint(str(path))

        # Determine final status
        if self._state == FSMState.TERMINATED:
            status = "success"
        elif self._state == FSMState.FAILED:
            status = "failed"
        else:
            status = "partial"

        # Save final checkpoint
        self.state_store.save_checkpoint(self.get_snapshot())

        return {
            "status": status,
            "trajectory": str(self.recorder.output_path),
            "steps": self._step_count,
            "findings": self._findings,
            "artifacts": [a.get("path", a.get("name", "")) for a in self.tools.get_artifacts()],
        }

    def _run_planning(self) -> None:
        """PLANNING state: decompose task into sub-tasks."""
        # Discover available data
        discover_result = self.tools.dispatch("discover_data")
        data_info = discover_result.output if discover_result.success else "No data files found."

        # Set up system context
        self.context.set_system_message(SYSTEM_PROMPT)

        # Build planning prompt
        planning_prompt = f"""## Task
{self.prompt}

## Available Data
{data_info}

## Working Directory
{self.work_dir}

## Output Directory
{self.output_dir}

Begin the analysis. Start by exploring the data to understand its structure, then proceed with the analysis step by step."""

        self.context.add_user_message(planning_prompt)

        # Transition to EXECUTING
        self._state = transition(self._state, "plan_ready")

    def _run_executing(self) -> None:
        """EXECUTING state: get LLM response and execute code."""
        self._step_count += 1

        # Update progress in context
        self._update_progress()

        # Get LLM response
        messages = self.context.get_messages_for_llm()
        self.lifecycle.pre_llm_call(
            messages_count=len(messages),
            token_budget=self.context.config.token_budget,
        )

        llm_start = time.time()
        response = self._call_llm(messages)
        llm_duration = int((time.time() - llm_start) * 1000)

        token_usage = {}
        if response.usage:
            token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        self.lifecycle.post_llm_call(token_usage=token_usage, duration_ms=llm_duration)

        # Parse response
        assistant_content = response.choices[0].message.content or ""
        self.context.add_assistant_message(assistant_content)

        # Check for termination signal
        if "[TERMINATE]" in assistant_content:
            thought = assistant_content.split("[TERMINATE]")[-1].strip()
            self.lifecycle.on_terminate(reason=thought, step_number=self._step_count)

            # Record termination
            self.recorder.create_record(
                step=self._step_count,
                state=self._state.value,
                thought=f"[TERMINATE] {thought}",
                action_type="terminate",
                action_input="",
                observation="Agent terminated successfully",
                observation_type="success",
                token_usage=token_usage,
                execution_time_ms=llm_duration,
                context_tokens_used=self.context.get_token_usage()["estimated_tokens"],
                compression_level=self.context.compression_level,
            )

            self._state = transition(self._state, "terminate")
            self.lifecycle.post_step(
                self._step_count, FSMState.TERMINATED.value, success=True
            )
            return

        # Extract code from response
        thought, code = self._parse_response(assistant_content)

        if not code:
            # No code found — ask LLM to try again
            self.context.add_user_message(
                "I could not find executable code in your response. "
                "Please provide your analysis code in a ```python``` code block."
            )
            self.lifecycle.post_step(
                self._step_count, self._state.value, success=False, error="No code found"
            )
            # Stay in EXECUTING state (through OBSERVING -> continue)
            self._state = transition(self._state, "code_generated")
            self._state = transition(self._state, "continue")
            return

        # Execute the code
        self.lifecycle.pre_code_execution(code)
        exec_start = time.time()
        result = self.tools.dispatch("execute_python", code=code)
        exec_duration = int((time.time() - exec_start) * 1000)

        self.lifecycle.post_code_execution(
            code=code,
            success=result.success,
            output=result.output[:500],
            duration_ms=exec_duration,
        )

        # Build observation
        if result.success:
            observation = result.output
            obs_type = "success"
            if result.artifacts:
                observation += f"\n\n[Generated artifacts: {', '.join(Path(a).name for a in result.artifacts)}]"
                obs_type = "chart"
        else:
            observation = f"ERROR:\n{result.error}"
            obs_type = "error"

        # Add observation to context
        self.context.add_user_message(f"Observation:\n{observation}")

        # Register any new artifacts
        if result.metadata and "dataframes" in result.metadata:
            for df_info in result.metadata["dataframes"]:
                self.context.register_artifact(Artifact(
                    name=df_info["name"],
                    artifact_type="dataframe",
                    summary=f"DataFrame {df_info['shape']}, cols: {', '.join(df_info['columns'][:10])}",
                    metadata=df_info,
                ))

        for artifact_path in result.artifacts:
            self.context.register_artifact(Artifact(
                name=Path(artifact_path).name,
                artifact_type="chart",
                summary=f"Chart saved to {Path(artifact_path).name}",
                path=artifact_path,
            ))

        # Record in trajectory
        self.recorder.create_record(
            step=self._step_count,
            state=self._state.value,
            thought=thought,
            action_type="code_execution",
            action_input=code,
            observation=observation[:3000],
            observation_type=obs_type,
            artifacts=result.artifacts,
            token_usage=token_usage,
            execution_time_ms=exec_duration,
            retry_count=self._retry_count,
            context_tokens_used=self.context.get_token_usage()["estimated_tokens"],
            compression_level=self.context.compression_level,
        )

        # Handle errors with retry
        if not result.success:
            self._retry_count += 1
            if self._retry_count >= self._max_retries:
                # Too many retries, move on
                self.context.add_user_message(
                    f"This code has failed {self._retry_count} times. "
                    "Please try a different approach or move to the next analysis step."
                )
                self._retry_count = 0
            # Stay in executing (through observing -> continue)
            self._state = transition(self._state, "code_generated")
            self._state = transition(self._state, "continue")
        else:
            self._retry_count = 0
            # Transition through OBSERVING back to EXECUTING
            self._state = transition(self._state, "code_generated")
            self._state = transition(self._state, "continue")

        self.lifecycle.post_step(
            self._step_count,
            self._state.value,
            success=result.success,
            error=result.error,
            token_usage=token_usage,
        )

    def _run_verifying(self) -> None:
        """VERIFYING state: check results for completeness and correctness."""
        # Ask LLM to verify results
        verify_prompt = (
            "Review what has been accomplished so far. "
            "Are all analysis requirements met? "
            "If yes, output [TERMINATE]. "
            "If not, describe what remains and continue."
        )
        self.context.add_user_message(verify_prompt)

        messages = self.context.get_messages_for_llm()
        response = self._call_llm(messages)
        content = response.choices[0].message.content or ""
        self.context.add_assistant_message(content)

        if "[TERMINATE]" in content:
            self._state = transition(self._state, "pass")
            self.lifecycle.on_terminate(reason="Verification passed", step_number=self._step_count)
        else:
            self._state = transition(self._state, "fail")

    def _call_llm(self, messages: list[dict[str, Any]]) -> Any:
        """Make an LLM API call."""
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=4096,
                temperature=0.2,
            )
            return response
        except Exception as e:
            # If context too long, trigger emergency compression and retry
            if "context_length" in str(e).lower() or "too long" in str(e).lower():
                self.context._apply_l4_compression()
                self.lifecycle.on_compression(
                    level=4,
                    tokens_before=self.context.get_token_usage()["estimated_tokens"],
                    tokens_after=0,
                )
                messages = self.context.get_messages_for_llm()
                return self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=4096,
                    temperature=0.2,
                )
            raise

    def _parse_response(self, content: str) -> tuple[str, str]:
        """Parse LLM response into (thought, code).

        Expected format:
            Thought: <reasoning>
            Action:
            ```python
            <code>
            ```
        """
        thought = ""
        code = ""

        # Extract thought
        if "Thought:" in content:
            thought_start = content.index("Thought:") + len("Thought:")
            # Thought ends at Action: or at code block
            thought_end = len(content)
            for marker in ["Action:", "```python", "```"]:
                if marker in content[thought_start:]:
                    candidate = content.index(marker, thought_start)
                    thought_end = min(thought_end, candidate)
            thought = content[thought_start:thought_end].strip()

        # Extract code from code block
        if "```python" in content:
            code_start = content.index("```python") + len("```python")
            code_end = content.find("```", code_start)
            if code_end == -1:
                code_end = len(content)
            code = content[code_start:code_end].strip()
        elif "```" in content:
            # Try generic code block
            parts = content.split("```")
            if len(parts) >= 3:
                code = parts[1].strip()
                # Remove language identifier if present
                if code.startswith(("python\n", "py\n")):
                    code = code.split("\n", 1)[1]

        return thought, code

    def _update_progress(self) -> None:
        """Update the progress summary in context."""
        completed_steps = self._step_count
        artifacts = self.tools.get_artifacts()
        charts = [a for a in artifacts if a.get("type") == "chart"]
        dataframes = [a for a in artifacts if a.get("type") == "dataframe"]

        summary_parts = [
            f"Steps completed: {completed_steps}/{self.max_steps}",
            f"DataFrames in namespace: {len(dataframes)}",
            f"Charts generated: {len(charts)}",
        ]

        if self._findings:
            summary_parts.append(f"Key findings: {len(self._findings)}")

        self._progress_summary = " | ".join(summary_parts)
        self.context.update_progress(self._progress_summary)

    def get_snapshot(self) -> ExecutionSnapshot:
        """Create a snapshot of current state for checkpointing."""
        return ExecutionSnapshot(
            current_state=self._state.value,
            step_count=self._step_count,
            prompt=self.prompt,
            messages=self.context.get_messages_raw(),
            plan=self._plan,
            current_task_index=self._current_task_index,
            artifacts=[a for a in self.tools.get_artifacts()],
            namespace_vars=self.tools.sandbox.get_variable_names(),
            progress_summary=self._progress_summary,
            findings=self._findings,
            step_history=[],
        )

    def _restore_from_checkpoint(self, checkpoint_path: str) -> None:
        """Restore engine state from a checkpoint."""
        snapshot = self.state_store.load_checkpoint(checkpoint_path)
        self._state = FSMState(snapshot.current_state)
        self._step_count = snapshot.step_count
        self._plan = snapshot.plan
        self._current_task_index = snapshot.current_task_index
        self._findings = snapshot.findings
        self._progress_summary = snapshot.progress_summary
        self.context.restore_messages(snapshot.messages)
        print(f"[harness] Restored from checkpoint at step {snapshot.step_count}")
