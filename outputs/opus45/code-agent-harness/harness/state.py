"""
S component - State Store for bug tracking, progress, and snapshots.

Responsibilities:
- Maintain bug list with status tracking
- Track fix progress and committed changes
- Provide snapshot/rollback capability at bug level
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import json
import shutil

from harness.schemas import (
    BugReport,
    BugStatus,
    BugSeverity,
    BugCategory,
    CommitRecord,
    FileSnapshot,
    FixAttempt,
)


class BugTracker:
    """Tracks bugs and their fix status."""

    def __init__(self) -> None:
        self._bugs: dict[str, BugReport] = {}
        self._fix_order: list[str] = []

    def add_bug(self, bug: BugReport) -> None:
        """Add a bug to track."""
        self._bugs[bug.id] = bug

    def get_bug(self, bug_id: str) -> Optional[BugReport]:
        """Get a bug by ID."""
        return self._bugs.get(bug_id)

    def get_all_bugs(self) -> list[BugReport]:
        """Get all tracked bugs."""
        return list(self._bugs.values())

    def get_bugs_by_status(self, status: BugStatus) -> list[BugReport]:
        """Get bugs with a specific status."""
        return [b for b in self._bugs.values() if b.status == status]

    def update_status(self, bug_id: str, status: BugStatus) -> bool:
        """Update bug status."""
        if bug_id in self._bugs:
            self._bugs[bug_id].status = status
            return True
        return False

    def set_fix_order(self, order: list[str]) -> None:
        """Set the order in which bugs should be fixed."""
        self._fix_order = order

    def get_next_bug_to_fix(self) -> Optional[BugReport]:
        """Get the next bug to fix based on priority order."""
        for bug_id in self._fix_order:
            bug = self._bugs.get(bug_id)
            if bug and bug.status == BugStatus.PENDING:
                return bug
        for bug in self._bugs.values():
            if bug.status == BugStatus.PENDING:
                return bug
        return None

    def get_progress(self) -> dict:
        """Get current progress statistics."""
        total = len(self._bugs)
        fixed = len(self.get_bugs_by_status(BugStatus.FIXED))
        fixing = len(self.get_bugs_by_status(BugStatus.FIXING))
        blocked = len(self.get_bugs_by_status(BugStatus.BLOCKED))
        pending = len(self.get_bugs_by_status(BugStatus.PENDING))
        return {
            "total": total,
            "fixed": fixed,
            "fixing": fixing,
            "blocked": blocked,
            "pending": pending,
            "progress_pct": (fixed / total * 100) if total > 0 else 0,
        }

    def prioritize_bugs(self) -> list[str]:
        """Sort bugs by severity and return ordered IDs."""
        severity_order = {
            BugSeverity.CRITICAL: 0,
            BugSeverity.HIGH: 1,
            BugSeverity.MEDIUM: 2,
            BugSeverity.LOW: 3,
        }
        category_order = {
            BugCategory.SECURITY: 0,
            BugCategory.TIMING: 1,
            BugCategory.LOGIC: 2,
            BugCategory.CORRECTNESS: 3,
            BugCategory.VALIDATION: 4,
            BugCategory.SPEC: 5,
        }
        sorted_bugs = sorted(
            self._bugs.values(),
            key=lambda b: (severity_order[b.severity], category_order[b.category]),
        )
        order = [b.id for b in sorted_bugs]
        self._fix_order = order
        return order


class SnapshotStore:
    """Manages file snapshots for rollback capability."""

    def __init__(self, snapshot_dir: Path) -> None:
        self._snapshot_dir = snapshot_dir
        self._snapshots: dict[str, dict[str, FileSnapshot]] = {}
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, bug_id: str, files: list[Path]) -> None:
        """Create snapshots of files before modifying them."""
        self._snapshots[bug_id] = {}
        for file_path in files:
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                snapshot = FileSnapshot(
                    path=str(file_path),
                    content=content,
                    timestamp=datetime.now(),
                )
                self._snapshots[bug_id][str(file_path)] = snapshot
                snapshot_path = self._snapshot_dir / bug_id / file_path.name
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                snapshot_path.write_text(content, encoding="utf-8")

    def rollback(self, bug_id: str) -> list[str]:
        """Rollback files to their snapshot state."""
        rolled_back = []
        if bug_id in self._snapshots:
            for path_str, snapshot in self._snapshots[bug_id].items():
                Path(path_str).write_text(snapshot.content, encoding="utf-8")
                rolled_back.append(path_str)
            del self._snapshots[bug_id]
        return rolled_back

    def clear_snapshot(self, bug_id: str) -> None:
        """Clear snapshot after successful fix."""
        if bug_id in self._snapshots:
            snapshot_dir = self._snapshot_dir / bug_id
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)
            del self._snapshots[bug_id]

    def get_snapshot(self, bug_id: str, file_path: str) -> Optional[FileSnapshot]:
        """Get a specific file snapshot."""
        if bug_id in self._snapshots:
            return self._snapshots[bug_id].get(file_path)
        return None


class CommitLog:
    """Tracks committed changes."""

    def __init__(self) -> None:
        self._commits: list[CommitRecord] = []

    def add_commit(self, commit: CommitRecord) -> None:
        """Record a commit."""
        self._commits.append(commit)

    def get_commits(self) -> list[CommitRecord]:
        """Get all commits."""
        return list(self._commits)

    def get_commit_for_bug(self, bug_id: str) -> Optional[CommitRecord]:
        """Get commit associated with a bug."""
        for commit in self._commits:
            if commit.bug_id == bug_id:
                return commit
        return None


class FixHistory:
    """Tracks fix attempts for learning and debugging."""

    def __init__(self) -> None:
        self._attempts: dict[str, list[FixAttempt]] = {}

    def add_attempt(self, attempt: FixAttempt) -> None:
        """Record a fix attempt."""
        if attempt.bug_id not in self._attempts:
            self._attempts[attempt.bug_id] = []
        self._attempts[attempt.bug_id].append(attempt)

    def get_attempts(self, bug_id: str) -> list[FixAttempt]:
        """Get all attempts for a bug."""
        return self._attempts.get(bug_id, [])

    def get_latest_attempt(self, bug_id: str) -> Optional[FixAttempt]:
        """Get the most recent attempt for a bug."""
        attempts = self._attempts.get(bug_id, [])
        return attempts[-1] if attempts else None


class StateStore:
    """
    S component - Unified state management.

    Combines bug tracking, snapshots, commits, and fix history
    with transactional semantics.
    """

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self.bug_tracker = BugTracker()
        self.snapshots = SnapshotStore(work_dir / ".harness" / "snapshots")
        self.commits = CommitLog()
        self.fix_history = FixHistory()
        self._state_file = work_dir / ".harness" / "state.json"

    def save(self) -> None:
        """Persist state to disk."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "bugs": [b.model_dump() for b in self.bug_tracker.get_all_bugs()],
            "fix_order": self.bug_tracker._fix_order,
            "commits": [c.model_dump() for c in self.commits.get_commits()],
        }
        self._state_file.write_text(json.dumps(state, default=str, indent=2))

    def load(self) -> bool:
        """Load state from disk."""
        if not self._state_file.exists():
            return False
        try:
            data = json.loads(self._state_file.read_text())
            for bug_data in data.get("bugs", []):
                bug = BugReport(**bug_data)
                self.bug_tracker.add_bug(bug)
            self.bug_tracker._fix_order = data.get("fix_order", [])
            for commit_data in data.get("commits", []):
                commit = CommitRecord(**commit_data)
                self.commits.add_commit(commit)
            return True
        except Exception:
            return False

    def clear(self) -> None:
        """Clear all state."""
        self.bug_tracker = BugTracker()
        self.snapshots = SnapshotStore(self.work_dir / ".harness" / "snapshots")
        self.commits = CommitLog()
        self.fix_history = FixHistory()
        if self._state_file.exists():
            self._state_file.unlink()
