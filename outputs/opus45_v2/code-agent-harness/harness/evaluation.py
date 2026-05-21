"""Evaluation (V) - Structured trajectory recording in JSONL format."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness.execution import ExecutionContext


@dataclass
class TrajectoryStep:
    """A single step in the execution trajectory."""
    timestamp: float
    step_number: int
    state: str
    action: str
    result: dict[str, Any]
    duration: float
    llm_calls: int
    iteration: int


@dataclass
class Trajectory:
    """Complete execution trajectory."""
    task_id: str
    task_type: str
    description: str
    start_time: float
    end_time: float | None = None
    status: str = "running"
    steps: list[TrajectoryStep] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class TrajectoryRecorder:
    """Records execution trajectory to JSONL format."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._trajectory: Trajectory | None = None
        self._step_number = 0
        self._last_step_time: float | None = None
        self._jsonl_file: Path | None = None
        self._file_handle: Any = None

    def start(self, ctx: ExecutionContext) -> str:
        """Start recording a new trajectory."""
        task_id = f"task_{int(time.time() * 1000)}"

        self._trajectory = Trajectory(
            task_id=task_id,
            task_type=ctx.task_type,
            description=ctx.description,
            start_time=time.time(),
        )

        self._step_number = 0
        self._last_step_time = time.time()

        self._jsonl_file = self.output_dir / f"trajectory_{task_id}.jsonl"
        self._file_handle = open(self._jsonl_file, "w")

        self._write_event({
            "event": "start",
            "timestamp": self._trajectory.start_time,
            "task_id": task_id,
            "task_type": ctx.task_type,
            "description": ctx.description,
            "repo_path": ctx.repo_path,
            "test_command": ctx.test_command,
            "constraints": ctx.constraints,
        })

        return task_id

    def record_step(
        self,
        ctx: ExecutionContext,
        action: str,
        result: dict[str, Any],
    ) -> None:
        """Record a single step in the trajectory."""
        if self._trajectory is None:
            return

        current_time = time.time()
        duration = current_time - (self._last_step_time or current_time)
        self._step_number += 1

        step = TrajectoryStep(
            timestamp=current_time,
            step_number=self._step_number,
            state=ctx.current_state.name,
            action=action,
            result=self._sanitize_result(result),
            duration=duration,
            llm_calls=ctx.llm_calls,
            iteration=ctx.iteration,
        )

        self._trajectory.steps.append(step)
        self._last_step_time = current_time

        self._write_event({
            "event": "step",
            "timestamp": step.timestamp,
            "step_number": step.step_number,
            "state": step.state,
            "action": step.action,
            "result": step.result,
            "duration": step.duration,
            "llm_calls": step.llm_calls,
            "iteration": step.iteration,
        })

    def record_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: dict[str, Any],
        duration: float,
    ) -> None:
        """Record a tool call."""
        self._write_event({
            "event": "tool_call",
            "timestamp": time.time(),
            "tool": tool_name,
            "params": self._sanitize_result(params),
            "result": self._sanitize_result(result),
            "duration": duration,
        })

    def record_llm_call(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
        duration: float,
    ) -> None:
        """Record an LLM API call."""
        self._write_event({
            "event": "llm_call",
            "timestamp": time.time(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "model": model,
            "duration": duration,
        })

    def record_error(self, error: str, context: dict[str, Any] | None = None) -> None:
        """Record an error event."""
        self._write_event({
            "event": "error",
            "timestamp": time.time(),
            "error": error,
            "context": context or {},
        })

    def finish(self, ctx: ExecutionContext) -> str:
        """Finish recording and return trajectory file path."""
        if self._trajectory is None:
            return ""

        self._trajectory.end_time = time.time()
        self._trajectory.status = "success" if ctx.current_state.name == "SUCCESS" else "failed"

        self._trajectory.summary = {
            "total_steps": len(self._trajectory.steps),
            "total_duration": self._trajectory.end_time - self._trajectory.start_time,
            "total_llm_calls": ctx.llm_calls,
            "total_iterations": ctx.iteration,
            "final_state": ctx.current_state.name,
            "edits_count": len(ctx.edits),
            "test_results": ctx.test_results,
            "last_error": ctx.last_error,
        }

        self._write_event({
            "event": "finish",
            "timestamp": self._trajectory.end_time,
            "status": self._trajectory.status,
            "summary": self._trajectory.summary,
        })

        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

        return str(self._jsonl_file) if self._jsonl_file else ""

    def get_trajectory(self) -> Trajectory | None:
        """Get the current trajectory."""
        return self._trajectory

    def get_statistics(self) -> dict[str, Any]:
        """Get trajectory statistics."""
        if self._trajectory is None:
            return {}

        steps = self._trajectory.steps
        if not steps:
            return {
                "total_steps": 0,
                "total_duration": 0,
                "states_visited": [],
            }

        state_durations: dict[str, float] = {}
        state_counts: dict[str, int] = {}
        action_counts: dict[str, int] = {}

        for step in steps:
            state_durations[step.state] = state_durations.get(step.state, 0) + step.duration
            state_counts[step.state] = state_counts.get(step.state, 0) + 1
            action_counts[step.action] = action_counts.get(step.action, 0) + 1

        return {
            "total_steps": len(steps),
            "total_duration": sum(s.duration for s in steps),
            "states_visited": list(state_counts.keys()),
            "state_counts": state_counts,
            "state_durations": state_durations,
            "action_counts": action_counts,
            "average_step_duration": sum(s.duration for s in steps) / len(steps),
        }

    def export_summary(self) -> dict[str, Any]:
        """Export trajectory summary for result.json."""
        if self._trajectory is None:
            return {}

        return {
            "task_id": self._trajectory.task_id,
            "task_type": self._trajectory.task_type,
            "status": self._trajectory.status,
            "duration": (self._trajectory.end_time or time.time()) - self._trajectory.start_time,
            "steps": len(self._trajectory.steps),
            "summary": self._trajectory.summary,
        }

    def _write_event(self, event: dict[str, Any]) -> None:
        """Write an event to the JSONL file."""
        if self._file_handle is None:
            return

        try:
            line = json.dumps(event, default=str)
            self._file_handle.write(line + "\n")
            self._file_handle.flush()
        except Exception:
            pass

    def _sanitize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Sanitize result for JSON serialization, truncating large values."""
        sanitized: dict[str, Any] = {}

        for key, value in result.items():
            if isinstance(value, str) and len(value) > 1000:
                sanitized[key] = value[:1000] + "... [truncated]"
            elif isinstance(value, (list, tuple)) and len(value) > 50:
                sanitized[key] = list(value[:50]) + [f"... ({len(value)} total)"]
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_result(value)
            else:
                sanitized[key] = value

        return sanitized


class TrajectoryAnalyzer:
    """Analyze trajectory files for insights."""

    def __init__(self, trajectory_path: str | Path) -> None:
        self.trajectory_path = Path(trajectory_path)
        self._events: list[dict[str, Any]] = []

    def load(self) -> bool:
        """Load trajectory from JSONL file."""
        if not self.trajectory_path.exists():
            return False

        self._events = []
        with open(self.trajectory_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self._events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return bool(self._events)

    def get_summary(self) -> dict[str, Any]:
        """Get trajectory summary."""
        if not self._events:
            return {}

        start_event = next((e for e in self._events if e.get("event") == "start"), None)
        finish_event = next((e for e in self._events if e.get("event") == "finish"), None)

        step_events = [e for e in self._events if e.get("event") == "step"]
        tool_events = [e for e in self._events if e.get("event") == "tool_call"]
        llm_events = [e for e in self._events if e.get("event") == "llm_call"]
        error_events = [e for e in self._events if e.get("event") == "error"]

        return {
            "task_id": start_event.get("task_id") if start_event else None,
            "task_type": start_event.get("task_type") if start_event else None,
            "status": finish_event.get("status") if finish_event else "incomplete",
            "total_steps": len(step_events),
            "total_tool_calls": len(tool_events),
            "total_llm_calls": len(llm_events),
            "total_errors": len(error_events),
            "summary": finish_event.get("summary") if finish_event else None,
        }

    def get_state_flow(self) -> list[str]:
        """Get sequence of states visited."""
        step_events = [e for e in self._events if e.get("event") == "step"]
        return [e.get("state", "") for e in step_events]

    def get_bottlenecks(self) -> list[dict[str, Any]]:
        """Identify steps that took longest."""
        step_events = [e for e in self._events if e.get("event") == "step"]

        sorted_steps = sorted(step_events, key=lambda e: e.get("duration", 0), reverse=True)

        return [
            {
                "step": e.get("step_number"),
                "state": e.get("state"),
                "action": e.get("action"),
                "duration": e.get("duration"),
            }
            for e in sorted_steps[:5]
        ]
