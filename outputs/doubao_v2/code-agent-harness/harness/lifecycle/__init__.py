"""
Lifecycle Hooks component - handles boundary events for task execution
"""

import os
import shutil
import tempfile
from typing import Dict, Any, Optional
from datetime import datetime


class LifecycleHooks:
    """
    Implements lifecycle hooks for task execution:
    - Task start/end events
    - Backup before operations
    - Rollback on failure
    - Timeout handling
    """

    def __init__(self, backup_dir: Optional[str] = None):
        self.backup_dir = backup_dir or tempfile.mkdtemp(prefix="harness_backup_")
        self.task_start_time: Optional[float] = None
        self.task_end_time: Optional[float] = None
        self.current_task_spec: Optional[Dict[str, Any]] = None
        self._create_backup_dir()

    def _create_backup_dir(self):
        """Create backup directory if it doesn't exist"""
        os.makedirs(self.backup_dir, exist_ok=True)

    def on_task_start(self, task_spec: Dict[str, Any]):
        """Called when a task starts"""
        self.task_start_time = datetime.now().timestamp()
        self.current_task_spec = task_spec

        # Create backup of current workspace
        self.backup_workspace("initial_state")

    def on_task_end(self):
        """Called when a task ends"""
        self.task_end_time = datetime.now().timestamp()

        # Cleanup old backups
        self.cleanup_old_backups()

    def on_task_failure(self, error: str):
        """Called when a task fails"""
        print(f"Task failed: {error}")

        # Auto-rollback to initial state
        self.rollback_to_backup("initial_state")

    def on_operation_pre(self, operation_name: str):
        """Called before an operation"""
        # Create backup before making changes
        backup_name = f"pre_{operation_name}_{datetime.now().timestamp()}"
        self.backup_workspace(backup_name)

    def on_operation_post(self, operation_name: str, success: bool = True):
        """Called after an operation"""
        if not success:
            # Rollback if operation failed
            self.rollback_to_last_backup()

    def backup_workspace(self, backup_name: str) -> str:
        """Backup the current workspace state"""
        if not self.current_task_spec:
            return ""

        repo_path = self.current_task_spec.get("repo_path", "./")
        abs_repo_path = os.path.abspath(repo_path)

        # Create backup directory structure
        backup_path = os.path.join(self.backup_dir, backup_name)
        os.makedirs(backup_path, exist_ok=True)

        # Copy important files/directories
        # In a real implementation, this would be more sophisticated
        for item in os.listdir(abs_repo_path):
            if item == ".git":
                continue  # Skip git directory

            src_path = os.path.join(abs_repo_path, item)
            dest_path = os.path.join(backup_path, item)

            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dest_path)

        return backup_path

    def rollback_to_backup(self, backup_name: str) -> bool:
        """Rollback workspace to a specific backup"""
        if not self.current_task_spec:
            return False

        repo_path = self.current_task_spec.get("repo_path", "./")
        abs_repo_path = os.path.abspath(repo_path)
        backup_path = os.path.join(self.backup_dir, backup_name)

        if not os.path.exists(backup_path):
            return False

        # Remove current files
        for item in os.listdir(abs_repo_path):
            if item == ".git":
                continue

            item_path = os.path.join(abs_repo_path, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

        # Restore from backup
        for item in os.listdir(backup_path):
            src_path = os.path.join(backup_path, item)
            dest_path = os.path.join(abs_repo_path, item)

            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path)
            else:
                shutil.copy2(src_path, dest_path)

        return True

    def rollback_to_last_backup(self) -> bool:
        """Rollback to the most recent backup"""
        if not os.path.exists(self.backup_dir):
            return False

        # List all backups and get the most recent one
        backups = sorted(os.listdir(self.backup_dir), key=lambda x: os.path.getmtime(os.path.join(self.backup_dir, x)))
        if not backups:
            return False

        return self.rollback_to_backup(backups[-1])

    def cleanup_old_backups(self, max_age_hours: int = 24):
        """Cleanup old backups"""
        if not os.path.exists(self.backup_dir):
            return

        current_time = datetime.now().timestamp()
        max_age_seconds = max_age_hours * 3600

        for backup_name in os.listdir(self.backup_dir):
            backup_path = os.path.join(self.backup_dir, backup_name)
            if os.path.isdir(backup_path):
                backup_time = os.path.getmtime(backup_path)
                if current_time - backup_time > max_age_seconds:
                    shutil.rmtree(backup_path)

    def get_backup_stats(self) -> Dict[str, Any]:
        """Get statistics about backups"""
        if not os.path.exists(self.backup_dir):
            return {
                "backup_count": 0,
                "total_size_bytes": 0
            }

        backup_count = 0
        total_size = 0

        for backup_name in os.listdir(self.backup_dir):
            backup_path = os.path.join(self.backup_dir, backup_name)
            if os.path.isdir(backup_path):
                backup_count += 1
                for root, dirs, files in os.walk(backup_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        total_size += os.path.getsize(file_path)

        return {
            "backup_count": backup_count,
            "total_size_bytes": total_size,
            "backup_directory": self.backup_dir
        }

    def list_backups(self) -> list:
        """List all available backups"""
        if not os.path.exists(self.backup_dir):
            return []

        backups = []
        for backup_name in os.listdir(self.backup_dir):
            backup_path = os.path.join(self.backup_dir, backup_name)
            if os.path.isdir(backup_path):
                backups.append({
                    "name": backup_name,
                    "timestamp": os.path.getmtime(backup_path),
                    "size": sum(os.path.getsize(os.path.join(backup_path, f)) for f in os.listdir(backup_path) if os.path.isfile(os.path.join(backup_path, f)))
                })

        return sorted(backups, key=lambda x: x["timestamp"], reverse=True)

    def __del__(self):
        """Cleanup backup directory"""
        try:
            if self.backup_dir and os.path.exists(self.backup_dir):
                shutil.rmtree(self.backup_dir)
        except:
            pass