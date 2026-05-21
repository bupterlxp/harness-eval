"""
Execution Loop (E) - State machine driving the analysis workflow.

Provides explicit states, transitions, and step-by-step execution with rollback support.
"""

import os
import json
import time
import re
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass
from openai import OpenAI

from harness.state import StateStore
from harness.context import ContextManager
from harness.tools import ToolRegistry
from harness.lifecycle import LifecycleHooks, HookPhase
from harness.evaluation import TrajectoryLogger


class ExecutionState(Enum):
    """States in the analysis execution state machine."""
    INIT = "init"
    DISCOVER_DATA = "discover_data"
    LOAD_DATA = "load_data"
    ANALYZE = "analyze"
    VISUALIZE = "visualize"
    SYNTHESIZE = "synthesize"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class StateTransition:
    """Represents a transition between states."""
    from_state: ExecutionState
    to_state: ExecutionState
    condition: str
    action: Optional[str] = None


class ExecutionLoop:
    """
    State machine that drives the analysis workflow.

    States:
    - INIT: Initialize components
    - DISCOVER_DATA: Find data files in working directory
    - LOAD_DATA: Load and validate data files
    - ANALYZE: Perform analysis (LLM-driven)
    - VISUALIZE: Generate charts
    - SYNTHESIZE: Generate insights and report
    - COMPLETE: Analysis finished successfully
    - FAILED: Analysis failed

    Supports:
    - Step-by-step execution
    - State snapshots after each step
    - Rollback to previous states
    """

    VALID_TRANSITIONS = [
        StateTransition(ExecutionState.INIT, ExecutionState.DISCOVER_DATA, "initialization complete"),
        StateTransition(ExecutionState.DISCOVER_DATA, ExecutionState.LOAD_DATA, "data files found"),
        StateTransition(ExecutionState.DISCOVER_DATA, ExecutionState.FAILED, "no data files found"),
        StateTransition(ExecutionState.LOAD_DATA, ExecutionState.ANALYZE, "data loaded successfully"),
        StateTransition(ExecutionState.LOAD_DATA, ExecutionState.FAILED, "data loading failed"),
        StateTransition(ExecutionState.ANALYZE, ExecutionState.ANALYZE, "continue analysis"),
        StateTransition(ExecutionState.ANALYZE, ExecutionState.VISUALIZE, "analysis complete, generate charts"),
        StateTransition(ExecutionState.ANALYZE, ExecutionState.SYNTHESIZE, "analysis complete"),
        StateTransition(ExecutionState.ANALYZE, ExecutionState.FAILED, "analysis failed"),
        StateTransition(ExecutionState.VISUALIZE, ExecutionState.VISUALIZE, "more charts needed"),
        StateTransition(ExecutionState.VISUALIZE, ExecutionState.SYNTHESIZE, "visualization complete"),
        StateTransition(ExecutionState.SYNTHESIZE, ExecutionState.COMPLETE, "synthesis complete"),
        StateTransition(ExecutionState.SYNTHESIZE, ExecutionState.FAILED, "synthesis failed"),
    ]

    def __init__(
        self,
        output_dir: Path,
        analysis_goal: str,
        data_files: list[str],
        max_steps: int = 20,
        constraints: list[str] = None
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.analysis_goal = analysis_goal
        self.data_files = data_files
        self.max_steps = max_steps
        self.constraints = constraints or []

        self.state_store = StateStore(self.output_dir)
        self.context_manager = ContextManager(self.state_store)
        self.tool_registry = ToolRegistry(self.state_store, self.output_dir)
        self.lifecycle_hooks = LifecycleHooks(self.state_store)
        self.trajectory_logger = TrajectoryLogger(self.output_dir)

        self.current_state = ExecutionState.INIT
        self.step_count = 0
        self.error_message: Optional[str] = None

        self.context_manager.set_analysis_goal(analysis_goal)
        self.context_manager.set_constraints(constraints or [])

        self.llm_client = OpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "")
        )
        self.model_name = os.environ.get("MODEL_NAME", "gpt-4o")

    def _transition_to(self, new_state: ExecutionState, reason: str) -> bool:
        """Attempt to transition to a new state."""
        valid = any(
            t.from_state == self.current_state and t.to_state == new_state
            for t in self.VALID_TRANSITIONS
        )

        if not valid:
            return False

        self.current_state = new_state
        return True

    def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM API."""
        response = self.llm_client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.1,
            max_tokens=4096
        )
        return response.choices[0].message.content

    def _parse_llm_response(self, response: str) -> dict:
        """Parse LLM response to extract action."""
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return {
            "thought": response,
            "action": "execute_code",
            "action_input": {"code": "result = 'Could not parse response'"}
        }

    def _discover_data_files(self) -> list[Path]:
        """Discover data files in working directory."""
        extensions = ['.csv', '.xlsx', '.xls', '.json', '.parquet']
        found_files = []

        for ext in extensions:
            found_files.extend(Path('.').glob(f'*{ext}'))
            found_files.extend(Path('.').glob(f'**/*{ext}'))

        for provided in self.data_files:
            path = Path(provided)
            if path.exists() and path not in found_files:
                found_files.append(path)

        return list(set(found_files))

    def run_init(self) -> bool:
        """Initialize the execution loop."""
        hook_results = self.lifecycle_hooks.run_hooks(HookPhase.PRE_STEP, max_steps=self.max_steps)
        if not self.lifecycle_hooks.check_all_passed(hook_results):
            self.error_message = "Pre-step hooks failed during init"
            return False

        self._transition_to(ExecutionState.DISCOVER_DATA, "initialization complete")
        return True

    def run_discover_data(self) -> bool:
        """Discover available data files."""
        data_files = self._discover_data_files()

        if not data_files:
            self.error_message = "No data files found"
            self._transition_to(ExecutionState.FAILED, "no data files found")
            return False

        self.state_store.set_variable("discovered_files", [str(f) for f in data_files])
        self._transition_to(ExecutionState.LOAD_DATA, "data files found")
        return True

    def run_load_data(self) -> bool:
        """Load discovered data files."""
        files = self.state_store.get_variable("discovered_files", [])

        loaded = []
        for filepath in files:
            result = self.tool_registry.execute("load_data", path=filepath)
            if result["success"]:
                loaded.append(filepath)

                hook_results = self.lifecycle_hooks.run_hooks(
                    HookPhase.POST_LOAD,
                    dataframe_name=result["result"]["dataframe_name"]
                )

                if not self.lifecycle_hooks.check_all_passed(hook_results):
                    warnings = self.lifecycle_hooks.get_warnings(hook_results)
                    self.state_store.set_variable(f"load_warnings_{filepath}", warnings)

        if not loaded:
            self.error_message = "Failed to load any data files"
            self._transition_to(ExecutionState.FAILED, "data loading failed")
            return False

        self.state_store.set_variable("loaded_files", loaded)
        self._transition_to(ExecutionState.ANALYZE, "data loaded successfully")
        return True

    def run_analyze_step(self) -> dict:
        """Run a single analysis step (LLM-driven)."""
        start_time = time.time()

        hook_results = self.lifecycle_hooks.run_hooks(HookPhase.PRE_STEP, max_steps=self.max_steps)
        if not self.lifecycle_hooks.check_all_passed(hook_results):
            return {
                "success": False,
                "error": "Max steps exceeded",
                "finished": False
            }

        messages = self.context_manager.get_messages()
        llm_response = self._call_llm(messages)

        parsed = self._parse_llm_response(llm_response)
        thought = parsed.get("thought", "")
        action = parsed.get("action", "")
        action_input = parsed.get("action_input", {})

        if action == "finish":
            self.trajectory_logger.log_step(
                action=action,
                action_input=action_input,
                input_dataframes=self.state_store.get_all_dataframes(),
                code_executed=None,
                output_shape=None,
                charts_generated=[],
                insights_added=[],
                tool_result={"finished": True},
                duration_ms=(time.time() - start_time) * 1000,
                success=True
            )
            return {"success": True, "finished": True}

        code_executed = None
        if action == "execute_code":
            code_executed = action_input.get("code", "")

        charts_before = len(self.state_store.charts)
        insights_before = len(self.state_store.insights)

        tool_result = self.tool_registry.execute(action, **action_input)

        charts_generated = [c["path"] for c in self.state_store.charts[charts_before:]]
        insights_added = self.state_store.insights[insights_before:]

        output_shape = None
        if tool_result["success"] and tool_result["result"]:
            if isinstance(tool_result["result"], dict):
                if "shape" in tool_result["result"]:
                    output_shape = {"shape": tool_result["result"]["shape"]}

        hook_results = self.lifecycle_hooks.run_hooks(
            HookPhase.POST_ANALYSIS,
            result=tool_result.get("result")
        )

        self.trajectory_logger.log_step(
            action=action,
            action_input=action_input,
            input_dataframes=self.state_store.get_all_dataframes(),
            code_executed=code_executed,
            output_shape=output_shape,
            charts_generated=charts_generated,
            insights_added=insights_added,
            tool_result=tool_result,
            duration_ms=(time.time() - start_time) * 1000,
            success=tool_result["success"],
            error=tool_result.get("error")
        )

        self.state_store.snapshot()
        self.step_count += 1

        self.context_manager.add_message("assistant", json.dumps(parsed))
        self.context_manager.add_message("user", f"Tool result: {json.dumps(tool_result, default=str)}")

        return {
            "success": tool_result["success"],
            "action": action,
            "result": tool_result,
            "finished": False
        }

    def run_to_completion(self) -> dict:
        """Run the full analysis to completion."""
        if self.current_state == ExecutionState.INIT:
            if not self.run_init():
                return self._build_result("failed")

        if self.current_state == ExecutionState.DISCOVER_DATA:
            if not self.run_discover_data():
                return self._build_result("failed")

        if self.current_state == ExecutionState.LOAD_DATA:
            if not self.run_load_data():
                return self._build_result("failed")

        while self.current_state == ExecutionState.ANALYZE and self.step_count < self.max_steps:
            step_result = self.run_analyze_step()

            if step_result.get("finished"):
                self._transition_to(ExecutionState.COMPLETE, "analysis complete")
                break

            if not step_result.get("success"):
                consecutive_failures = self.state_store.get_variable("consecutive_failures", 0) + 1
                self.state_store.set_variable("consecutive_failures", consecutive_failures)

                if consecutive_failures >= 3:
                    self._transition_to(ExecutionState.FAILED, "too many consecutive failures")
                    break
            else:
                self.state_store.set_variable("consecutive_failures", 0)

        if self.step_count >= self.max_steps:
            self._transition_to(ExecutionState.COMPLETE, "max steps reached")

        return self._build_result()

    def rollback(self, to_step: int) -> bool:
        """Rollback to a specific step."""
        if self.state_store.rollback(to_step):
            self.step_count = to_step + 1
            self.current_state = ExecutionState.ANALYZE
            return True
        return False

    def _build_result(self, status: str = None) -> dict:
        """Build the final result object."""
        if status is None:
            if self.current_state == ExecutionState.COMPLETE:
                status = "success" if self.state_store.insights else "partial"
            elif self.current_state == ExecutionState.FAILED:
                status = "failed"
            else:
                status = "partial"

        report_path = self._generate_report()
        script_path = self._generate_script()

        result = {
            "status": status,
            "charts": self.state_store.charts,
            "insights": self.state_store.insights,
            "report_path": str(report_path),
            "script_path": str(script_path),
            "trajectory": str(self.trajectory_logger.trajectory_path)
        }

        result_path = self.output_dir / "result.json"
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)

        return result

    def _generate_report(self) -> Path:
        """Generate text report with charts."""
        report_path = self.output_dir / "report.md"

        lines = [
            f"# Data Analysis Report",
            f"\n## Analysis Goal\n{self.analysis_goal}",
            f"\n## Data Summary"
        ]

        for name in self.state_store.list_dataframes():
            df = self.state_store.get_dataframe(name)
            if df is not None:
                lines.append(f"\n### {name}")
                lines.append(f"- Rows: {len(df)}")
                lines.append(f"- Columns: {len(df.columns)}")
                lines.append(f"- Columns: {', '.join(df.columns[:20])}")

        if self.state_store.insights:
            lines.append("\n## Key Insights")
            for i, insight in enumerate(self.state_store.insights, 1):
                lines.append(f"{i}. {insight}")

        if self.state_store.charts:
            lines.append("\n## Visualizations")
            for chart in self.state_store.charts:
                lines.append(f"\n### {chart['description']}")
                lines.append(f"![{chart['description']}]({chart['path']})")

        with open(report_path, "w") as f:
            f.write("\n".join(lines))

        return report_path

    def _generate_script(self) -> Path:
        """Generate reproducible Python script."""
        script_path = self.output_dir / "analysis_script.py"

        lines = [
            '"""',
            f'Reproducible Analysis Script',
            f'Goal: {self.analysis_goal}',
            '"""',
            '',
            'import pandas as pd',
            'import numpy as np',
            'import matplotlib.pyplot as plt',
            'import seaborn as sns',
            '',
            '# Configure matplotlib for non-interactive use',
            "plt.switch_backend('Agg')",
            ''
        ]

        loaded_files = self.state_store.get_variable("loaded_files", [])
        for filepath in loaded_files:
            name = Path(filepath).stem
            suffix = Path(filepath).suffix.lower()
            if suffix == '.csv':
                lines.append(f'{name} = pd.read_csv("{filepath}")')
            elif suffix in ['.xlsx', '.xls']:
                lines.append(f'{name} = pd.read_excel("{filepath}")')
            elif suffix == '.json':
                lines.append(f'{name} = pd.read_json("{filepath}")')
            elif suffix == '.parquet':
                lines.append(f'{name} = pd.read_parquet("{filepath}")')

        lines.append('')
        lines.append('# Analysis steps')

        for step in self.trajectory_logger.get_all_steps():
            if step.code_executed:
                lines.append(f'\n# Step {step.step_id}')
                lines.append(step.code_executed)

        lines.append('')
        lines.append('print("Analysis complete")')

        with open(script_path, "w") as f:
            f.write("\n".join(lines))

        return script_path


def run_analysis(
    analysis_goal: str,
    output_dir: str,
    data_files: list[str] = None,
    max_steps: int = 20,
    constraints: list[str] = None
) -> dict:
    """Main entry point for running analysis."""
    loop = ExecutionLoop(
        output_dir=Path(output_dir),
        analysis_goal=analysis_goal,
        data_files=data_files or [],
        max_steps=max_steps,
        constraints=constraints or []
    )

    return loop.run_to_completion()
