"""Evaluation Interface — trajectory recording as JSONL."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class TrajectoryEntry:
    """A single action-observation record for the trajectory JSONL."""

    step: int
    timestamp: float
    thought: str
    action: str
    action_input: dict[str, Any]
    observation: str
    success: bool
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> TrajectoryEntry:
        """Deserialize from a JSON line."""
        data = json.loads(line)
        return cls(**data)


@dataclass
class RunSummary:
    """Summary record written at the end of a trajectory."""

    status: str  # success, partial, failed
    total_steps: int
    total_duration_ms: float
    tools_used: dict[str, int]
    files_modified: list[str]
    error_count: int
    final_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line."""
        data = asdict(self)
        data["_type"] = "summary"
        return json.dumps(data, ensure_ascii=False)


class TrajectoryRecorder:
    """Records agent execution trajectory as JSONL.

    Each line in the output file is a complete action-observation record.
    The final line is a summary record.
    """

    def __init__(self, output_path: Path | str) -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[TrajectoryEntry] = []
        self._start_time: float = time.time()
        self._tool_counts: dict[str, int] = {}
        self._error_count: int = 0
        self._file_handle = open(self.output_path, "w")

    def record_step(
        self,
        step: int,
        thought: str,
        action: str,
        action_input: dict[str, Any],
        observation: str,
        success: bool,
        duration_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> TrajectoryEntry:
        """Record a single step and write it to the JSONL file."""
        entry = TrajectoryEntry(
            step=step,
            timestamp=time.time(),
            thought=thought,
            action=action,
            action_input=action_input,
            observation=observation,
            success=success,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        self._tool_counts[action] = self._tool_counts.get(action, 0) + 1
        if not success:
            self._error_count += 1

        # Write immediately (append)
        self._file_handle.write(entry.to_jsonl() + "\n")
        self._file_handle.flush()

        return entry

    def write_summary(
        self,
        status: str,
        files_modified: list[str],
        final_message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> RunSummary:
        """Write the final summary record."""
        total_duration = (time.time() - self._start_time) * 1000
        summary = RunSummary(
            status=status,
            total_steps=len(self._entries),
            total_duration_ms=total_duration,
            tools_used=self._tool_counts.copy(),
            files_modified=files_modified,
            error_count=self._error_count,
            final_message=final_message,
            metadata=metadata or {},
        )
        self._file_handle.write(summary.to_jsonl() + "\n")
        self._file_handle.flush()
        return summary

    def close(self) -> None:
        """Close the output file."""
        if self._file_handle and not self._file_handle.closed:
            self._file_handle.close()

    @property
    def step_count(self) -> int:
        return len(self._entries)

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def entries(self) -> list[TrajectoryEntry]:
        return self._entries.copy()

    def __del__(self) -> None:
        self.close()

    @staticmethod
    def load_trajectory(path: Path | str) -> list[dict[str, Any]]:
        """Load and parse a trajectory JSONL file."""
        entries = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
