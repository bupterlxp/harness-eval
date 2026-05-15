"""Tests for fix rollback functionality."""

import pytest
from pathlib import Path
import tempfile
import shutil

from harness.state import SnapshotStore, StateStore
from harness.lifecycle import (
    FileBackupHook,
    RollbackHook,
    LifecycleManager,
    HookContext,
)


class TestSnapshotStore:
    """Tests for the snapshot store."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path)

    def test_create_snapshot(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("original content")

        snapshot_dir = temp_dir / "snapshots"
        store = SnapshotStore(snapshot_dir)
        store.create_snapshot("bug_1", [test_file])

        assert "bug_1" in store._snapshots
        assert str(test_file) in store._snapshots["bug_1"]
        assert store._snapshots["bug_1"][str(test_file)].content == "original content"

    def test_rollback(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("original content")

        snapshot_dir = temp_dir / "snapshots"
        store = SnapshotStore(snapshot_dir)
        store.create_snapshot("bug_1", [test_file])

        test_file.write_text("modified content")
        assert test_file.read_text() == "modified content"

        rolled_back = store.rollback("bug_1")
        assert str(test_file) in rolled_back
        assert test_file.read_text() == "original content"

    def test_clear_snapshot(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("content")

        snapshot_dir = temp_dir / "snapshots"
        store = SnapshotStore(snapshot_dir)
        store.create_snapshot("bug_1", [test_file])

        store.clear_snapshot("bug_1")
        assert "bug_1" not in store._snapshots


class TestFileBackupHook:
    """Tests for file backup hook."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path)

    def test_backup_creates_file(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("original")

        backup_dir = temp_dir / "backups"
        hook = FileBackupHook(backup_dir)

        ctx = HookContext(file_path=str(test_file))
        result = hook.execute(ctx)

        assert result.success
        assert str(test_file) in hook._backups

    def test_restore_from_backup(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("original")

        backup_dir = temp_dir / "backups"
        hook = FileBackupHook(backup_dir)

        ctx = HookContext(file_path=str(test_file))
        hook.execute(ctx)

        test_file.write_text("modified")
        result = hook.restore(str(test_file))

        assert result.success
        assert test_file.read_text() == "original"


class TestRollbackHook:
    """Tests for rollback hook."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path)

    def test_rollback_registered_files(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("original")

        backup_dir = temp_dir / "backups"
        backup_hook = FileBackupHook(backup_dir)
        rollback_hook = RollbackHook(backup_hook)

        ctx = HookContext(file_path=str(test_file), bug_id="bug_1")
        backup_hook.execute(ctx)
        rollback_hook.register_file("bug_1", str(test_file))

        test_file.write_text("modified")

        result = rollback_hook.execute(HookContext(bug_id="bug_1"))
        assert result.success
        assert test_file.read_text() == "original"


class TestLifecycleManager:
    """Tests for lifecycle manager."""

    @pytest.fixture
    def temp_dir(self):
        path = Path(tempfile.mkdtemp())
        yield path
        shutil.rmtree(path)

    def test_before_file_modify(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("content")

        manager = LifecycleManager(temp_dir)
        result = manager.before_file_modify(str(test_file), "bug_1")

        assert result.success

    def test_on_fix_failure_rollback(self, temp_dir):
        test_file = temp_dir / "test.py"
        test_file.write_text("original")

        manager = LifecycleManager(temp_dir)
        manager.before_file_modify(str(test_file), "bug_1")

        test_file.write_text("broken")

        result = manager.on_fix_failure("bug_1")
        assert result.success
        assert test_file.read_text() == "original"
