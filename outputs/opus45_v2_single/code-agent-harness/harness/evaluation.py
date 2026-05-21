"""
Evaluation (V) - Records structured trajectory in JSONL format.

Responsibilities:
- Log each step with state, operation, result, timing
- Maintain JSONL trajectory file
- Provide trajectory analysis utilities
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from enum import Enum


class StepType(str, Enum):
    """Types of steps in the trajectory."""
    PHASE_TRANSITION = "phase_transition"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TEST_RUN = "test_run"
    FILE_EDIT = "file_edit"
    SNAPSHOT = "snapshot"
    ROLLBACK = "rollback"
    ERROR = "error"
    DECISION = "decision"


@dataclass
class TrajectoryStep:
    """A single step in the agent's trajectory."""
    step_id: int
    step_type: StepType
    timestamp: float
    phase: str
    operation: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    duration_ms: float
    success: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value if isinstance(self.step_type, Enum) else self.step_type,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "operation": self.operation,
            "input": self.input_data,
            "output": self.output_data,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "metadata": self.metadata,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class TrajectoryStats:
    """Statistics about the trajectory."""
    total_steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    test_runs: int = 0
    file_edits: int = 0
    errors: int = 0
    rollbacks: int = 0
    total_duration_ms: float = 0.0
    phases_visited: list[str] = field(default_factory=list)


class TrajectoryLogger:
    """Logs agent trajectory to JSONL format."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.trajectory_path = self.output_dir / "trajectory.jsonl"
        self._step_counter = 0
        self._current_phase = "INIT"
        self._start_time: float | None = None
        self._step_start_time: float | None = None
        self._stats = TrajectoryStats()

    def start_session(self, task_description: str, metadata: dict[str, Any] | None = None) -> None:
        """Start a new trajectory session."""
        self._start_time = time.time()
        self._step_counter = 0

        # Write session header
        header = {
            "session_start": self._start_time,
            "task_description": task_description,
            "metadata": metadata or {},
        }

        with open(self.trajectory_path, "w") as f:
            f.write(json.dumps(header) + "\n")

    def end_session(self, status: str, result: dict[str, Any] | None = None) -> str:
        """End the session and write summary."""
        end_time = time.time()
        total_duration = (end_time - self._start_time) * 1000 if self._start_time else 0

        footer = {
            "session_end": end_time,
            "status": status,
            "result": result or {},
            "total_duration_ms": total_duration,
            "stats": asdict(self._stats),
        }

        with open(self.trajectory_path, "a") as f:
            f.write(json.dumps(footer) + "\n")

        return str(self.trajectory_path)

    def set_phase(self, phase: str) -> None:
        """Update current phase."""
        if phase != self._current_phase:
            self.log_step(
                step_type=StepType.PHASE_TRANSITION,
                operation=f"transition_to_{phase}",
                input_data={"from_phase": self._current_phase},
                output_data={"to_phase": phase},
                success=True,
            )
            self._current_phase = phase
            if phase not in self._stats.phases_visited:
                self._stats.phases_visited.append(phase)

    def start_step(self) -> None:
        """Mark the start of a step for timing."""
        self._step_start_time = time.time()

    def log_step(
        self,
        step_type: StepType,
        operation: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> TrajectoryStep:
        """Log a single step to the trajectory."""
        self._step_counter += 1
        timestamp = time.time()

        if self._step_start_time:
            duration_ms = (timestamp - self._step_start_time) * 1000
            self._step_start_time = None
        else:
            duration_ms = 0.0

        step = TrajectoryStep(
            step_id=self._step_counter,
            step_type=step_type,
            timestamp=timestamp,
            phase=self._current_phase,
            operation=operation,
            input_data=self._sanitize_data(input_data),
            output_data=self._sanitize_data(output_data),
            duration_ms=duration_ms,
            success=success,
            metadata=metadata or {},
        )

        # Update stats
        self._stats.total_steps += 1
        self._stats.total_duration_ms += duration_ms

        if step_type == StepType.LLM_CALL:
            self._stats.llm_calls += 1
        elif step_type == StepType.TOOL_CALL:
            self._stats.tool_calls += 1
        elif step_type == StepType.TEST_RUN:
            self._stats.test_runs += 1
        elif step_type == StepType.FILE_EDIT:
            self._stats.file_edits += 1
        elif step_type == StepType.ERROR:
            self._stats.errors += 1
        elif step_type == StepType.ROLLBACK:
            self._stats.rollbacks += 1

        # Write to file
        with open(self.trajectory_path, "a") as f:
            f.write(step.to_jsonl() + "\n")

        return step

    def log_llm_call(
        self,
        messages: list[dict[str, Any]],
        response: dict[str, Any],
        success: bool,
        model: str | None = None,
    ) -> TrajectoryStep:
        """Log an LLM API call."""
        return self.log_step(
            step_type=StepType.LLM_CALL,
            operation="llm_completion",
            input_data={
                "message_count": len(messages),
                "model": model,
                "last_message_preview": self._preview_message(messages[-1] if messages else {}),
            },
            output_data={
                "response_preview": self._preview_response(response),
                "has_tool_calls": bool(response.get("tool_calls")),
            },
            success=success,
        )

    def log_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        success: bool,
    ) -> TrajectoryStep:
        """Log a tool call."""
        return self.log_step(
            step_type=StepType.TOOL_CALL,
            operation=f"tool:{tool_name}",
            input_data={"tool": tool_name, "arguments": self._truncate_dict(arguments)},
            output_data={"result": self._truncate_value(result)},
            success=success,
        )

    def log_test_run(
        self,
        command: str,
        passed: int,
        failed: int,
        errors: list[str],
    ) -> TrajectoryStep:
        """Log a test run."""
        return self.log_step(
            step_type=StepType.TEST_RUN,
            operation="run_tests",
            input_data={"command": command},
            output_data={
                "passed": passed,
                "failed": failed,
                "error_count": len(errors),
                "error_preview": errors[:3] if errors else [],
            },
            success=failed == 0 and len(errors) == 0,
        )

    def log_file_edit(
        self,
        file_path: str,
        edit_type: str,
        diff_preview: str,
        success: bool,
    ) -> TrajectoryStep:
        """Log a file edit."""
        return self.log_step(
            step_type=StepType.FILE_EDIT,
            operation=f"edit:{edit_type}",
            input_data={"file": file_path},
            output_data={"diff_preview": diff_preview[:500]},
            success=success,
        )

    def log_error(
        self,
        error: Exception,
        context: dict[str, Any] | None = None,
    ) -> TrajectoryStep:
        """Log an error."""
        return self.log_step(
            step_type=StepType.ERROR,
            operation="error",
            input_data=context or {},
            output_data={
                "error_type": type(error).__name__,
                "error_message": str(error)[:500],
            },
            success=False,
        )

    def log_decision(
        self,
        decision: str,
        reasoning: str,
        options_considered: list[str] | None = None,
    ) -> TrajectoryStep:
        """Log a decision point."""
        return self.log_step(
            step_type=StepType.DECISION,
            operation="decision",
            input_data={
                "options": options_considered or [],
            },
            output_data={
                "decision": decision,
                "reasoning": reasoning[:500],
            },
            success=True,
        )

    def get_stats(self) -> TrajectoryStats:
        """Get current trajectory statistics."""
        return self._stats

    def read_trajectory(self) -> list[dict[str, Any]]:
        """Read the trajectory file."""
        if not self.trajectory_path.exists():
            return []

        entries = []
        with open(self.trajectory_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    @staticmethod
    def _sanitize_data(data: dict[str, Any]) -> dict[str, Any]:
        """Sanitize data for JSON serialization."""
        def sanitize_value(v: Any) -> Any:
            if isinstance(v, (str, int, float, bool, type(None))):
                return v
            elif isinstance(v, dict):
                return {k: sanitize_value(val) for k, val in v.items()}
            elif isinstance(v, (list, tuple)):
                return [sanitize_value(item) for item in v]
            else:
                return str(v)

        return {k: sanitize_value(v) for k, v in data.items()}

    @staticmethod
    def _truncate_value(value: Any, max_len: int = 500) -> Any:
        """Truncate value for logging."""
        if isinstance(value, str):
            return value[:max_len] + "..." if len(value) > max_len else value
        elif isinstance(value, dict):
            return {k: TrajectoryLogger._truncate_value(v, max_len // 2) for k, v in list(value.items())[:10]}
        elif isinstance(value, list):
            return [TrajectoryLogger._truncate_value(v, max_len // 2) for v in value[:10]]
        else:
            result = str(value)
            return result[:max_len] + "..." if len(result) > max_len else result

    @staticmethod
    def _truncate_dict(d: dict[str, Any], max_len: int = 200) -> dict[str, Any]:
        """Truncate dictionary values for logging."""
        return {k: TrajectoryLogger._truncate_value(v, max_len) for k, v in d.items()}

    @staticmethod
    def _preview_message(message: dict[str, Any]) -> str:
        """Create preview of an LLM message."""
        role = message.get("role", "unknown")
        content = message.get("content", "")
        if isinstance(content, str):
            preview = content[:200]
        else:
            preview = str(content)[:200]
        return f"[{role}] {preview}"

    @staticmethod
    def _preview_response(response: dict[str, Any]) -> str:
        """Create preview of an LLM response."""
        if "content" in response:
            return str(response["content"])[:300]
        elif "message" in response:
            return str(response["message"].get("content", ""))[:300]
        else:
            return str(response)[:300]
