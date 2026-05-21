"""
State Store (S) - Persistent runtime state with snapshot and rollback capabilities.

Supports:
- State snapshots at any point
- Rollback to previous snapshots
- File modification tracking with undo
- Crash recovery from last snapshot
"""

from __future__ import annotations

import json
import shutil
import hashlib
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from enum import Enum


class AgentPhase(Enum):
    """Explicit phases in the agent state machine."""
    INIT = "init"
    UNDERSTAND = "understand"
    LOCATE = "locate"
    PLAN = "plan"
    EDIT = "edit"
    VERIFY = "verify"
    RETRY = "retry"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class FileBackup:
    """Tracks a single file's backup state."""
    original_path: str
    backup_path: str
    original_hash: str
    existed: bool


@dataclass
class Snapshot:
    """A point-in-time snapshot of agent state."""
    snapshot_id: str
    timestamp: float
    phase: str
    iteration: int
    file_backups: list[FileBackup]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "iteration": self.iteration,
            "file_backups": [asdict(fb) for fb in self.file_backups],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        return cls(
            snapshot_id=data["snapshot_id"],
            timestamp=data["timestamp"],
            phase=data["phase"],
            iteration=data["iteration"],
            file_backups=[FileBackup(**fb) for fb in data["file_backups"]],
            metadata=data.get("metadata", {}),
        )


class StateStore:
    """
    Manages persistent state with snapshot/rollback capabilities.

    Features:
    - Automatic file backup before modifications
    - Named snapshots for recovery points
    - Full rollback to any snapshot
    - Crash recovery support
    """

    def __init__(self, work_dir: Path, state_dir: Path | None = None):
        self.work_dir = Path(work_dir).resolve()
        self.state_dir = Path(state_dir) if state_dir else self.work_dir / ".harness_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.state_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)

        self.current_phase = AgentPhase.INIT
        self.iteration = 0
        self.snapshots: list[Snapshot] = []
        self.active_file_backups: dict[str, FileBackup] = {}
        self.metadata: dict[str, Any] = {}

        self._load_state()

    def _state_file(self) -> Path:
        return self.state_dir / "state.json"

    def _load_state(self) -> None:
        """Load state from disk if exists (crash recovery)."""
        state_file = self._state_file()
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                self.current_phase = AgentPhase(data.get("current_phase", "init"))
                self.iteration = data.get("iteration", 0)
                self.snapshots = [Snapshot.from_dict(s) for s in data.get("snapshots", [])]
                self.metadata = data.get("metadata", {})
                for fb_data in data.get("active_file_backups", []):
                    fb = FileBackup(**fb_data)
                    self.active_file_backups[fb.original_path] = fb
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_state(self) -> None:
        """Persist state to disk."""
        data = {
            "current_phase": self.current_phase.value,
            "iteration": self.iteration,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "active_file_backups": [asdict(fb) for fb in self.active_file_backups.values()],
            "metadata": self.metadata,
        }
        self._state_file().write_text(json.dumps(data, indent=2))

    def _file_hash(self, path: Path) -> str:
        """Compute hash of file contents."""
        if not path.exists():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]

    def set_phase(self, phase: AgentPhase) -> None:
        """Transition to a new phase."""
        self.current_phase = phase
        self._save_state()

    def increment_iteration(self) -> int:
        """Increment and return the iteration counter."""
        self.iteration += 1
        self._save_state()
        return self.iteration

    def backup_file(self, file_path: str | Path) -> FileBackup | None:
        """Create a backup of a file before modification."""
        path = Path(file_path).resolve()
        path_str = str(path)

        if path_str in self.active_file_backups:
            return self.active_file_backups[path_str]

        backup_name = f"{path.name}_{self._file_hash(path)}_{int(time.time() * 1000)}"
        backup_path = self.backup_dir / backup_name

        existed = path.exists()
        original_hash = ""

        if existed:
            shutil.copy2(path, backup_path)
            original_hash = self._file_hash(path)

        fb = FileBackup(
            original_path=path_str,
            backup_path=str(backup_path),
            original_hash=original_hash,
            existed=existed,
        )
        self.active_file_backups[path_str] = fb
        self._save_state()
        return fb

    def restore_file(self, file_path: str | Path) -> bool:
        """Restore a single file from backup."""
        path_str = str(Path(file_path).resolve())

        if path_str not in self.active_file_backups:
            return False

        fb = self.active_file_backups[path_str]
        target = Path(fb.original_path)

        if fb.existed:
            backup = Path(fb.backup_path)
            if backup.exists():
                shutil.copy2(backup, target)
        else:
            if target.exists():
                target.unlink()

        del self.active_file_backups[path_str]
        self._save_state()
        return True

    def create_snapshot(self, name: str = "") -> Snapshot:
        """Create a named snapshot of current state."""
        snapshot_id = name or f"snap_{int(time.time() * 1000)}"

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            timestamp=time.time(),
            phase=self.current_phase.value,
            iteration=self.iteration,
            file_backups=list(self.active_file_backups.values()),
            metadata=dict(self.metadata),
        )
        self.snapshots.append(snapshot)
        self._save_state()
        return snapshot

    def rollback_to_snapshot(self, snapshot_id: str) -> bool:
        """Rollback all state to a specific snapshot."""
        target_snapshot = None
        target_idx = -1

        for idx, snap in enumerate(self.snapshots):
            if snap.snapshot_id == snapshot_id:
                target_snapshot = snap
                target_idx = idx
                break

        if target_snapshot is None:
            return False

        for path_str in list(self.active_file_backups.keys()):
            self.restore_file(path_str)

        for fb in target_snapshot.file_backups:
            self.active_file_backups[fb.original_path] = fb

        self.current_phase = AgentPhase(target_snapshot.phase)
        self.iteration = target_snapshot.iteration
        self.metadata = dict(target_snapshot.metadata)
        self.snapshots = self.snapshots[:target_idx + 1]

        self._save_state()
        return True

    def rollback_all_files(self) -> int:
        """Rollback all modified files to their original state."""
        count = 0
        for path_str in list(self.active_file_backups.keys()):
            if self.restore_file(path_str):
                count += 1
        return count

    def get_modified_files(self) -> list[str]:
        """Get list of files that have been backed up (modified)."""
        return list(self.active_file_backups.keys())

    def set_metadata(self, key: str, value: Any) -> None:
        """Store arbitrary metadata."""
        self.metadata[key] = value
        self._save_state()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Retrieve metadata."""
        return self.metadata.get(key, default)

    def cleanup(self) -> None:
        """Remove all state and backup files."""
        if self.state_dir.exists():
            shutil.rmtree(self.state_dir)
