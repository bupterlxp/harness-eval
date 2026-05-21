"""State Store (S) - Persistent state with snapshot and rollback."""

from __future__ import annotations

import copy
import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness.execution import ExecutionContext


@dataclass
class FileBackup:
    """Backup of a file's state."""
    path: str
    content: str | None
    existed: bool
    timestamp: float = field(default_factory=time.time)


@dataclass
class Snapshot:
    """A snapshot of execution state."""
    snapshot_id: str
    timestamp: float
    state_name: str
    iteration: int
    context_data: dict[str, Any]
    file_backups: dict[str, FileBackup]


class StateStore:
    """Persistent state store with snapshot and rollback capabilities."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path.cwd() / ".harness_state"

        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._snapshots: list[Snapshot] = []
        self._file_backups: dict[str, FileBackup] = {}
        self._current_snapshot_id: str | None = None

    def snapshot(self, ctx: ExecutionContext) -> str:
        """Create a snapshot of current state."""
        snapshot_id = f"snapshot_{int(time.time() * 1000)}_{ctx.iteration}"

        context_data = {
            "task_type": ctx.task_type,
            "description": ctx.description,
            "repo_path": ctx.repo_path,
            "test_command": ctx.test_command,
            "constraints": ctx.constraints,
            "current_state": ctx.current_state.name,
            "iteration": ctx.iteration,
            "max_iterations": ctx.max_iterations,
            "max_llm_calls": ctx.max_llm_calls,
            "llm_calls": ctx.llm_calls,
            "understanding": ctx.understanding,
            "located_files": ctx.located_files,
            "plan": ctx.plan,
            "edits": ctx.edits,
            "test_results": ctx.test_results,
            "last_error": ctx.last_error,
            "retry_count": ctx.retry_count,
            "max_retries": ctx.max_retries,
        }

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            timestamp=time.time(),
            state_name=ctx.current_state.name,
            iteration=ctx.iteration,
            context_data=context_data,
            file_backups=copy.deepcopy(self._file_backups),
        )

        self._snapshots.append(snapshot)
        self._current_snapshot_id = snapshot_id

        self._save_snapshot_to_disk(snapshot)

        if len(self._snapshots) > 20:
            old = self._snapshots.pop(0)
            self._remove_snapshot_from_disk(old.snapshot_id)

        return snapshot_id

    def rollback(self, ctx: ExecutionContext, snapshot_id: str | None = None) -> bool:
        """Rollback to a previous snapshot."""
        if not self._snapshots:
            return False

        if snapshot_id:
            target = next((s for s in self._snapshots if s.snapshot_id == snapshot_id), None)
        else:
            target = self._snapshots[-1] if self._snapshots else None

        if not target:
            return False

        for path, backup in target.file_backups.items():
            self._restore_file(backup)

        self._current_snapshot_id = target.snapshot_id

        return True

    def backup_file(self, file_path: str) -> FileBackup:
        """Create a backup of a file before modification."""
        path = Path(file_path)

        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            existed = True
        else:
            content = None
            existed = False

        backup = FileBackup(
            path=str(path.absolute()),
            content=content,
            existed=existed,
        )

        self._file_backups[str(path.absolute())] = backup
        return backup

    def restore_file(self, file_path: str) -> bool:
        """Restore a file from backup."""
        abs_path = str(Path(file_path).absolute())
        if abs_path not in self._file_backups:
            return False

        backup = self._file_backups[abs_path]
        return self._restore_file(backup)

    def get_snapshots(self) -> list[dict[str, Any]]:
        """Get list of available snapshots."""
        return [
            {
                "id": s.snapshot_id,
                "timestamp": s.timestamp,
                "state": s.state_name,
                "iteration": s.iteration,
            }
            for s in self._snapshots
        ]

    def get_latest_snapshot(self) -> Snapshot | None:
        """Get the most recent snapshot."""
        return self._snapshots[-1] if self._snapshots else None

    def load_from_disk(self) -> bool:
        """Load state from disk (for crash recovery)."""
        snapshots_dir = self.storage_dir / "snapshots"
        if not snapshots_dir.exists():
            return False

        loaded = False
        for snapshot_file in sorted(snapshots_dir.glob("*.json")):
            try:
                with open(snapshot_file) as f:
                    data = json.load(f)

                file_backups = {}
                for path, backup_data in data.get("file_backups", {}).items():
                    file_backups[path] = FileBackup(
                        path=backup_data["path"],
                        content=backup_data["content"],
                        existed=backup_data["existed"],
                        timestamp=backup_data.get("timestamp", 0),
                    )

                snapshot = Snapshot(
                    snapshot_id=data["snapshot_id"],
                    timestamp=data["timestamp"],
                    state_name=data["state_name"],
                    iteration=data["iteration"],
                    context_data=data["context_data"],
                    file_backups=file_backups,
                )
                self._snapshots.append(snapshot)
                loaded = True
            except Exception:
                continue

        if self._snapshots:
            self._current_snapshot_id = self._snapshots[-1].snapshot_id

        return loaded

    def clear(self) -> None:
        """Clear all state."""
        self._snapshots.clear()
        self._file_backups.clear()
        self._current_snapshot_id = None

        if self.storage_dir.exists():
            shutil.rmtree(self.storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def get_modified_files(self) -> list[str]:
        """Get list of files that have been backed up."""
        return list(self._file_backups.keys())

    def _restore_file(self, backup: FileBackup) -> bool:
        """Restore a single file from backup."""
        try:
            path = Path(backup.path)

            if backup.existed:
                if backup.content is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(backup.content, encoding="utf-8")
            else:
                if path.exists():
                    path.unlink()

            return True
        except Exception:
            return False

    def _save_snapshot_to_disk(self, snapshot: Snapshot) -> None:
        """Save snapshot to disk for persistence."""
        snapshots_dir = self.storage_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        file_backups_data = {}
        for path, backup in snapshot.file_backups.items():
            file_backups_data[path] = {
                "path": backup.path,
                "content": backup.content,
                "existed": backup.existed,
                "timestamp": backup.timestamp,
            }

        data = {
            "snapshot_id": snapshot.snapshot_id,
            "timestamp": snapshot.timestamp,
            "state_name": snapshot.state_name,
            "iteration": snapshot.iteration,
            "context_data": snapshot.context_data,
            "file_backups": file_backups_data,
        }

        snapshot_file = snapshots_dir / f"{snapshot.snapshot_id}.json"
        with open(snapshot_file, "w") as f:
            json.dump(data, f, indent=2)

    def _remove_snapshot_from_disk(self, snapshot_id: str) -> None:
        """Remove snapshot file from disk."""
        snapshot_file = self.storage_dir / "snapshots" / f"{snapshot_id}.json"
        if snapshot_file.exists():
            snapshot_file.unlink()


class TransactionalFileWriter:
    """Write files with automatic backup and rollback support."""

    def __init__(self, state_store: StateStore) -> None:
        self.state_store = state_store
        self._transaction_files: list[str] = []
        self._in_transaction = False

    def begin_transaction(self) -> None:
        """Begin a new transaction."""
        self._transaction_files.clear()
        self._in_transaction = True

    def write_file(self, file_path: str, content: str) -> bool:
        """Write file with backup."""
        abs_path = str(Path(file_path).absolute())

        self.state_store.backup_file(abs_path)

        if self._in_transaction:
            self._transaction_files.append(abs_path)

        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def commit(self) -> None:
        """Commit current transaction."""
        self._transaction_files.clear()
        self._in_transaction = False

    def rollback(self) -> None:
        """Rollback current transaction."""
        if not self._in_transaction:
            return

        for file_path in reversed(self._transaction_files):
            self.state_store.restore_file(file_path)

        self._transaction_files.clear()
        self._in_transaction = False
