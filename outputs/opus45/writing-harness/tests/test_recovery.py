"""
test_recovery.py - Tests for S component crash recovery

Tests snapshot/commit/recover operations and crash recovery scenarios.
"""

import pytest
import tempfile
from pathlib import Path

from harness.state import StateStore, SessionNotFoundError, SnapshotNotFoundError
from harness.schemas import SessionState, ExecutionState, TaskSpec, SceneDraft, StyleSpec


class TestStateStoreBasics:
    """Test basic StateStore operations"""

    @pytest.fixture
    def store(self):
        """Create a temporary state store"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield StateStore(Path(tmpdir) / "test.db")

    def test_create_session(self, store):
        """Can create a new session"""
        state = store.create_session()
        assert state.session_id is not None
        assert state.current_state == ExecutionState.INIT

    def test_create_session_with_id(self, store):
        """Can create session with specific ID"""
        state = store.create_session("test-123")
        assert state.session_id == "test-123"

    def test_commit_and_recover(self, store):
        """Can commit and recover session state"""
        state = store.create_session("test-456")
        state.current_state = ExecutionState.DRAFT_SCENE
        state.narrator_voice = "Test voice sample"

        store.commit(state)

        recovered = store.recover("test-456")
        assert recovered.session_id == "test-456"
        assert recovered.current_state == ExecutionState.DRAFT_SCENE
        assert recovered.narrator_voice == "Test voice sample"

    def test_recover_nonexistent(self, store):
        """Recovering nonexistent session raises error"""
        with pytest.raises(SessionNotFoundError):
            store.recover("nonexistent")

    def test_session_exists(self, store):
        """Can check if session exists"""
        assert not store.session_exists("test-789")
        store.create_session("test-789")
        assert store.session_exists("test-789")


class TestSnapshots:
    """Test snapshot operations"""

    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield StateStore(Path(tmpdir) / "test.db")

    def test_create_snapshot(self, store):
        """Can create a named snapshot"""
        state = store.create_session("test-snap")
        state.current_state = ExecutionState.DRAFT_SCENE
        state.current_scene_index = 3

        snapshot_id = store.snapshot(state, "scene_3_complete")
        assert snapshot_id is not None

    def test_recover_snapshot(self, store):
        """Can recover from named snapshot"""
        state = store.create_session("test-snap-recover")
        state.current_state = ExecutionState.DRAFT_SCENE
        state.current_scene_index = 3

        store.snapshot(state, "checkpoint_1")

        state.current_state = ExecutionState.CONSISTENCY_CHECK
        state.current_scene_index = 5
        store.commit(state)

        recovered = store.recover_snapshot("test-snap-recover", "checkpoint_1")
        assert recovered.current_state == ExecutionState.DRAFT_SCENE
        assert recovered.current_scene_index == 3

    def test_list_snapshots(self, store):
        """Can list all snapshots for a session"""
        state = store.create_session("test-list")

        store.snapshot(state, "snap1")
        store.snapshot(state, "snap2")
        store.snapshot(state, "snap3")

        snapshots = store.list_snapshots("test-list")
        assert len(snapshots) == 3
        names = [s["name"] for s in snapshots]
        assert "snap1" in names
        assert "snap2" in names
        assert "snap3" in names

    def test_recover_latest_snapshot(self, store):
        """Can recover the most recent snapshot"""
        state = store.create_session("test-latest")

        state.current_scene_index = 1
        store.snapshot(state, "first")

        state.current_scene_index = 2
        store.snapshot(state, "second")

        state.current_scene_index = 3
        store.snapshot(state, "third")

        recovered = store.recover_latest_snapshot("test-latest")
        assert recovered.current_scene_index == 3


class TestCrashRecovery:
    """Test crash recovery scenarios"""

    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield StateStore(Path(tmpdir) / "test.db")

    def test_recover_after_scene_4_crash(self, store):
        """Simulate crash at scene 4 and verify recovery"""
        state = store.create_session("crash-test")
        state.task_spec = TaskSpec(
            genre="psychological thriller",
            core_tension="murder confession",
            obsession_object="the old man's eye",
            style=StyleSpec()
        )
        state.narrator_voice = "TRUE!—nervous—very, very dreadfully nervous..."

        for i in range(4):
            state.current_scene_index = i
            state.scene_drafts.append(SceneDraft(
                scene_id=i,
                content=f"Scene {i} content",
                word_count=200
            ))
            store.snapshot(state, f"scene_{i}_complete", {"scene_id": i})

        state.current_state = ExecutionState.DRAFT_SCENE
        state.current_scene_index = 4
        store.commit(state)

        recovered = store.recover_latest_snapshot("crash-test")
        assert recovered.current_scene_index == 3
        assert len(recovered.scene_drafts) == 4
        assert recovered.narrator_voice == "TRUE!—nervous—very, very dreadfully nervous..."

    def test_recover_preserves_imagery_table(self, store):
        """Recovery preserves established imagery"""
        from harness.schemas import ImageryEntry

        state = store.create_session("imagery-test")
        state.imagery_table = [
            ImageryEntry(
                image_id="img_0",
                name="vulture_eye",
                description="pale blue eye with a film over it",
                category="obsession_object",
                first_scene=0,
                references=[0, 1, 2]
            ),
            ImageryEntry(
                image_id="img_1",
                name="heartbeat",
                description="sound like a watch wrapped in cotton",
                category="sensory_signal",
                first_scene=3,
                references=[3, 4]
            )
        ]

        store.snapshot(state, "with_imagery")

        recovered = store.recover_snapshot("imagery-test", "with_imagery")
        assert len(recovered.imagery_table) == 2
        assert recovered.imagery_table[0].name == "vulture_eye"
        assert recovered.imagery_table[1].name == "heartbeat"
        assert recovered.imagery_table[0].references == [0, 1, 2]

    def test_multiple_sessions_isolated(self, store):
        """Different sessions don't interfere with each other"""
        state1 = store.create_session("session-1")
        state1.narrator_voice = "Voice 1"
        store.commit(state1)

        state2 = store.create_session("session-2")
        state2.narrator_voice = "Voice 2"
        store.commit(state2)

        recovered1 = store.recover("session-1")
        recovered2 = store.recover("session-2")

        assert recovered1.narrator_voice == "Voice 1"
        assert recovered2.narrator_voice == "Voice 2"

    def test_delete_session(self, store):
        """Can delete a session and its snapshots"""
        state = store.create_session("delete-me")
        store.snapshot(state, "snap1")
        store.snapshot(state, "snap2")

        store.delete_session("delete-me")

        assert not store.session_exists("delete-me")
        assert len(store.list_snapshots("delete-me")) == 0
