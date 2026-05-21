"""Evaluation Interface — trajectory recording as JSONL.

Records every action-observation pair as a complete record in a JSONL file,
enabling offline evaluation of agent behavior.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryRecord:
    """A single action-observation record in the trajectory."""

    step: int
    timestamp: float
    state: str  # FSM state at time of action

    # LLM decision
    thought: str
    action_type: str  # "code_execution" | "sql_execution" | "file_operation" | "terminate"
    action_input: str  # The code or command to execute

    # Execution result
    observation: str  # stdout/stderr/result summary
    observation_type: str  # "success" | "error" | "timeout" | "chart"
    artifacts: list[str] = field(default_factory=list)  # Paths to generated files

    # Metrics
    token_usage: dict[str, int] = field(default_factory=dict)
    execution_time_ms: int = 0
    retry_count: int = 0

    # Context state
    context_tokens_used: int = 0
    compression_level: int = 0  # 0=none, 1-4 = compression levels applied

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrajectoryRecorder:
    """Records agent trajectory as JSONL for evaluation.

    Each line in the output file is a complete JSON object representing
    one action-observation cycle.
    """

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self._records: list[TrajectoryRecord] = []
        self._start_time = time.time()
        # Ensure file exists (truncate if resuming is not needed)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, record: TrajectoryRecord) -> None:
        """Append a record to the trajectory."""
        self._records.append(record)
        with open(self.output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def create_record(
        self,
        step: int,
        state: str,
        thought: str,
        action_type: str,
        action_input: str,
        observation: str,
        observation_type: str,
        artifacts: list[str] | None = None,
        token_usage: dict[str, int] | None = None,
        execution_time_ms: int = 0,
        retry_count: int = 0,
        context_tokens_used: int = 0,
        compression_level: int = 0,
    ) -> TrajectoryRecord:
        """Create and record a trajectory entry."""
        record = TrajectoryRecord(
            step=step,
            timestamp=time.time(),
            state=state,
            thought=thought,
            action_type=action_type,
            action_input=action_input,
            observation=observation,
            observation_type=observation_type,
            artifacts=artifacts or [],
            token_usage=token_usage or {},
            execution_time_ms=execution_time_ms,
            retry_count=retry_count,
            context_tokens_used=context_tokens_used,
            compression_level=compression_level,
        )
        self.record(record)
        return record

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the trajectory for reporting."""
        total_time = time.time() - self._start_time
        success_count = sum(1 for r in self._records if r.observation_type == "success")
        error_count = sum(1 for r in self._records if r.observation_type == "error")
        total_tokens = sum(
            r.token_usage.get("total_tokens", 0) for r in self._records
        )
        return {
            "total_steps": len(self._records),
            "success_steps": success_count,
            "error_steps": error_count,
            "total_time_seconds": round(total_time, 2),
            "total_tokens": total_tokens,
            "trajectory_path": str(self.output_path),
        }

    @property
    def step_count(self) -> int:
        return len(self._records)
