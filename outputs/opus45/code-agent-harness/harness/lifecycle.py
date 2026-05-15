"""
L component - Lifecycle Hooks for backup, validation, and rollback.

Pre/post hooks for:
- File modification (backup before, verify after)
- Test execution (snapshot before)
- Commit (validation before)
- Fix failure (rollback)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import shutil


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""
    bug_id: Optional[str] = None
    file_path: Optional[str] = None
    commit_message: Optional[str] = None
    test_pattern: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class HookResult:
    """Result of a hook execution."""

    def __init__(
        self,
        success: bool,
        message: str = "",
        data: dict | None = None,
        should_abort: bool = False,
    ):
        self.success = success
        self.message = message
        self.data = data or {}
        self.should_abort = should_abort

    @classmethod
    def ok(cls, message: str = "", data: dict | None = None) -> "HookResult":
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str, should_abort: bool = True) -> "HookResult":
        return cls(success=False, message=message, should_abort=should_abort)


class Hook(ABC):
    """Abstract base class for lifecycle hooks."""

    name: str

    @abstractmethod
    def execute(self, context: HookContext) -> HookResult:
        """Execute the hook."""
        pass


class FileBackupHook(Hook):
    """Backs up files before modification."""

    name = "file_backup"

    def __init__(self, backup_dir: Path) -> None:
        self._backup_dir = backup_dir
        self._backups: dict[str, Path] = {}

    def execute(self, context: HookContext) -> HookResult:
        if not context.file_path:
            return HookResult.fail("No file path provided")

        source = Path(context.file_path)
        if not source.exists():
            return HookResult.ok("File does not exist, no backup needed")

        self._backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = context.timestamp.strftime("%Y%m%d_%H%M%S")
        backup_name = f"{source.name}.{timestamp}.bak"
        backup_path = self._backup_dir / backup_name

        shutil.copy2(source, backup_path)
        self._backups[str(source)] = backup_path

        return HookResult.ok(
            f"Backed up {source} to {backup_path}",
            {"backup_path": str(backup_path)},
        )

    def restore(self, file_path: str) -> HookResult:
        """Restore a file from backup."""
        if file_path not in self._backups:
            return HookResult.fail(f"No backup found for {file_path}")

        backup_path = self._backups[file_path]
        if not backup_path.exists():
            return HookResult.fail(f"Backup file missing: {backup_path}")

        shutil.copy2(backup_path, file_path)
        return HookResult.ok(f"Restored {file_path} from {backup_path}")


class TestSnapshotHook(Hook):
    """Creates test state snapshot before running tests."""

    name = "test_snapshot"

    def __init__(self) -> None:
        self._snapshots: list[dict] = []

    def execute(self, context: HookContext) -> HookResult:
        snapshot = {
            "timestamp": context.timestamp.isoformat(),
            "bug_id": context.bug_id,
            "test_pattern": context.test_pattern,
        }
        self._snapshots.append(snapshot)
        return HookResult.ok("Test snapshot created", {"snapshot": snapshot})

    def get_snapshots(self) -> list[dict]:
        return list(self._snapshots)


class CommitValidationHook(Hook):
    """Validates commit before allowing it."""

    name = "commit_validation"

    def __init__(
        self,
        require_bug_id: bool = True,
        require_message: bool = True,
        min_message_length: int = 10,
    ) -> None:
        self._require_bug_id = require_bug_id
        self._require_message = require_message
        self._min_message_length = min_message_length

    def execute(self, context: HookContext) -> HookResult:
        errors = []

        if self._require_bug_id and not context.bug_id:
            errors.append("Commit must be associated with a bug ID")

        if self._require_message:
            if not context.commit_message:
                errors.append("Commit message is required")
            elif len(context.commit_message) < self._min_message_length:
                errors.append(
                    f"Commit message must be at least {self._min_message_length} characters"
                )

        if errors:
            return HookResult.fail("; ".join(errors))

        return HookResult.ok("Commit validation passed")


class RollbackHook(Hook):
    """Handles rollback on fix failure."""

    name = "rollback"

    def __init__(self, backup_hook: FileBackupHook) -> None:
        self._backup_hook = backup_hook
        self._rollback_files: dict[str, list[str]] = {}

    def register_file(self, bug_id: str, file_path: str) -> None:
        """Register a file for potential rollback."""
        if bug_id not in self._rollback_files:
            self._rollback_files[bug_id] = []
        if file_path not in self._rollback_files[bug_id]:
            self._rollback_files[bug_id].append(file_path)

    def execute(self, context: HookContext) -> HookResult:
        if not context.bug_id:
            return HookResult.fail("No bug ID for rollback")

        files = self._rollback_files.get(context.bug_id, [])
        if not files:
            return HookResult.ok("No files to rollback")

        restored = []
        failed = []
        for file_path in files:
            result = self._backup_hook.restore(file_path)
            if result.success:
                restored.append(file_path)
            else:
                failed.append(file_path)

        del self._rollback_files[context.bug_id]

        if failed:
            return HookResult.fail(
                f"Rollback partially failed. Restored: {restored}, Failed: {failed}"
            )

        return HookResult.ok(f"Rolled back {len(restored)} files", {"files": restored})


class HookRegistry:
    """Registry for managing lifecycle hooks."""

    def __init__(self) -> None:
        self._pre_hooks: dict[str, list[Hook]] = {}
        self._post_hooks: dict[str, list[Hook]] = {}

    def register_pre(self, event: str, hook: Hook) -> None:
        """Register a pre-event hook."""
        if event not in self._pre_hooks:
            self._pre_hooks[event] = []
        self._pre_hooks[event].append(hook)

    def register_post(self, event: str, hook: Hook) -> None:
        """Register a post-event hook."""
        if event not in self._post_hooks:
            self._post_hooks[event] = []
        self._post_hooks[event].append(hook)

    def run_pre_hooks(self, event: str, context: HookContext) -> list[HookResult]:
        """Run all pre-event hooks."""
        results = []
        for hook in self._pre_hooks.get(event, []):
            result = hook.execute(context)
            results.append(result)
            if result.should_abort:
                break
        return results

    def run_post_hooks(self, event: str, context: HookContext) -> list[HookResult]:
        """Run all post-event hooks."""
        results = []
        for hook in self._post_hooks.get(event, []):
            result = hook.execute(context)
            results.append(result)
        return results


class LifecycleManager:
    """
    L component - Manages all lifecycle hooks.

    Coordinates file backup, test snapshots, commit validation,
    and rollback operations.
    """

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._backup_dir = work_dir / ".harness" / "backups"

        self.file_backup = FileBackupHook(self._backup_dir)
        self.test_snapshot = TestSnapshotHook()
        self.commit_validation = CommitValidationHook()
        self.rollback = RollbackHook(self.file_backup)

        self.registry = HookRegistry()
        self._setup_default_hooks()

    def _setup_default_hooks(self) -> None:
        """Set up default hook registrations."""
        self.registry.register_pre("file_modify", self.file_backup)
        self.registry.register_pre("test_run", self.test_snapshot)
        self.registry.register_pre("commit", self.commit_validation)

    def before_file_modify(self, file_path: str, bug_id: Optional[str] = None) -> HookResult:
        """Run hooks before modifying a file."""
        context = HookContext(file_path=file_path, bug_id=bug_id)
        results = self.registry.run_pre_hooks("file_modify", context)

        if bug_id:
            self.rollback.register_file(bug_id, file_path)

        return results[0] if results else HookResult.ok()

    def before_test_run(
        self, bug_id: Optional[str] = None, test_pattern: Optional[str] = None
    ) -> HookResult:
        """Run hooks before running tests."""
        context = HookContext(bug_id=bug_id, test_pattern=test_pattern)
        results = self.registry.run_pre_hooks("test_run", context)
        return results[0] if results else HookResult.ok()

    def before_commit(self, bug_id: str, message: str) -> HookResult:
        """Run hooks before committing."""
        context = HookContext(bug_id=bug_id, commit_message=message)
        results = self.registry.run_pre_hooks("commit", context)

        for result in results:
            if not result.success:
                return result
        return HookResult.ok()

    def on_fix_failure(self, bug_id: str) -> HookResult:
        """Handle fix failure with rollback."""
        context = HookContext(bug_id=bug_id)
        return self.rollback.execute(context)

    def clear_rollback_state(self, bug_id: str) -> None:
        """Clear rollback state after successful fix."""
        if bug_id in self.rollback._rollback_files:
            del self.rollback._rollback_files[bug_id]
