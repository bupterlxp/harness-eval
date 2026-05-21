"""Evaluation Interface - trajectory recording as JSONL.

Records every action-observation pair as a JSONL line, enabling
offline evaluation, debugging, and replay of agent trajectories.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryEntry:
    """A single action-observation record in the trajectory."""
    step: int
    timestamp: float
    phase: str
    action_type: str  # search | fetch | llm_call | transition | decompose | synthesize | generate
    action_input: dict[str, Any]
    observation: dict[str, Any]
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        record = {
            "step": self.step,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "action_type": self.action_type,
            "action_input": self.action_input,
            "observation": self.observation,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }
        return json.dumps(record, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "TrajectoryEntry":
        """Deserialize from a JSONL line."""
        data = json.loads(line)
        return cls(**data)


class TrajectoryRecorder:
    """Records agent trajectory as JSONL for evaluation."""

    def __init__(self, output_path: Path):
        self._output_path = output_path
        self._entries: list[TrajectoryEntry] = []
        self._step_counter = 0
        self._file_handle = None

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def entries(self) -> list[TrajectoryEntry]:
        return self._entries

    @property
    def step_count(self) -> int:
        return self._step_counter

    def record(
        self,
        phase: str,
        action_type: str,
        action_input: dict[str, Any],
        observation: dict[str, Any],
        duration_ms: float = 0.0,
        success: bool = True,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TrajectoryEntry:
        """Record an action-observation pair."""
        self._step_counter += 1
        entry = TrajectoryEntry(
            step=self._step_counter,
            timestamp=time.time(),
            phase=phase,
            action_type=action_type,
            action_input=action_input,
            observation=observation,
            duration_ms=duration_ms,
            success=success,
            error=error,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self._append_to_file(entry)
        return entry

    def record_transition(self, from_phase: str, to_phase: str, reason: str = "") -> TrajectoryEntry:
        """Record a state transition."""
        return self.record(
            phase=from_phase,
            action_type="transition",
            action_input={"from": from_phase, "to": to_phase, "reason": reason},
            observation={"new_phase": to_phase},
        )

    def record_search(
        self,
        phase: str,
        query: str,
        results: list[dict[str, Any]],
        duration_ms: float = 0.0,
        success: bool = True,
        error: str | None = None,
    ) -> TrajectoryEntry:
        """Record a search action."""
        return self.record(
            phase=phase,
            action_type="search",
            action_input={"query": query},
            observation={"num_results": len(results), "results": results[:5]},  # Keep first 5
            duration_ms=duration_ms,
            success=success,
            error=error,
        )

    def record_fetch(
        self,
        phase: str,
        url: str,
        content_length: int,
        duration_ms: float = 0.0,
        success: bool = True,
        error: str | None = None,
    ) -> TrajectoryEntry:
        """Record a URL fetch action."""
        return self.record(
            phase=phase,
            action_type="fetch",
            action_input={"url": url},
            observation={"content_length": content_length, "success": success},
            duration_ms=duration_ms,
            success=success,
            error=error,
        )

    def record_llm_call(
        self,
        phase: str,
        purpose: str,
        input_summary: str,
        output_summary: str,
        duration_ms: float = 0.0,
        token_usage: dict[str, int] | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> TrajectoryEntry:
        """Record an LLM call."""
        return self.record(
            phase=phase,
            action_type="llm_call",
            action_input={"purpose": purpose, "input_summary": input_summary},
            observation={"output_summary": output_summary, "token_usage": token_usage or {}},
            duration_ms=duration_ms,
            success=success,
            error=error,
            metadata={"token_usage": token_usage or {}},
        )

    def _append_to_file(self, entry: TrajectoryEntry) -> None:
        """Append entry to JSONL file (streaming write)."""
        with open(self._output_path, "a", encoding="utf-8") as f:
            f.write(entry.to_jsonl() + "\n")

    def finalize(self, status: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
        """Write final summary and return evaluation metadata."""
        final_record = {
            "type": "summary",
            "status": status,
            "total_steps": self._step_counter,
            "total_entries": len(self._entries),
            "summary": summary or {},
            "timestamp": time.time(),
        }
        with open(self._output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(final_record, ensure_ascii=False) + "\n")
        return final_record

    @classmethod
    def load(cls, path: Path) -> list[TrajectoryEntry]:
        """Load trajectory entries from a JSONL file."""
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("type") == "summary":
                    continue  # Skip summary records
                entries.append(TrajectoryEntry.from_jsonl(line))
        return entries

    def get_stats(self) -> dict[str, Any]:
        """Get trajectory statistics."""
        action_counts: dict[str, int] = {}
        total_duration = 0.0
        error_count = 0

        for entry in self._entries:
            action_counts[entry.action_type] = action_counts.get(entry.action_type, 0) + 1
            total_duration += entry.duration_ms
            if not entry.success:
                error_count += 1

        return {
            "total_steps": self._step_counter,
            "action_counts": action_counts,
            "total_duration_ms": total_duration,
            "error_count": error_count,
            "error_rate": error_count / max(1, self._step_counter),
        }
