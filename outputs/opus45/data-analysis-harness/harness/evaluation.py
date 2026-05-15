"""
V - Evaluation Interface

JSONL trajectory recording for:
- Input data shape at each step
- Executed code
- Output shape and statistics
- Validation results
- Generated chart paths
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from harness.schemas import AnalysisState, ChartRecord, Insight, ValidationResult


@dataclass
class TrajectoryEntry:
    """A single entry in the execution trajectory."""
    step_number: int
    state: str
    timestamp: str
    action: str
    input_shapes: dict[str, tuple[int, ...]]
    output_shapes: dict[str, tuple[int, ...]]
    validation_results: list[dict[str, Any]]
    chart_paths: list[str]
    insights: list[dict[str, Any]]
    execution_time_ms: float
    success: bool
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class EvaluationInterface:
    """
    Records execution trajectory in JSONL format.

    Each step records:
    - Input data shapes
    - Executed action description
    - Output shapes
    - Validation results
    - Generated chart paths
    """

    def __init__(self, output_dir: Path | str = "./output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._trajectory_file = self.output_dir / "trajectory.jsonl"
        self._entries: list[TrajectoryEntry] = []
        self._current_entry: TrajectoryEntry | None = None
        self._step_start_time: datetime | None = None

    def start_step(
        self,
        step_number: int,
        state: AnalysisState,
        action: str,
        input_vars: dict[str, Any],
    ) -> None:
        """Start recording a new step."""
        self._step_start_time = datetime.now()

        input_shapes = {}
        for name, value in input_vars.items():
            if isinstance(value, pd.DataFrame):
                input_shapes[name] = value.shape
            elif isinstance(value, (list, tuple)):
                input_shapes[name] = (len(value),)
            elif isinstance(value, dict):
                input_shapes[name] = (len(value),)

        self._current_entry = TrajectoryEntry(
            step_number=step_number,
            state=state.value,
            timestamp=self._step_start_time.isoformat(),
            action=action,
            input_shapes=input_shapes,
            output_shapes={},
            validation_results=[],
            chart_paths=[],
            insights=[],
            execution_time_ms=0.0,
            success=True,
        )

    def record_outputs(self, output_vars: dict[str, Any]) -> None:
        """Record output shapes for current step."""
        if not self._current_entry:
            return

        for name, value in output_vars.items():
            if isinstance(value, pd.DataFrame):
                self._current_entry.output_shapes[name] = value.shape
            elif isinstance(value, (list, tuple)):
                self._current_entry.output_shapes[name] = (len(value),)
            elif isinstance(value, dict):
                self._current_entry.output_shapes[name] = (len(value),)

    def record_validation(self, results: list[ValidationResult]) -> None:
        """Record validation results for current step."""
        if not self._current_entry:
            return

        for result in results:
            self._current_entry.validation_results.append({
                "check_name": result.check_name,
                "passed": result.passed,
                "message": result.message,
                "severity": result.severity,
            })

    def record_chart(self, chart: ChartRecord) -> None:
        """Record a generated chart for current step."""
        if not self._current_entry:
            return

        self._current_entry.chart_paths.append(chart.file_path)

    def record_insight(self, insight: Insight) -> None:
        """Record an insight for current step."""
        if not self._current_entry:
            return

        self._current_entry.insights.append({
            "insight_id": insight.insight_id,
            "category": insight.category,
            "title": insight.title,
            "supporting_data": insight.supporting_data,
        })

    def record_extra(self, key: str, value: Any) -> None:
        """Record extra data for current step."""
        if not self._current_entry:
            return

        if isinstance(value, (str, int, float, bool, list, dict, type(None))):
            self._current_entry.extra[key] = value
        else:
            self._current_entry.extra[key] = str(value)

    def end_step(self, success: bool = True, error: str | None = None) -> None:
        """End current step and write to trajectory."""
        if not self._current_entry:
            return

        if self._step_start_time:
            elapsed = (datetime.now() - self._step_start_time).total_seconds() * 1000
            self._current_entry.execution_time_ms = elapsed

        self._current_entry.success = success
        self._current_entry.error_message = error

        self._entries.append(self._current_entry)
        self._write_entry(self._current_entry)
        self._current_entry = None

    def _write_entry(self, entry: TrajectoryEntry) -> None:
        """Write entry to JSONL file."""
        with open(self._trajectory_file, "a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def get_trajectory(self) -> list[TrajectoryEntry]:
        """Get all trajectory entries."""
        return list(self._entries)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of the execution trajectory."""
        if not self._entries:
            return {"total_steps": 0}

        total_time = sum(e.execution_time_ms for e in self._entries)
        success_count = sum(1 for e in self._entries if e.success)
        total_charts = sum(len(e.chart_paths) for e in self._entries)
        total_insights = sum(len(e.insights) for e in self._entries)

        validation_failures = []
        for entry in self._entries:
            for v in entry.validation_results:
                if not v["passed"]:
                    validation_failures.append(v)

        return {
            "total_steps": len(self._entries),
            "successful_steps": success_count,
            "failed_steps": len(self._entries) - success_count,
            "total_execution_time_ms": total_time,
            "total_charts": total_charts,
            "total_insights": total_insights,
            "validation_failures": len(validation_failures),
            "states_visited": list({e.state for e in self._entries}),
        }

    def export_summary(self, filepath: Path | str | None = None) -> str:
        """Export trajectory summary to JSON."""
        filepath = filepath or self.output_dir / "trajectory_summary.json"
        summary = self.get_summary()
        with open(filepath, "w") as f:
            json.dump(summary, f, indent=2)
        return str(filepath)

    def load_trajectory(self, filepath: Path | str | None = None) -> list[TrajectoryEntry]:
        """Load trajectory from JSONL file."""
        filepath = filepath or self._trajectory_file
        if not Path(filepath).exists():
            return []

        entries = []
        with open(filepath) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entries.append(TrajectoryEntry(**data))

        self._entries = entries
        return entries

    def clear(self) -> None:
        """Clear trajectory and remove file."""
        self._entries.clear()
        self._current_entry = None
        if self._trajectory_file.exists():
            self._trajectory_file.unlink()

    def get_step_by_number(self, step_number: int) -> TrajectoryEntry | None:
        """Get a specific step by number."""
        for entry in self._entries:
            if entry.step_number == step_number:
                return entry
        return None

    def get_steps_by_state(self, state: AnalysisState) -> list[TrajectoryEntry]:
        """Get all steps for a specific state."""
        return [e for e in self._entries if e.state == state.value]

    def get_all_chart_paths(self) -> list[str]:
        """Get paths of all generated charts."""
        paths = []
        for entry in self._entries:
            paths.extend(entry.chart_paths)
        return paths

    def get_all_validation_failures(self) -> list[dict[str, Any]]:
        """Get all validation failures across the trajectory."""
        failures = []
        for entry in self._entries:
            for v in entry.validation_results:
                if not v["passed"]:
                    failures.append({
                        "step_number": entry.step_number,
                        "state": entry.state,
                        **v
                    })
        return failures

    def format_trajectory_report(self) -> str:
        """Format trajectory as a readable report."""
        lines = ["# Execution Trajectory Report", ""]
        summary = self.get_summary()
        lines.append(f"Total Steps: {summary['total_steps']}")
        lines.append(f"Successful: {summary['successful_steps']}")
        lines.append(f"Failed: {summary['failed_steps']}")
        lines.append(f"Total Time: {summary['total_execution_time_ms']:.0f}ms")
        lines.append(f"Charts Generated: {summary['total_charts']}")
        lines.append(f"Insights Found: {summary['total_insights']}")
        lines.append("")

        lines.append("## Step Details")
        for entry in self._entries:
            status = "✓" if entry.success else "✗"
            lines.append(f"\n### {status} Step {entry.step_number}: {entry.state}")
            lines.append(f"Action: {entry.action}")
            lines.append(f"Time: {entry.execution_time_ms:.0f}ms")

            if entry.input_shapes:
                shapes = ", ".join(f"{k}: {v}" for k, v in entry.input_shapes.items())
                lines.append(f"Inputs: {shapes}")

            if entry.output_shapes:
                shapes = ", ".join(f"{k}: {v}" for k, v in entry.output_shapes.items())
                lines.append(f"Outputs: {shapes}")

            if entry.chart_paths:
                lines.append(f"Charts: {', '.join(entry.chart_paths)}")

            if entry.error_message:
                lines.append(f"Error: {entry.error_message}")

        return "\n".join(lines)
