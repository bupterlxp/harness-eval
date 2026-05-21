"""
State Store (S) - Manages persistent state with snapshot and rollback capabilities.

Responsibilities:
- Snapshot creation and restoration
- File modification tracking and rollback
- Crash recovery from last snapshot
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any


class AgentPhase(Enum):
    """Phases in the agent state machine."""
    INIT = auto()
    UNDERSTAND = auto()
    LOCATE = auto()
    PLAN = auto()
    EDIT = auto()
    VERIFY = auto()
    RETRY = auto()
    COMPLETE = auto()
    FAILED = auto()


@dataclass
class FileBackup:
    """Tracks a file's original state for rollback."""
    path: str
    original_content: str | None  # None means file didn't exist
    backup_time: float = field(default_factory=time.time)


@dataclass
class Snapshot:
    """A snapshot of the agent's state at a point in time."""
    snapshot_id: str
    phase: AgentPhase
    file_backups: dict[str, FileBackup]
    context_summary: str
    llm_calls: int
    retry_count: int
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "phase": self.phase.name,
            "file_backups": {
                k: {"path": v.path, "original_content": v.original_content, "backup_time": v.backup_time}
                for k, v in self.file_backups.items()
            },
            "context_summary": self.context_summary,
            "llm_calls": self.llm_calls,
            "retry_count": self.retry_count,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        return cls(
            snapshot_id=data["snapshot_id"],
            phase=AgentPhase[data["phase"]],
            file_backups={
                k: FileBackup(path=v["path"], original_content=v["original_content"], backup_time=v["backup_time"])
                for k, v in data["file_backups"].items()
            },
            context_summary=data["context_summary"],
            llm_calls=data["llm_calls"],
            retry_count=data["retry_count"],
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class AgentState:
    """Current state of the agent."""
    phase: AgentPhase = AgentPhase.INIT
    task_description: str = ""
    repo_path: str = ""
    test_command: str | None = None
    constraints: list[str] = field(default_factory=list)

    # Tracking
    llm_calls: int = 0
    retry_count: int = 0
    max_retries: int = 5
    max_llm_calls: int = 50

    # Results
    modified_files: list[str] = field(default_factory=list)
    test_results: dict[str, Any] = field(default_factory=dict)
    error_messages: list[str] = field(default_factory=list)

    # Context
    understanding: str = ""
    located_files: list[str] = field(default_factory=list)
    current_plan: list[str] = field(default_factory=list)


class StateStore:
    """Manages agent state with snapshot/rollback capabilities."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.snapshots_dir = self.output_dir / ".snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        self.state = AgentState()
        self.file_backups: dict[str, FileBackup] = {}
        self.snapshots: list[str] = []
        self._snapshot_counter = 0

    def backup_file(self, file_path: str) -> None:
        """Create a backup of a file before modification."""
        if file_path in self.file_backups:
            return  # Already backed up

        path = Path(file_path)
        if path.exists():
            original_content = path.read_text(encoding="utf-8", errors="replace")
        else:
            original_content = None

        self.file_backups[file_path] = FileBackup(
            path=file_path,
            original_content=original_content,
        )

    def rollback_file(self, file_path: str) -> bool:
        """Rollback a single file to its original state."""
        if file_path not in self.file_backups:
            return False

        backup = self.file_backups[file_path]
        path = Path(file_path)

        if backup.original_content is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(backup.original_content, encoding="utf-8")

        return True

    def rollback_all(self) -> list[str]:
        """Rollback all modified files to their original state."""
        rolled_back = []
        for file_path in list(self.file_backups.keys()):
            if self.rollback_file(file_path):
                rolled_back.append(file_path)
        self.file_backups.clear()
        self.state.modified_files.clear()
        return rolled_back

    def create_snapshot(self, context_summary: str = "") -> str:
        """Create a snapshot of current state."""
        self._snapshot_counter += 1
        snapshot_id = f"snapshot_{self._snapshot_counter:04d}"

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            phase=self.state.phase,
            file_backups=dict(self.file_backups),
            context_summary=context_summary,
            llm_calls=self.state.llm_calls,
            retry_count=self.state.retry_count,
            metadata={
                "modified_files": list(self.state.modified_files),
                "located_files": list(self.state.located_files),
            },
        )

        snapshot_path = self.snapshots_dir / f"{snapshot_id}.json"
        snapshot_path.write_text(json.dumps(snapshot.to_dict(), indent=2))
        self.snapshots.append(snapshot_id)

        return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore state from a snapshot."""
        snapshot_path = self.snapshots_dir / f"{snapshot_id}.json"
        if not snapshot_path.exists():
            return False

        data = json.loads(snapshot_path.read_text())
        snapshot = Snapshot.from_dict(data)

        # Rollback files to snapshot state
        current_backups = set(self.file_backups.keys())
        snapshot_backups = set(snapshot.file_backups.keys())

        # Restore files that were modified after snapshot
        for file_path in current_backups - snapshot_backups:
            self.rollback_file(file_path)

        self.file_backups = snapshot.file_backups
        self.state.phase = snapshot.phase
        self.state.llm_calls = snapshot.llm_calls
        self.state.retry_count = snapshot.retry_count
        self.state.modified_files = snapshot.metadata.get("modified_files", [])
        self.state.located_files = snapshot.metadata.get("located_files", [])

        return True

    def get_latest_snapshot(self) -> str | None:
        """Get the ID of the most recent snapshot."""
        if not self.snapshots:
            return None
        return self.snapshots[-1]

    def recover_from_crash(self) -> bool:
        """Attempt to recover from the last saved snapshot."""
        snapshot_files = sorted(self.snapshots_dir.glob("snapshot_*.json"))
        if not snapshot_files:
            return False

        latest = snapshot_files[-1].stem
        return self.restore_snapshot(latest)

    def can_continue(self) -> bool:
        """Check if agent is within budget limits."""
        return (
            self.state.llm_calls < self.state.max_llm_calls
            and self.state.retry_count < self.state.max_retries
        )

    def increment_llm_calls(self) -> None:
        """Track an LLM call."""
        self.state.llm_calls += 1

    def increment_retry(self) -> None:
        """Track a retry attempt."""
        self.state.retry_count += 1

    def set_phase(self, phase: AgentPhase) -> None:
        """Update the current phase."""
        self.state.phase = phase

    def save_state(self) -> None:
        """Persist current state to disk."""
        state_path = self.output_dir / "agent_state.json"
        state_data = {
            "phase": self.state.phase.name,
            "task_description": self.state.task_description,
            "repo_path": self.state.repo_path,
            "test_command": self.state.test_command,
            "constraints": self.state.constraints,
            "llm_calls": self.state.llm_calls,
            "retry_count": self.state.retry_count,
            "modified_files": self.state.modified_files,
            "test_results": self.state.test_results,
            "error_messages": self.state.error_messages,
            "snapshots": self.snapshots,
        }
        state_path.write_text(json.dumps(state_data, indent=2))

    def load_state(self) -> bool:
        """Load state from disk."""
        state_path = self.output_dir / "agent_state.json"
        if not state_path.exists():
            return False

        data = json.loads(state_path.read_text())
        self.state.phase = AgentPhase[data["phase"]]
        self.state.task_description = data["task_description"]
        self.state.repo_path = data["repo_path"]
        self.state.test_command = data.get("test_command")
        self.state.constraints = data.get("constraints", [])
        self.state.llm_calls = data["llm_calls"]
        self.state.retry_count = data["retry_count"]
        self.state.modified_files = data.get("modified_files", [])
        self.state.test_results = data.get("test_results", {})
        self.state.error_messages = data.get("error_messages", [])
        self.snapshots = data.get("snapshots", [])

        return True
