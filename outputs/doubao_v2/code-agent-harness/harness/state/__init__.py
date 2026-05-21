"""
State Store component - persists runtime state and supports snapshot/rollback
"""

import os
import json
import shutil
import tempfile
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class StateSnapshot:
    """Represents a snapshot of system state at a point in time"""
    timestamp: float
    description: str
    state_data: Dict[str, Any]
    file_changes: Dict[str, str] = field(default_factory=dict)  # path -> hash


class StateStore:
    """
    Manages system state with snapshot and rollback capabilities
    Tracks file changes for easy rollback
    """

    def __init__(self, working_dir: Optional[str] = None):
        self.working_dir = working_dir or os.getcwd()
        self.snapshots: List[StateSnapshot] = []
        self.current_state: Dict[str, Any] = {}
        self.temp_dir: Optional[str] = None
        self._initialize_temp_dir()

    def _initialize_temp_dir(self):
        """Initialize temporary directory for storing file backups"""
        self.temp_dir = tempfile.mkdtemp(prefix="harness_state_")

    def _get_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of a file"""
        import hashlib

        if not os.path.exists(file_path):
            return ""

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _backup_file(self, file_path: str) -> str:
        """Backup a file to temporary storage and return backup path"""
        if not os.path.exists(file_path):
            return ""

        rel_path = os.path.relpath(file_path, self.working_dir)
        backup_path = os.path.join(self.temp_dir, rel_path)

        # Create directory structure
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        # Copy file
        shutil.copy2(file_path, backup_path)
        return backup_path

    def create_snapshot(self, description: str = "") -> str:
        """Create a snapshot of current state"""
        # Create snapshot of current state data
        snapshot_data = {
            "current_state": self.current_state.copy(),
            "timestamp": datetime.now().isoformat()
        }

        # Track file changes
        file_changes: Dict[str, str] = {}

        # In a real implementation, we would track all modified files
        # For now, we'll just capture the current working directory state
        # This would be replaced with actual file change tracking

        snapshot = StateSnapshot(
            timestamp=datetime.now().timestamp(),
            description=description,
            state_data=snapshot_data,
            file_changes=file_changes
        )

        self.snapshots.append(snapshot)
        return snapshot.timestamp

    def save_state(self, key: str, value: Any):
        """Save a value to the current state"""
        self.current_state[key] = value

    def load_state(self, key: str, default: Any = None) -> Any:
        """Load a value from the current state"""
        return self.current_state.get(key, default)

    def get_state(self) -> Dict[str, Any]:
        """Get full current state"""
        return self.current_state.copy()

    def rollback_to_snapshot(self, timestamp: Optional[float] = None) -> bool:
        """Rollback to a specific snapshot or the most recent one"""
        if not self.snapshots:
            return False

        target_snapshot: Optional[StateSnapshot] = None

        if timestamp is None:
            # Rollback to last snapshot
            target_snapshot = self.snapshots[-1]
        else:
            # Find snapshot with matching timestamp
            for snapshot in reversed(self.snapshots):
                if snapshot.timestamp == timestamp:
                    target_snapshot = snapshot
                    break

        if not target_snapshot:
            return False

        # Restore state data
        self.current_state = target_snapshot.state_data.get("current_state", {})

        # Restore files from backup
        # In a real implementation, we would restore files from backups
        # For now, this is a placeholder

        return True

    def rollback_to_last_snapshot(self) -> bool:
        """Rollback to the most recent snapshot"""
        return self.rollback_to_snapshot()

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """List all available snapshots"""
        return [{
            "timestamp": s.timestamp,
            "description": s.description,
            "state_size": len(json.dumps(s.state_data)),
            "file_changes_count": len(s.file_changes)
        } for s in self.snapshots]

    def clear_snapshots(self):
        """Clear all snapshots"""
        self.snapshots = []
        # Also cleanup temp directory
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        self._initialize_temp_dir()

    def track_file_change(self, file_path: str):
        """Track that a file has been modified"""
        # This would be called whenever a file is modified
        # For now, just backup the file
        rel_path = os.path.relpath(file_path, self.working_dir)
        backup_path = os.path.join(self.temp_dir, rel_path)

        if os.path.exists(file_path):
            self._backup_file(file_path)

    def get_file_backup(self, file_path: str) -> Optional[str]:
        """Get backup path for a file if it exists"""
        rel_path = os.path.relpath(file_path, self.working_dir)
        backup_path = os.path.join(self.temp_dir, rel_path)

        if os.path.exists(backup_path):
            return backup_path
        return None

    def __del__(self):
        """Cleanup temporary directory"""
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except:
            pass
