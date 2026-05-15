"""
Lifecycle hooks and utilities.
"""

import os
import shutil
import tempfile
from datetime import datetime
from typing import Dict, Optional, Any, Callable

from .state import StateStore


class FileBackupManager:
    """Manages file backups for rollback functionality."""

    def __init__(self, backup_dir: str = "./harness_backups"):
        self.backup_dir = backup_dir
        os.makedirs(backup_dir, exist_ok=True)
        self.backups: Dict[str, str] = {}  # original_path -> backup_path

    def backup_file(self, file_path: str) -> str:
        """Backup a file to the backup directory."""
        if not os.path.exists(file_path):
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.basename(file_path)
        backup_name = f"{filename}.{timestamp}.backup"
        backup_path = os.path.join(self.backup_dir, backup_name)

        shutil.copy2(file_path, backup_path)
        self.backups[file_path] = backup_path
        return backup_path

    def restore_file(self, file_path: str) -> bool:
        """Restore a file from backup."""
        if file_path not in self.backups:
            return False

        backup_path = self.backups[file_path]
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, file_path)
            return True
        return False

    def cleanup(self) -> None:
        """Clean up all backup files."""
        for backup_path in self.backups.values():
            if os.path.exists(backup_path):
                os.remove(backup_path)
        self.backups.clear()


class LifecycleHooks:
    """Manages pre/post lifecycle hooks."""

    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self.file_backup_manager = FileBackupManager()
        self.pre_fix_hooks: list[Callable[[], None]] = []
        self.post_fix_hooks: list[Callable[[bool], None]] = []
        self.pre_commit_hooks: list[Callable[[], bool]] = []
        self.post_commit_hooks: list[Callable[[str], None]] = []

    def add_pre_fix_hook(self, hook: Callable[[], None]) -> None:
        """Add a hook to run before fixing a bug."""
        self.pre_fix_hooks.append(hook)

    def add_post_fix_hook(self, hook: Callable[[bool], None]) -> None:
        """Add a hook to run after fixing a bug."""
        self.post_fix_hooks.append(hook)

    def add_pre_commit_hook(self, hook: Callable[[], bool]) -> None:
        """Add a hook to run before committing a fix."""
        self.pre_commit_hooks.append(hook)

    def add_post_commit_hook(self, hook: Callable[[str], None]) -> None:
        """Add a hook to run after committing a fix."""
        self.post_commit_hooks.append(hook)

    def run_pre_fix_hooks(self) -> None:
        """Run all pre-fix hooks."""
        for hook in self.pre_fix_hooks:
            hook()

    def run_post_fix_hooks(self, success: bool) -> None:
        """Run all post-fix hooks."""
        for hook in self.post_fix_hooks:
            hook(success)

    def run_pre_commit_hooks(self) -> bool:
        """Run all pre-commit hooks. Return True if all pass."""
        for hook in self.pre_commit_hooks:
            if not hook():
                return False
        return True

    def run_post_commit_hooks(self, commit_hash: str) -> None:
        """Run all post-commit hooks."""
        for hook in self.post_commit_hooks:
            hook(commit_hash)

    def setup_default_hooks(self) -> None:
        """Setup default lifecycle hooks."""

        # Pre-fix hook: create snapshot
        def pre_fix_snapshot():
            self.state_store.create_snapshot(f"pre_fix_{datetime.now().isoformat()}")

        self.add_pre_fix_hook(pre_fix_snapshot)

        # Post-fix hook: validate fix
        def post_fix_validation(success: bool):
            if not success:
                # Rollback to snapshot on failure
                if self.state_store.last_snapshot:
                    self.state_store.load_snapshot(self.state_store.last_snapshot)

        self.add_post_fix_hook(post_fix_validation)

        # Pre-commit hook: run tests
        def pre_commit_test() -> bool:
            from .tools import ToolRegistry
            registry = ToolRegistry()
            result = registry.execute_tool("test_runner")
            return result.success

        self.add_pre_commit_hook(pre_commit_test)

    def backup_file_before_modification(self, file_path: str) -> str:
        """Backup a file before modification."""
        return self.file_backup_manager.backup_file(file_path)

    def cleanup_backups(self) -> None:
        """Clean up all backup files."""
        self.file_backup_manager.cleanup()


def with_backup(file_path: str) -> Callable:
    """Decorator to backup a file before modification."""
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            backup_manager = FileBackupManager()
            backup_path = backup_manager.backup_file(file_path)
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                # Restore from backup on exception
                if os.path.exists(backup_path):
                    shutil.copy2(backup_path, file_path)
                raise e
            finally:
                backup_manager.cleanup()
        return wrapper
    return decorator


def atomic_file_update(file_path: str, new_content: str) -> bool:
    """Atomically update a file's content."""
    try:
        # Write to temporary file first
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(file_path))
        with os.fdopen(fd, 'w') as f:
            f.write(new_content)

        # Rename temporary file to original
        shutil.move(temp_path, file_path)
        return True
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False