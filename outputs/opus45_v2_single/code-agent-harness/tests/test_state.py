"""Tests for the State module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.state import AgentPhase, AgentState, FileBackup, Snapshot, StateStore


class TestAgentPhase:
    """Tests for AgentPhase enum."""

    def test_all_phases_exist(self):
        phases = [
            AgentPhase.INIT,
            AgentPhase.UNDERSTAND,
            AgentPhase.LOCATE,
            AgentPhase.PLAN,
            AgentPhase.EDIT,
            AgentPhase.VERIFY,
            AgentPhase.RETRY,
            AgentPhase.COMPLETE,
            AgentPhase.FAILED,
        ]
        assert len(phases) == 9


class TestFileBackup:
    """Tests for FileBackup dataclass."""

    def test_backup_creation(self):
        backup = FileBackup(path="/test/file.py", original_content="content")
        assert backup.path == "/test/file.py"
        assert backup.original_content == "content"
        assert backup.backup_time > 0

    def test_backup_for_new_file(self):
        backup = FileBackup(path="/test/new.py", original_content=None)
        assert backup.original_content is None


class TestSnapshot:
    """Tests for Snapshot dataclass."""

    def test_snapshot_to_dict(self):
        snapshot = Snapshot(
            snapshot_id="snap_001",
            phase=AgentPhase.EDIT,
            file_backups={},
            context_summary="test summary",
            llm_calls=5,
            retry_count=1,
        )
        d = snapshot.to_dict()
        assert d["snapshot_id"] == "snap_001"
        assert d["phase"] == "EDIT"
        assert d["llm_calls"] == 5

    def test_snapshot_from_dict(self):
        data = {
            "snapshot_id": "snap_002",
            "phase": "VERIFY",
            "file_backups": {},
            "context_summary": "summary",
            "llm_calls": 10,
            "retry_count": 2,
            "timestamp": 12345.0,
            "metadata": {"key": "value"},
        }
        snapshot = Snapshot.from_dict(data)
        assert snapshot.snapshot_id == "snap_002"
        assert snapshot.phase == AgentPhase.VERIFY
        assert snapshot.llm_calls == 10


class TestStateStore:
    """Tests for StateStore."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def state_store(self, temp_dir):
        return StateStore(temp_dir)

    def test_initialization(self, state_store, temp_dir):
        assert state_store.output_dir == Path(temp_dir)
        assert state_store.state.phase == AgentPhase.INIT

    def test_backup_file_existing(self, state_store, temp_dir):
        test_file = Path(temp_dir) / "test.py"
        test_file.write_text("original content")

        state_store.backup_file(str(test_file))

        assert str(test_file) in state_store.file_backups
        assert state_store.file_backups[str(test_file)].original_content == "original content"

    def test_backup_file_nonexistent(self, state_store, temp_dir):
        fake_path = str(Path(temp_dir) / "nonexistent.py")
        state_store.backup_file(fake_path)

        assert fake_path in state_store.file_backups
        assert state_store.file_backups[fake_path].original_content is None

    def test_rollback_file(self, state_store, temp_dir):
        test_file = Path(temp_dir) / "rollback_test.py"
        test_file.write_text("original")

        state_store.backup_file(str(test_file))
        test_file.write_text("modified")

        assert test_file.read_text() == "modified"
        state_store.rollback_file(str(test_file))
        assert test_file.read_text() == "original"

    def test_rollback_all(self, state_store, temp_dir):
        files = []
        for i in range(3):
            f = Path(temp_dir) / f"file{i}.py"
            f.write_text(f"original{i}")
            files.append(f)
            state_store.backup_file(str(f))
            f.write_text(f"modified{i}")

        rolled_back = state_store.rollback_all()

        assert len(rolled_back) == 3
        for i, f in enumerate(files):
            assert f.read_text() == f"original{i}"

    def test_create_snapshot(self, state_store):
        state_store.state.phase = AgentPhase.EDIT
        state_store.state.llm_calls = 5

        snapshot_id = state_store.create_snapshot("test context")

        assert snapshot_id.startswith("snapshot_")
        assert snapshot_id in state_store.snapshots
        assert (state_store.snapshots_dir / f"{snapshot_id}.json").exists()

    def test_restore_snapshot(self, state_store):
        state_store.state.phase = AgentPhase.EDIT
        state_store.state.llm_calls = 5
        snapshot_id = state_store.create_snapshot("before change")

        state_store.state.phase = AgentPhase.VERIFY
        state_store.state.llm_calls = 10

        success = state_store.restore_snapshot(snapshot_id)

        assert success
        assert state_store.state.phase == AgentPhase.EDIT
        assert state_store.state.llm_calls == 5

    def test_can_continue(self, state_store):
        assert state_store.can_continue()

        state_store.state.llm_calls = 100
        assert not state_store.can_continue()

    def test_save_and_load_state(self, state_store, temp_dir):
        state_store.state.task_description = "Test task"
        state_store.state.llm_calls = 7
        state_store.state.phase = AgentPhase.LOCATE

        state_store.save_state()

        new_store = StateStore(temp_dir)
        assert new_store.load_state()
        assert new_store.state.task_description == "Test task"
        assert new_store.state.llm_calls == 7
        assert new_store.state.phase == AgentPhase.LOCATE
