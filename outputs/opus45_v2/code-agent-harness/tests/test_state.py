"""Tests for the state module."""

import tempfile
from pathlib import Path

import pytest

from harness.execution import ExecutionContext, ExecutionState
from harness.state import FileBackup, Snapshot, StateStore, TransactionalFileWriter


class TestFileBackup:
    """Tests for FileBackup class."""

    def test_backup_creation(self) -> None:
        """Test creating a file backup."""
        backup = FileBackup(
            path="/tmp/test.txt",
            content="original content",
            existed=True,
        )

        assert backup.path == "/tmp/test.txt"
        assert backup.content == "original content"
        assert backup.existed is True
        assert backup.timestamp > 0


class TestStateStore:
    """Tests for StateStore."""

    def test_store_creation(self) -> None:
        """Test creating a state store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            assert store.storage_dir.exists()

    def test_backup_file(self) -> None:
        """Test backing up a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original")

            backup = store.backup_file(str(test_file))

            assert backup.existed is True
            assert backup.content == "original"

    def test_backup_nonexistent_file(self) -> None:
        """Test backing up a nonexistent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            backup = store.backup_file(str(Path(tmpdir) / "nonexistent.txt"))

            assert backup.existed is False
            assert backup.content is None

    def test_restore_file(self) -> None:
        """Test restoring a file from backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original")
            store.backup_file(str(test_file))

            test_file.write_text("modified")
            assert test_file.read_text() == "modified"

            store.restore_file(str(test_file))
            assert test_file.read_text() == "original"

    def test_snapshot(self) -> None:
        """Test creating a snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            ctx = ExecutionContext(
                task_type="test",
                description="test task",
                repo_path=tmpdir,
                test_command=None,
                constraints=[],
            )

            snapshot_id = store.snapshot(ctx)

            assert snapshot_id.startswith("snapshot_")
            assert len(store.get_snapshots()) == 1

    def test_rollback_to_snapshot(self) -> None:
        """Test rolling back to a snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original")
            store.backup_file(str(test_file))

            ctx = ExecutionContext(
                task_type="test",
                description="test",
                repo_path=tmpdir,
                test_command=None,
                constraints=[],
            )
            snapshot_id = store.snapshot(ctx)

            test_file.write_text("modified")

            success = store.rollback(ctx, snapshot_id)
            assert success
            assert test_file.read_text() == "original"

    def test_get_modified_files(self) -> None:
        """Test getting list of modified files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            file1 = Path(tmpdir) / "file1.txt"
            file2 = Path(tmpdir) / "file2.txt"
            file1.write_text("content1")
            file2.write_text("content2")

            store.backup_file(str(file1))
            store.backup_file(str(file2))

            modified = store.get_modified_files()
            assert len(modified) == 2

    def test_clear(self) -> None:
        """Test clearing state store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)

            ctx = ExecutionContext(
                task_type="test",
                description="test",
                repo_path=tmpdir,
                test_command=None,
                constraints=[],
            )
            store.snapshot(ctx)

            store.clear()

            assert len(store.get_snapshots()) == 0

    def test_load_from_disk(self) -> None:
        """Test loading state from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store1 = StateStore(tmpdir)

            ctx = ExecutionContext(
                task_type="test",
                description="test",
                repo_path=tmpdir,
                test_command=None,
                constraints=[],
            )
            store1.snapshot(ctx)

            store2 = StateStore(tmpdir)
            loaded = store2.load_from_disk()

            assert loaded
            assert len(store2.get_snapshots()) == 1


class TestTransactionalFileWriter:
    """Tests for TransactionalFileWriter."""

    def test_write_file(self) -> None:
        """Test writing a file with backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            writer = TransactionalFileWriter(store)

            test_file = Path(tmpdir) / "test.txt"
            success = writer.write_file(str(test_file), "content")

            assert success
            assert test_file.read_text() == "content"

    def test_transaction_rollback(self) -> None:
        """Test rolling back a transaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            writer = TransactionalFileWriter(store)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("original")

            writer.begin_transaction()
            writer.write_file(str(test_file), "modified")
            writer.rollback()

            assert test_file.read_text() == "original"

    def test_transaction_commit(self) -> None:
        """Test committing a transaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            writer = TransactionalFileWriter(store)

            test_file = Path(tmpdir) / "test.txt"

            writer.begin_transaction()
            writer.write_file(str(test_file), "committed")
            writer.commit()

            assert test_file.read_text() == "committed"
