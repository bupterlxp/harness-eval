"""Evaluation Interface — trajectory recording as JSONL.

Each line in the trajectory file is a complete action-observation record
containing all information needed to replay or evaluate the agent's behavior.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class TrajectoryEntry:
    """A single entry in the trajectory JSONL."""
    timestamp: float
    entry_type: str  # "action", "observation", "phase_transition", "error", "metric"
    phase: str = ""
    iteration: int = 0
    tool_name: str = ""
    action_type: str = ""
    input_data: Any = None
    output_data: Any = None
    duration_ms: float = 0.0
    token_usage: int = 0
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "timestamp": self.timestamp,
            "entry_type": self.entry_type,
        }
        if self.phase:
            d["phase"] = self.phase
        if self.iteration:
            d["iteration"] = self.iteration
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.action_type:
            d["action_type"] = self.action_type
        if self.input_data is not None:
            d["input"] = self.input_data
        if self.output_data is not None:
            d["output"] = self.output_data
        if self.duration_ms:
            d["duration_ms"] = self.duration_ms
        if self.token_usage:
            d["token_usage"] = self.token_usage
        if self.error:
            d["error"] = self.error
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class TrajectoryRecorder:
    """Records agent trajectory as JSONL for evaluation."""

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self._entries: list[TrajectoryEntry] = []
        self._start_time = time.time()
        self._total_tokens = 0
        self._total_actions = 0

        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write header entry
        self._write_entry(TrajectoryEntry(
            timestamp=time.time(),
            entry_type="session_start",
            metadata={"start_time": self._start_time},
        ))

    def record_action(self, action_type: str, tool_name: str,
                      input_data: Any, output_data: Any,
                      duration_ms: float = 0.0, token_usage: int = 0,
                      phase: str = "", iteration: int = 0,
                      metadata: Optional[dict[str, Any]] = None) -> None:
        """Record a complete action-observation pair."""
        self._total_actions += 1
        self._total_tokens += token_usage

        entry = TrajectoryEntry(
            timestamp=time.time(),
            entry_type="action",
            phase=phase,
            iteration=iteration,
            tool_name=tool_name,
            action_type=action_type,
            input_data=input_data,
            output_data=output_data,
            duration_ms=duration_ms,
            token_usage=token_usage,
            metadata=metadata or {},
        )
        self._write_entry(entry)

    def record_phase_transition(self, new_phase: str, iteration: int) -> None:
        """Record a phase transition in the FSM."""
        entry = TrajectoryEntry(
            timestamp=time.time(),
            entry_type="phase_transition",
            phase=new_phase,
            iteration=iteration,
        )
        self._write_entry(entry)

    def record_error(self, error_message: str, phase: str = "",
                     iteration: int = 0, tool_name: str = "") -> None:
        """Record an error event."""
        entry = TrajectoryEntry(
            timestamp=time.time(),
            entry_type="error",
            phase=phase,
            iteration=iteration,
            tool_name=tool_name,
            error=error_message,
        )
        self._write_entry(entry)

    def record_metric(self, metric_name: str, value: Any,
                      phase: str = "", iteration: int = 0) -> None:
        """Record a metric (scores, lengths, etc.)."""
        entry = TrajectoryEntry(
            timestamp=time.time(),
            entry_type="metric",
            phase=phase,
            iteration=iteration,
            metadata={"metric_name": metric_name, "value": value},
        )
        self._write_entry(entry)

    def record_completion(self, status: str, final_stats: dict[str, Any]) -> None:
        """Record session completion."""
        entry = TrajectoryEntry(
            timestamp=time.time(),
            entry_type="session_end",
            metadata={
                "status": status,
                "total_actions": self._total_actions,
                "total_tokens": self._total_tokens,
                "elapsed_seconds": time.time() - self._start_time,
                "stats": final_stats,
            },
        )
        self._write_entry(entry)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the trajectory."""
        return {
            "total_entries": len(self._entries),
            "total_actions": self._total_actions,
            "total_tokens": self._total_tokens,
            "elapsed_seconds": time.time() - self._start_time,
            "output_path": str(self.output_path),
        }

    def _write_entry(self, entry: TrajectoryEntry) -> None:
        """Write an entry to the JSONL file."""
        self._entries.append(entry)
        with open(self.output_path, "a", encoding="utf-8") as f:
            line = json.dumps(entry.to_dict(), ensure_ascii=False)
            f.write(line + "\n")


class EvaluationMetrics:
    """Compute evaluation metrics from trajectory data."""

    def __init__(self, trajectory_path: Path):
        self.trajectory_path = trajectory_path
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """Load trajectory entries from JSONL."""
        if self.trajectory_path.exists():
            with open(self.trajectory_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.entries.append(json.loads(line))

    def total_tokens(self) -> int:
        """Total token usage across all actions."""
        return sum(e.get("token_usage", 0) for e in self.entries)

    def total_actions(self) -> int:
        """Total number of tool actions."""
        return sum(1 for e in self.entries if e.get("entry_type") == "action")

    def total_errors(self) -> int:
        """Total number of errors."""
        return sum(1 for e in self.entries if e.get("entry_type") == "error")

    def phase_transitions(self) -> list[str]:
        """Ordered list of phase transitions."""
        return [
            e["phase"] for e in self.entries
            if e.get("entry_type") == "phase_transition"
        ]

    def average_action_duration(self) -> float:
        """Average duration of tool actions in ms."""
        durations = [e["duration_ms"] for e in self.entries
                     if e.get("entry_type") == "action" and e.get("duration_ms")]
        return sum(durations) / len(durations) if durations else 0.0

    def critique_scores(self) -> list[dict[str, float]]:
        """Extract critique scores from metrics."""
        scores = []
        for e in self.entries:
            if (e.get("entry_type") == "metric" and
                    e.get("metadata", {}).get("metric_name") == "critique_scores"):
                scores.append(e["metadata"]["value"])
        return scores

    def elapsed_time(self) -> float:
        """Total elapsed time in seconds."""
        if len(self.entries) >= 2:
            return self.entries[-1].get("timestamp", 0) - self.entries[0].get("timestamp", 0)
        return 0.0

    def compute_summary(self) -> dict[str, Any]:
        """Compute full evaluation summary."""
        return {
            "total_tokens": self.total_tokens(),
            "total_actions": self.total_actions(),
            "total_errors": self.total_errors(),
            "elapsed_seconds": self.elapsed_time(),
            "average_action_duration_ms": self.average_action_duration(),
            "phase_sequence": self.phase_transitions(),
            "critique_scores": self.critique_scores(),
        }
