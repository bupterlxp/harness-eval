"""Evaluation Interface (V) — trajectory recording as JSONL.

Records every action-observation pair as a complete JSONL record.
Supports trajectory replay and analysis.
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
    action_type: str
    action_params: dict[str, Any]
    observation: str
    result: dict[str, Any]
    success: bool
    url_before: str
    url_after: str
    page_title: str = ""
    plan_state: dict[str, Any] = field(default_factory=dict)
    memory_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    llm_response_raw: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0
    error: str = ""

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        data = {
            "step": self.step,
            "timestamp": self.timestamp,
            "action": {
                "type": self.action_type,
                "params": self.action_params,
            },
            "observation": self.observation[:2000],  # Truncate for storage
            "result": self.result,
            "success": self.success,
            "url_before": self.url_before,
            "url_after": self.url_after,
            "page_title": self.page_title,
            "plan_state": self.plan_state,
            "memory_summary": self.memory_summary,
            "warnings": self.warnings,
            "llm_response_raw": self.llm_response_raw[:1000],
            "token_usage": self.token_usage,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "TrajectoryRecord":
        """Deserialize from a JSONL line."""
        data = json.loads(line)
        return cls(
            step=data["step"],
            timestamp=data["timestamp"],
            action_type=data["action"]["type"],
            action_params=data["action"]["params"],
            observation=data.get("observation", ""),
            result=data.get("result", {}),
            success=data.get("success", False),
            url_before=data.get("url_before", ""),
            url_after=data.get("url_after", ""),
            page_title=data.get("page_title", ""),
            plan_state=data.get("plan_state", {}),
            memory_summary=data.get("memory_summary", ""),
            warnings=data.get("warnings", []),
            llm_response_raw=data.get("llm_response_raw", ""),
            token_usage=data.get("token_usage", {}),
            duration_ms=data.get("duration_ms", 0),
            error=data.get("error", ""),
        )


@dataclass
class TrajectoryStats:
    """Aggregate statistics for a trajectory."""

    total_steps: int = 0
    successful_steps: int = 0
    failed_steps: int = 0
    total_duration_ms: float = 0
    total_tokens_prompt: int = 0
    total_tokens_completion: int = 0
    unique_urls_visited: int = 0
    action_type_counts: dict[str, int] = field(default_factory=dict)
    error_count: int = 0
    start_time: float = 0
    end_time: float = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrajectoryRecorder:
    """Records trajectory to JSONL file."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trajectory_path = output_dir / "trajectory.jsonl"
        self._records: list[TrajectoryRecord] = []
        self._stats = TrajectoryStats()
        self._urls_visited: set[str] = set()
        self._file_handle = None

    def start(self) -> None:
        """Start recording. Opens the trajectory file."""
        self._file_handle = open(self.trajectory_path, "w")
        self._stats.start_time = time.time()

    def record(self, record: TrajectoryRecord) -> None:
        """Record a single action-observation pair."""
        self._records.append(record)

        # Write to file immediately (streaming)
        if self._file_handle:
            self._file_handle.write(record.to_jsonl() + "\n")
            self._file_handle.flush()

        # Update stats
        self._stats.total_steps += 1
        if record.success:
            self._stats.successful_steps += 1
        else:
            self._stats.failed_steps += 1
        self._stats.total_duration_ms += record.duration_ms

        if record.token_usage:
            self._stats.total_tokens_prompt += record.token_usage.get("prompt_tokens", 0)
            self._stats.total_tokens_completion += record.token_usage.get("completion_tokens", 0)

        self._urls_visited.add(record.url_before)
        self._urls_visited.add(record.url_after)
        self._stats.unique_urls_visited = len(self._urls_visited - {""})

        action = record.action_type
        self._stats.action_type_counts[action] = (
            self._stats.action_type_counts.get(action, 0) + 1
        )

        if record.error:
            self._stats.error_count += 1

    def finish(self) -> TrajectoryStats:
        """Finish recording. Closes file and returns stats."""
        self._stats.end_time = time.time()
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None

        # Write stats file
        stats_path = self.output_dir / "trajectory_stats.json"
        with open(stats_path, "w") as f:
            json.dump(self._stats.to_dict(), f, indent=2)

        return self._stats

    def get_records(self) -> list[TrajectoryRecord]:
        """Get all recorded records."""
        return self._records

    def get_stats(self) -> TrajectoryStats:
        """Get current stats."""
        self._stats.unique_urls_visited = len(self._urls_visited - {""})
        return self._stats

    @classmethod
    def load_trajectory(cls, trajectory_path: Path) -> list[TrajectoryRecord]:
        """Load a trajectory from JSONL file."""
        records = []
        with open(trajectory_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(TrajectoryRecord.from_jsonl(line))
        return records


class EvaluationReporter:
    """Generates evaluation reports from trajectory data."""

    def __init__(self, trajectory_path: Path):
        self.trajectory_path = trajectory_path
        self.records: list[TrajectoryRecord] = []

    def load(self) -> None:
        """Load trajectory records."""
        self.records = TrajectoryRecorder.load_trajectory(self.trajectory_path)

    def compute_metrics(self) -> dict[str, Any]:
        """Compute evaluation metrics from trajectory."""
        if not self.records:
            return {"error": "No records loaded"}

        total = len(self.records)
        successes = sum(1 for r in self.records if r.success)
        failures = total - successes

        # Action diversity
        action_types = set(r.action_type for r in self.records)

        # Efficiency: ratio of successful actions to total
        efficiency = successes / total if total > 0 else 0

        # Stagnation: consecutive same actions
        max_repeat = 0
        current_repeat = 1
        for i in range(1, len(self.records)):
            if (
                self.records[i].action_type == self.records[i - 1].action_type
                and self.records[i].action_params == self.records[i - 1].action_params
            ):
                current_repeat += 1
                max_repeat = max(max_repeat, current_repeat)
            else:
                current_repeat = 1

        # Total time
        if self.records:
            total_time = self.records[-1].timestamp - self.records[0].timestamp
        else:
            total_time = 0

        # Token usage
        total_prompt_tokens = sum(r.token_usage.get("prompt_tokens", 0) for r in self.records)
        total_completion_tokens = sum(
            r.token_usage.get("completion_tokens", 0) for r in self.records
        )

        return {
            "total_steps": total,
            "successful_steps": successes,
            "failed_steps": failures,
            "success_rate": efficiency,
            "action_diversity": len(action_types),
            "action_types_used": sorted(action_types),
            "max_consecutive_repeat": max_repeat,
            "total_time_seconds": total_time,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
            "unique_urls": len(set(r.url_after for r in self.records if r.url_after)),
            "final_status": self.records[-1].action_type if self.records else "unknown",
        }

    def generate_report(self) -> str:
        """Generate a human-readable evaluation report."""
        metrics = self.compute_metrics()
        lines = [
            "=" * 60,
            "TRAJECTORY EVALUATION REPORT",
            "=" * 60,
            f"Total Steps: {metrics['total_steps']}",
            f"Success Rate: {metrics['success_rate']:.1%}",
            f"Failed Steps: {metrics['failed_steps']}",
            f"Action Diversity: {metrics['action_diversity']} types",
            f"Actions Used: {', '.join(metrics['action_types_used'])}",
            f"Max Consecutive Repeat: {metrics['max_consecutive_repeat']}",
            f"Total Time: {metrics['total_time_seconds']:.1f}s",
            f"Total Tokens: {metrics['total_tokens']}",
            f"Unique URLs: {metrics['unique_urls']}",
            f"Final Action: {metrics['final_status']}",
            "=" * 60,
        ]
        return "\n".join(lines)
