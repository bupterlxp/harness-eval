"""
State management for the agent harness.
"""

import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from .schemas import BugReport, FixAttempt, CommitRecord


class BugTracker:
    """Tracks bugs and their status."""

    def __init__(self):
        self.bugs: Dict[int, BugReport] = {}
        self.fix_history: List[FixAttempt] = []
        self.commits: List[CommitRecord] = []
        self.current_bug_id = 1

    def add_bug(self, bug_report: BugReport) -> int:
        """Add a new bug to the tracker."""
        bug_id = self.current_bug_id
        bug_report.bug_id = bug_id
        self.bugs[bug_id] = bug_report
        self.current_bug_id += 1
        return bug_id

    def get_bug(self, bug_id: int) -> Optional[BugReport]:
        """Get a bug by ID."""
        return self.bugs.get(bug_id)

    def list_bugs(self, status: Optional[str] = None) -> List[BugReport]:
        """List all bugs, optionally filtered by status."""
        if status:
            return [b for b in self.bugs.values() if b.status == status]
        return list(self.bugs.values())

    def update_bug_status(self, bug_id: int, status: str) -> bool:
        """Update the status of a bug."""
        if bug_id not in self.bugs:
            return False
        self.bugs[bug_id].status = status
        return True

    def add_fix_attempt(self, fix_attempt: FixAttempt) -> None:
        """Add a fix attempt to history."""
        self.fix_history.append(fix_attempt)

    def add_commit(self, commit_record: CommitRecord) -> None:
        """Add a commit record."""
        self.commits.append(commit_record)


class StateStore:
    """Maintains state and provides snapshot/rollback functionality."""

    def __init__(self, workdir: str = "./harness_state"):
        self.workdir = workdir
        self.snapshots_dir = os.path.join(workdir, "snapshots")
        self._init_directories()

        self.bug_tracker = BugTracker()
        self.current_step = 0
        self.current_state = "INIT"
        self.last_snapshot: Optional[str] = None

    def _init_directories(self) -> None:
        """Initialize required directories."""
        os.makedirs(self.snapshots_dir, exist_ok=True)

    def create_snapshot(self, name: Optional[str] = None) -> str:
        """Create a snapshot of the current state."""
        if not name:
            name = f"snapshot_{datetime.now().isoformat()}_{uuid4().hex[:8]}"

        snapshot_path = os.path.join(self.snapshots_dir, name)
        os.makedirs(snapshot_path, exist_ok=True)

        # Save bug tracker state
        with open(os.path.join(snapshot_path, "bugs.json"), "w") as f:
            json.dump({
                "bugs": {k: v.dict() for k, v in self.bug_tracker.bugs.items()},
                "current_bug_id": self.bug_tracker.current_bug_id
            }, f, indent=2)

        # Save other state
        with open(os.path.join(snapshot_path, "state.json"), "w") as f:
            json.dump({
                "current_step": self.current_step,
                "current_state": self.current_state,
                "last_snapshot": self.last_snapshot
            }, f, indent=2)

        self.last_snapshot = name
        return snapshot_path

    def load_snapshot(self, snapshot_path: str) -> None:
        """Load state from a snapshot."""
        if not os.path.exists(snapshot_path):
            raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

        # Load bug tracker state
        bugs_file = os.path.join(snapshot_path, "bugs.json")
        if os.path.exists(bugs_file):
            with open(bugs_file, "r") as f:
                data = json.load(f)
                self.bug_tracker.bugs = {int(k): BugReport(**v) for k, v in data["bugs"].items()}
                self.bug_tracker.current_bug_id = data["current_bug_id"]

        # Load other state
        state_file = os.path.join(snapshot_path, "state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                data = json.load(f)
                self.current_step = data["current_step"]
                self.current_state = data["current_state"]
                self.last_snapshot = data["last_snapshot"]

    def list_snapshots(self) -> List[str]:
        """List all available snapshots."""
        if not os.path.exists(self.snapshots_dir):
            return []
        return [d for d in os.listdir(self.snapshots_dir) if os.path.isdir(os.path.join(self.snapshots_dir, d))]

    def save_state(self, filepath: str = "harness_state.json") -> None:
        """Save complete state to file."""
        state = {
            "bug_tracker": {
                "bugs": {k: v.dict() for k, v in self.bug_tracker.bugs.items()},
                "current_bug_id": self.bug_tracker.current_bug_id,
                "fix_history": [f.dict() for f in self.bug_tracker.fix_history],
                "commits": [c.dict() for c in self.bug_tracker.commits]
            },
            "current_step": self.current_step,
            "current_state": self.current_state,
            "last_snapshot": self.last_snapshot
        }

        with open(filepath, "w") as f:
            json.dump(state, f, indent=2)

    def load_state(self, filepath: str = "harness_state.json") -> None:
        """Load complete state from file."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"State file not found: {filepath}")

        with open(filepath, "r") as f:
            state = json.load(f)

        # Load bug tracker
        bt_data = state["bug_tracker"]
        self.bug_tracker.bugs = {int(k): BugReport(**v) for k, v in bt_data["bugs"].items()}
        self.bug_tracker.current_bug_id = bt_data["current_bug_id"]
        self.bug_tracker.fix_history = [FixAttempt(**f) for f in bt_data["fix_history"]]
        self.bug_tracker.commits = [CommitRecord(**c) for c in bt_data["commits"]]

        # Load other state
        self.current_step = state["current_step"]
        self.current_state = state["current_state"]
        self.last_snapshot = state["last_snapshot"]