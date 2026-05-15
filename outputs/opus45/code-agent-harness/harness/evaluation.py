"""
V component - Evaluation Interface for JSONL trajectory recording.

Records:
- State transitions
- Tool calls and their results
- Code diffs
- Test results
- Timing information
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import time

from harness.schemas import TrajectoryStep, ToolCall, TestResult


class TrajectoryRecorder:
    """
    V component - Records execution trajectory in JSONL format.

    Each step is recorded with:
    - Step number and timestamp
    - Current state
    - Action taken
    - Tool calls made
    - Code diff (if any)
    - Test results (if any)
    - Duration
    """

    def __init__(self, output_path: Optional[Path] = None) -> None:
        self._output_path = output_path
        self._steps: list[TrajectoryStep] = []
        self._step_counter = 0
        self._current_step: Optional[TrajectoryStep] = None
        self._step_start_time: Optional[float] = None

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)

    def begin_step(self, state: str, action: str) -> None:
        """Begin recording a new step."""
        self._step_counter += 1
        self._step_start_time = time.time()
        self._current_step = TrajectoryStep(
            step_number=self._step_counter,
            timestamp=datetime.now(),
            state=state,
            action=action,
            tool_calls=[],
            code_diff=None,
            test_result=None,
            duration_ms=0.0,
            metadata={},
        )

    def record_tool_call(self, tool_call: ToolCall) -> None:
        """Record a tool call in the current step."""
        if self._current_step:
            self._current_step.tool_calls.append(tool_call)

    def record_diff(self, diff: str) -> None:
        """Record a code diff in the current step."""
        if self._current_step:
            self._current_step.code_diff = diff

    def record_test_result(self, result: TestResult) -> None:
        """Record test results in the current step."""
        if self._current_step:
            self._current_step.test_result = result

    def add_metadata(self, key: str, value: any) -> None:
        """Add metadata to the current step."""
        if self._current_step:
            self._current_step.metadata[key] = value

    def end_step(self) -> TrajectoryStep:
        """End the current step and record it."""
        if not self._current_step:
            raise RuntimeError("No step in progress")

        if self._step_start_time:
            self._current_step.duration_ms = (time.time() - self._step_start_time) * 1000

        step = self._current_step
        self._steps.append(step)
        self._flush_step(step)

        self._current_step = None
        self._step_start_time = None

        return step

    def _flush_step(self, step: TrajectoryStep) -> None:
        """Write step to output file."""
        if self._output_path:
            with self._output_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(step.model_dump(), default=str) + "\n")

    def get_all_steps(self) -> list[TrajectoryStep]:
        """Get all recorded steps."""
        return list(self._steps)

    def get_step(self, step_number: int) -> Optional[TrajectoryStep]:
        """Get a specific step by number."""
        for step in self._steps:
            if step.step_number == step_number:
                return step
        return None

    def get_summary(self) -> dict:
        """Get trajectory summary statistics."""
        total_duration = sum(s.duration_ms for s in self._steps)
        tool_calls = sum(len(s.tool_calls) for s in self._steps)
        states_visited = list(set(s.state for s in self._steps))

        test_steps = [s for s in self._steps if s.test_result]
        final_test = test_steps[-1].test_result if test_steps else None

        return {
            "total_steps": len(self._steps),
            "total_duration_ms": total_duration,
            "total_tool_calls": tool_calls,
            "states_visited": states_visited,
            "final_test_result": final_test.model_dump() if final_test else None,
        }

    def export_jsonl(self, path: Path) -> None:
        """Export all steps to a JSONL file."""
        with path.open("w", encoding="utf-8") as f:
            for step in self._steps:
                f.write(json.dumps(step.model_dump(), default=str) + "\n")

    def clear(self) -> None:
        """Clear all recorded steps."""
        self._steps.clear()
        self._step_counter = 0
        self._current_step = None


class MetricsCollector:
    """Collects metrics during execution."""

    def __init__(self) -> None:
        self._metrics: dict[str, list[float]] = {}
        self._counters: dict[str, int] = {}
        self._start_times: dict[str, float] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        if name not in self._counters:
            self._counters[name] = 0
        self._counters[name] += amount

    def record(self, name: str, value: float) -> None:
        """Record a metric value."""
        if name not in self._metrics:
            self._metrics[name] = []
        self._metrics[name].append(value)

    def start_timer(self, name: str) -> None:
        """Start a timer."""
        self._start_times[name] = time.time()

    def stop_timer(self, name: str) -> float:
        """Stop a timer and return duration in ms."""
        if name not in self._start_times:
            return 0.0
        duration = (time.time() - self._start_times[name]) * 1000
        del self._start_times[name]
        self.record(f"{name}_duration_ms", duration)
        return duration

    def get_counter(self, name: str) -> int:
        """Get counter value."""
        return self._counters.get(name, 0)

    def get_metric_avg(self, name: str) -> float:
        """Get average of a metric."""
        values = self._metrics.get(name, [])
        return sum(values) / len(values) if values else 0.0

    def get_all(self) -> dict:
        """Get all metrics and counters."""
        return {
            "counters": dict(self._counters),
            "metrics": {
                name: {
                    "count": len(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values) if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                }
                for name, values in self._metrics.items()
            },
        }


class EvaluationInterface:
    """
    V component - Complete evaluation interface.

    Combines trajectory recording with metrics collection.
    """

    def __init__(self, work_dir: Path, session_id: Optional[str] = None) -> None:
        self.work_dir = work_dir
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        output_dir = work_dir / ".harness" / "trajectories"
        output_path = output_dir / f"{self.session_id}.jsonl"

        self.trajectory = TrajectoryRecorder(output_path)
        self.metrics = MetricsCollector()

    def begin_step(self, state: str, action: str) -> None:
        """Begin a new step."""
        self.trajectory.begin_step(state, action)
        self.metrics.increment("total_steps")
        self.metrics.start_timer("step")

    def record_tool_call(self, tool_call: ToolCall) -> None:
        """Record a tool call."""
        self.trajectory.record_tool_call(tool_call)
        self.metrics.increment("total_tool_calls")
        self.metrics.increment(f"tool_{tool_call.tool_name}_calls")
        if not tool_call.success:
            self.metrics.increment("failed_tool_calls")

    def record_diff(self, diff: str) -> None:
        """Record a code diff."""
        self.trajectory.record_diff(diff)
        self.metrics.increment("code_changes")

    def record_test_result(self, result: TestResult) -> None:
        """Record test results."""
        self.trajectory.record_test_result(result)
        self.metrics.increment("test_runs")
        self.metrics.record("tests_passed", result.passed)
        self.metrics.record("tests_failed", result.failed)

    def add_metadata(self, key: str, value: any) -> None:
        """Add metadata to current step."""
        self.trajectory.add_metadata(key, value)

    def end_step(self) -> TrajectoryStep:
        """End the current step."""
        step = self.trajectory.end_step()
        self.metrics.stop_timer("step")
        return step

    def get_report(self) -> dict:
        """Get comprehensive evaluation report."""
        return {
            "session_id": self.session_id,
            "trajectory_summary": self.trajectory.get_summary(),
            "metrics": self.metrics.get_all(),
        }

    def export(self, path: Optional[Path] = None) -> Path:
        """Export trajectory and report."""
        if path is None:
            path = self.work_dir / ".harness" / "reports" / f"{self.session_id}_report.json"

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.get_report(), f, indent=2, default=str)

        return path
