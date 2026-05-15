"""
S - State Store

Manages execution state including:
- DataFrame snapshots at each step
- Variable registry for intermediate results
- Rollback support to any step
"""

from __future__ import annotations

import copy
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from harness.schemas import AnalysisState, AnalysisStep, ChartRecord, Insight


@dataclass
class StateSnapshot:
    """A snapshot of state at a particular step."""
    step_number: int
    state: AnalysisState
    variables: dict[str, Any]
    charts: list[ChartRecord]
    insights: list[Insight]
    created_at: datetime = field(default_factory=datetime.now)

    def copy_variables(self) -> dict[str, Any]:
        """Deep copy variables for restoration."""
        result = {}
        for key, value in self.variables.items():
            if isinstance(value, pd.DataFrame):
                result[key] = value.copy(deep=True)
            elif isinstance(value, (list, dict)):
                result[key] = copy.deepcopy(value)
            else:
                result[key] = value
        return result


class ExecutionState:
    """
    Manages the complete execution state for the analysis harness.

    Supports:
    - Variable registration and retrieval
    - DataFrame snapshot management
    - Step-level rollback
    - State persistence (optional)
    """

    def __init__(self, output_dir: Path | str = "./output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._current_state: AnalysisState = AnalysisState.INIT
        self._step_number: int = 0
        self._variables: dict[str, Any] = {}
        self._snapshots: dict[int, StateSnapshot] = {}
        self._steps: list[AnalysisStep] = []
        self._charts: list[ChartRecord] = []
        self._insights: list[Insight] = []
        self._start_time: datetime = datetime.now()

    @property
    def current_state(self) -> AnalysisState:
        """Get current analysis state."""
        return self._current_state

    @property
    def step_number(self) -> int:
        """Get current step number."""
        return self._step_number

    @property
    def variables(self) -> dict[str, Any]:
        """Get all registered variables (read-only view)."""
        return dict(self._variables)

    @property
    def charts(self) -> list[ChartRecord]:
        """Get all generated charts."""
        return list(self._charts)

    @property
    def insights(self) -> list[Insight]:
        """Get all recorded insights."""
        return list(self._insights)

    @property
    def steps(self) -> list[AnalysisStep]:
        """Get all executed steps."""
        return list(self._steps)

    def set_variable(self, name: str, value: Any) -> None:
        """Register or update a variable."""
        self._variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a registered variable."""
        return self._variables.get(name, default)

    def has_variable(self, name: str) -> bool:
        """Check if a variable is registered."""
        return name in self._variables

    def get_dataframe(self, name: str) -> pd.DataFrame | None:
        """Get a DataFrame variable with type checking."""
        value = self._variables.get(name)
        if isinstance(value, pd.DataFrame):
            return value
        return None

    def add_chart(self, chart: ChartRecord) -> None:
        """Register a generated chart."""
        self._charts.append(chart)

    def add_insight(self, insight: Insight) -> None:
        """Register a discovered insight."""
        self._insights.append(insight)

    def start_step(self, state: AnalysisState, description: str,
                   input_vars: list[str], output_vars: list[str],
                   validation_conditions: list[str]) -> AnalysisStep:
        """Start a new analysis step."""
        self._step_number += 1
        step = AnalysisStep(
            state=state,
            step_number=self._step_number,
            description=description,
            input_vars=input_vars,
            output_vars=output_vars,
            validation_conditions=validation_conditions,
        )
        self._steps.append(step)
        self._current_state = state
        return step

    def complete_step(self, step: AnalysisStep, success: bool = True,
                      error: str | None = None, findings: list[str] | None = None) -> None:
        """Complete a step and take a snapshot."""
        step.mark_complete(success=success, error=error)
        if findings:
            step.findings = findings

        if success:
            self._take_snapshot()

    def _take_snapshot(self) -> None:
        """Take a snapshot of current state."""
        snapshot = StateSnapshot(
            step_number=self._step_number,
            state=self._current_state,
            variables=self._copy_variables(),
            charts=list(self._charts),
            insights=list(self._insights),
        )
        self._snapshots[self._step_number] = snapshot

    def _copy_variables(self) -> dict[str, Any]:
        """Deep copy all variables for snapshotting."""
        result = {}
        for key, value in self._variables.items():
            if isinstance(value, pd.DataFrame):
                result[key] = value.copy(deep=True)
            elif isinstance(value, (list, dict)):
                result[key] = copy.deepcopy(value)
            else:
                result[key] = value
        return result

    def can_rollback_to(self, step_number: int) -> bool:
        """Check if rollback to a specific step is possible."""
        return step_number in self._snapshots

    def rollback_to_step(self, step_number: int) -> bool:
        """
        Rollback state to after a specific step completed.

        Returns True if successful, False if snapshot not found.
        """
        if step_number not in self._snapshots:
            return False

        snapshot = self._snapshots[step_number]

        self._variables = snapshot.copy_variables()
        self._charts = list(snapshot.charts)
        self._insights = list(snapshot.insights)
        self._current_state = snapshot.state
        self._step_number = snapshot.step_number

        steps_to_remove = [s for s in self._steps if s.step_number > step_number]
        for step in steps_to_remove:
            self._steps.remove(step)

        snapshots_to_remove = [k for k in self._snapshots if k > step_number]
        for k in snapshots_to_remove:
            del self._snapshots[k]

        return True

    def rollback_to_state(self, state: AnalysisState) -> bool:
        """
        Rollback to the last snapshot of a specific state.

        Returns True if successful, False if no snapshot found for that state.
        """
        matching_snapshots = [
            (step_num, snap) for step_num, snap in self._snapshots.items()
            if snap.state == state
        ]
        if not matching_snapshots:
            return False

        latest_step = max(matching_snapshots, key=lambda x: x[0])[0]
        return self.rollback_to_step(latest_step)

    def get_available_rollback_points(self) -> list[tuple[int, AnalysisState, str]]:
        """Get list of available rollback points."""
        result = []
        for step_num, snapshot in sorted(self._snapshots.items()):
            step = next((s for s in self._steps if s.step_number == step_num), None)
            desc = step.description if step else ""
            result.append((step_num, snapshot.state, desc))
        return result

    def transition_to(self, new_state: AnalysisState) -> None:
        """Transition to a new state (without starting a step)."""
        self._current_state = new_state

    def get_last_chart(self) -> ChartRecord | None:
        """Get the most recently generated chart."""
        return self._charts[-1] if self._charts else None

    def get_charts_for_state(self, state: AnalysisState) -> list[ChartRecord]:
        """Get all charts generated in a specific state."""
        return [c for c in self._charts if c.state == state]

    def get_execution_summary(self) -> dict[str, Any]:
        """Get a summary of the execution state."""
        return {
            "current_state": self._current_state.value,
            "step_number": self._step_number,
            "total_steps": len(self._steps),
            "successful_steps": sum(1 for s in self._steps if s.success),
            "failed_steps": sum(1 for s in self._steps if not s.success and s.completed_at),
            "variables_count": len(self._variables),
            "charts_count": len(self._charts),
            "insights_count": len(self._insights),
            "snapshots_count": len(self._snapshots),
            "elapsed_time": (datetime.now() - self._start_time).total_seconds(),
        }

    def save_to_file(self, filepath: Path | str) -> None:
        """Persist state to a file."""
        filepath = Path(filepath)
        state_data = {
            "current_state": self._current_state.value,
            "step_number": self._step_number,
            "variables": self._variables,
            "snapshots": self._snapshots,
            "steps": self._steps,
            "charts": self._charts,
            "insights": self._insights,
            "start_time": self._start_time,
        }
        with open(filepath, "wb") as f:
            pickle.dump(state_data, f)

    def load_from_file(self, filepath: Path | str) -> bool:
        """Load state from a file."""
        filepath = Path(filepath)
        if not filepath.exists():
            return False

        with open(filepath, "rb") as f:
            state_data = pickle.load(f)

        self._current_state = AnalysisState(state_data["current_state"])
        self._step_number = state_data["step_number"]
        self._variables = state_data["variables"]
        self._snapshots = state_data["snapshots"]
        self._steps = state_data["steps"]
        self._charts = state_data["charts"]
        self._insights = state_data["insights"]
        self._start_time = state_data["start_time"]
        return True

    def clear(self) -> None:
        """Reset state to initial values."""
        self._current_state = AnalysisState.INIT
        self._step_number = 0
        self._variables.clear()
        self._snapshots.clear()
        self._steps.clear()
        self._charts.clear()
        self._insights.clear()
        self._start_time = datetime.now()
