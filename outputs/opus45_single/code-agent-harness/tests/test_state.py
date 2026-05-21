"""Tests for harness.state module."""

import tempfile
import shutil
from pathlib import Path

import pytest

from harness.state import StateStore, AgentPhase, Snapshot, FileBackup


class TestStateStore:
    """Tests for StateStore functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d)

    @pytest.fixture
    def state_store(self, temp_dir):
        """Create a StateStore instance."""
        return StateStore(temp_dir)

    def test_init_creates_directories(self, temp_dir):
        """Test that initialization creates required directories."""
        store = StateStore(temp_dir)
        assert store.state_dir.exists()
        assert store.backup_dir.exists()

    def test_phase_transitions(self, state_store):
        """Test phase transitions are tracked."""
        assert state_store.current_phase == AgentPhase.INIT

        state_store.set_phase(AgentPhase.UNDERSTAND)
        assert state_store.current_phase == AgentPhase.UNDERSTAND

        state_store.set_phase(AgentPhase.LOCATE)
        assert state_store.current_phase == AgentPhase.LOCATE

    def test_iteration_counter(self, state_store):
        """Test iteration counter increments correctly."""
        assert state_store.iteration == 0

        assert state_store.increment_iteration() == 1
        assert state_store.increment_iteration() == 2
        assert state_store.iteration == 2

    def test_file_backup_and_restore(self, state_store, temp_dir):
        """Test file backup and restore functionality."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("original content")

        backup = state_store.backup_file(test_file)
        assert backup is not None
        assert backup.existed is True

        test_file.write_text("modified content")
        assert test_file.read_text() == "modified content"

        restored = state_store.restore_file(test_file)
        assert restored is True
        assert test_file.read_text() == "original content"

    def test_backup_nonexistent_file(self, state_store, temp_dir):
        """Test backup of a file that doesn't exist."""
        new_file = temp_dir / "new.txt"
        assert not new_file.exists()

        backup = state_store.backup_file(new_file)
        assert backup is not None
        assert backup.existed is False

        new_file.write_text("new content")
        assert new_file.exists()

        state_store.restore_file(new_file)
        assert not new_file.exists()

    def test_snapshot_creation(self, state_store, temp_dir):
        """Test snapshot creation."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        state_store.backup_file(test_file)
        state_store.set_phase(AgentPhase.EDIT)

        snapshot = state_store.create_snapshot("test_snapshot")
        assert snapshot.snapshot_id == "test_snapshot"
        assert snapshot.phase == "edit"
        assert len(snapshot.file_backups) == 1

    def test_rollback_to_snapshot(self, state_store, temp_dir):
        """Test rollback to a snapshot."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("original")

        state_store.backup_file(test_file)
        state_store.set_phase(AgentPhase.EDIT)
        state_store.create_snapshot("before_edit")

        test_file.write_text("modified")
        state_store.set_phase(AgentPhase.VERIFY)

        success = state_store.rollback_to_snapshot("before_edit")
        assert success is True
        assert state_store.current_phase == AgentPhase.EDIT

    def test_metadata_storage(self, state_store):
        """Test metadata storage and retrieval."""
        state_store.set_metadata("key1", "value1")
        state_store.set_metadata("key2", {"nested": "data"})

        assert state_store.get_metadata("key1") == "value1"
        assert state_store.get_metadata("key2") == {"nested": "data"}
        assert state_store.get_metadata("missing", "default") == "default"

    def test_modified_files_tracking(self, state_store, temp_dir):
        """Test tracking of modified files."""
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        state_store.backup_file(file1)
        state_store.backup_file(file2)

        modified = state_store.get_modified_files()
        assert len(modified) == 2
        assert str(file1.resolve()) in modified
        assert str(file2.resolve()) in modified

    def test_rollback_all_files(self, state_store, temp_dir):
        """Test rolling back all modified files."""
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"
        file1.write_text("original1")
        file2.write_text("original2")

        state_store.backup_file(file1)
        state_store.backup_file(file2)

        file1.write_text("modified1")
        file2.write_text("modified2")

        count = state_store.rollback_all_files()
        assert count == 2
        assert file1.read_text() == "original1"
        assert file2.read_text() == "original2"

    def test_state_persistence(self, temp_dir):
        """Test that state persists across instances."""
        store1 = StateStore(temp_dir)
        store1.set_phase(AgentPhase.VERIFY)
        store1.set_metadata("test", "data")
        store1.increment_iteration()

        store2 = StateStore(temp_dir)
        assert store2.current_phase == AgentPhase.VERIFY
        assert store2.get_metadata("test") == "data"
        assert store2.iteration == 1

    def test_cleanup(self, state_store, temp_dir):
        """Test cleanup removes all state."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")
        state_store.backup_file(test_file)

        state_dir = state_store.state_dir
        assert state_dir.exists()

        state_store.cleanup()
        assert not state_dir.exists()


class TestAgentPhase:
    """Tests for AgentPhase enum."""

    def test_all_phases_defined(self):
        """Test all required phases exist."""
        phases = [
            AgentPhase.INIT,
            AgentPhase.UNDERSTAND,
            AgentPhase.LOCATE,
            AgentPhase.PLAN,
            AgentPhase.EDIT,
            AgentPhase.VERIFY,
            AgentPhase.RETRY,
            AgentPhase.COMPLETE,
            AgentPhase.FAILED
        ]
        assert len(phases) == 9

    def test_phase_values(self):
        """Test phase string values."""
        assert AgentPhase.INIT.value == "init"
        assert AgentPhase.COMPLETE.value == "complete"
        assert AgentPhase.FAILED.value == "failed"
