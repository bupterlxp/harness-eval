"""
Evaluation (V) - Structured trajectory logging.

Records:
- Each step: state, operation, result, timing
- Full execution trajectory in JSONL format
- Summary statistics
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from contextlib import contextmanager


@dataclass
class TrajectoryStep:
    """A single step in the execution trajectory."""
    step_id: int
    timestamp: float
    phase: str
    action: str
    action_input: dict[str, Any]
    result: Any
    success: bool
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "action": self.action,
            "action_input": self.action_input,
            "result": self._serialize_result(),
            "success": self.success,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata
        }

    def _serialize_result(self) -> Any:
        if self.result is None:
            return None
        if isinstance(self.result, (str, int, float, bool, list, dict)):
            return self.result
        if hasattr(self.result, "to_dict"):
            return self.result.to_dict()
        return str(self.result)


@dataclass
class TrajectorySummary:
    """Summary statistics for the trajectory."""
    total_steps: int
    successful_steps: int
    failed_steps: int
    total_duration_ms: float
    phases_visited: list[str]
    tools_used: dict[str, int]
    llm_calls: int
    retries: int

    def to_dict(self) -> dict:
        return asdict(self)


class TrajectoryLogger:
    """
    Logs execution trajectory to JSONL format.

    Each line in the output file is a JSON object representing
    a step in the execution.
    """

    def __init__(self, output_path: Path | str):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        self.steps: list[TrajectoryStep] = []
        self._step_counter = 0
        self._start_time = time.time()
        self._phases_visited: set[str] = set()
        self._tools_used: dict[str, int] = {}
        self._llm_calls = 0
        self._retries = 0

        self._file_handle = open(self.output_path, "w")

    def _write_step(self, step: TrajectoryStep) -> None:
        """Write a step to the JSONL file."""
        line = json.dumps(step.to_dict()) + "\n"
        self._file_handle.write(line)
        self._file_handle.flush()

    def log_step(
        self,
        phase: str,
        action: str,
        action_input: dict[str, Any],
        result: Any,
        success: bool,
        duration_ms: float,
        metadata: dict[str, Any] | None = None
    ) -> TrajectoryStep:
        """Log a single execution step."""
        self._step_counter += 1

        step = TrajectoryStep(
            step_id=self._step_counter,
            timestamp=time.time(),
            phase=phase,
            action=action,
            action_input=action_input,
            result=result,
            success=success,
            duration_ms=duration_ms,
            metadata=metadata or {}
        )

        self.steps.append(step)
        self._phases_visited.add(phase)

        if action.startswith("tool:"):
            tool_name = action.split(":", 1)[1]
            self._tools_used[tool_name] = self._tools_used.get(tool_name, 0) + 1
        elif action == "llm_call":
            self._llm_calls += 1

        self._write_step(step)
        return step

    @contextmanager
    def timed_step(
        self,
        phase: str,
        action: str,
        action_input: dict[str, Any],
        metadata: dict[str, Any] | None = None
    ):
        """Context manager for timing a step."""
        start = time.time()
        result_holder = {"result": None, "success": True, "error": None}

        try:
            yield result_holder
        except Exception as e:
            result_holder["success"] = False
            result_holder["error"] = str(e)
            raise
        finally:
            duration_ms = (time.time() - start) * 1000
            self.log_step(
                phase=phase,
                action=action,
                action_input=action_input,
                result=result_holder.get("result") or result_holder.get("error"),
                success=result_holder["success"],
                duration_ms=duration_ms,
                metadata=metadata
            )

    def log_retry(self, reason: str) -> None:
        """Record a retry event."""
        self._retries += 1
        self.log_step(
            phase="retry",
            action="retry",
            action_input={"reason": reason},
            result=None,
            success=True,
            duration_ms=0,
            metadata={"retry_count": self._retries}
        )

    def log_phase_transition(self, from_phase: str, to_phase: str, reason: str = "") -> None:
        """Record a phase transition."""
        self.log_step(
            phase=from_phase,
            action="phase_transition",
            action_input={"from": from_phase, "to": to_phase, "reason": reason},
            result=to_phase,
            success=True,
            duration_ms=0
        )

    def get_summary(self) -> TrajectorySummary:
        """Generate summary statistics."""
        successful = sum(1 for s in self.steps if s.success)
        total_duration = sum(s.duration_ms for s in self.steps)

        return TrajectorySummary(
            total_steps=len(self.steps),
            successful_steps=successful,
            failed_steps=len(self.steps) - successful,
            total_duration_ms=total_duration,
            phases_visited=list(self._phases_visited),
            tools_used=dict(self._tools_used),
            llm_calls=self._llm_calls,
            retries=self._retries
        )

    def finalize(self) -> Path:
        """Close the log file and return its path."""
        summary = self.get_summary()
        summary_line = json.dumps({
            "type": "summary",
            "data": summary.to_dict()
        }) + "\n"
        self._file_handle.write(summary_line)
        self._file_handle.close()
        return self.output_path

    def get_recent_steps(self, n: int = 5) -> list[TrajectoryStep]:
        """Get the most recent n steps."""
        return self.steps[-n:]

    def get_steps_by_phase(self, phase: str) -> list[TrajectoryStep]:
        """Get all steps for a specific phase."""
        return [s for s in self.steps if s.phase == phase]


class EvaluationMetrics:
    """Tracks evaluation metrics during execution."""

    def __init__(self):
        self.test_results: dict[str, Any] = {
            "passed": 0,
            "failed": 0,
            "errors": []
        }
        self.edits: list[dict[str, str]] = []
        self.llm_token_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }

    def record_test_result(self, passed: int, failed: int, errors: list[str]) -> None:
        """Record test execution results."""
        self.test_results["passed"] = passed
        self.test_results["failed"] = failed
        self.test_results["errors"] = errors

    def record_edit(self, file_path: str, diff: str) -> None:
        """Record a file edit."""
        self.edits.append({
            "file": file_path,
            "diff": diff
        })

    def record_token_usage(self, prompt: int, completion: int) -> None:
        """Record LLM token usage."""
        self.llm_token_usage["prompt_tokens"] += prompt
        self.llm_token_usage["completion_tokens"] += completion
        self.llm_token_usage["total_tokens"] += prompt + completion

    def to_dict(self) -> dict:
        return {
            "test_results": self.test_results,
            "edits": self.edits,
            "llm_token_usage": self.llm_token_usage
        }
