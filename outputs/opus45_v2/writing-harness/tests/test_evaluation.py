"""Tests for the evaluation module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.evaluation import TrajectoryRecorder, TrajectoryEntry


class TestTrajectoryEntry:
    def test_to_dict(self):
        entry = TrajectoryEntry(
            timestamp="2024-01-01T12:00:00",
            phase="generating",
            scene_id=1,
            action="scene_start",
            word_count=0,
            total_word_count=500,
            consistency_check=None,
            metadata={"key": "value"},
        )
        d = entry.to_dict()
        assert d["phase"] == "generating"
        assert d["scene_id"] == 1
        assert d["metadata"]["key"] == "value"

    def test_to_json(self):
        entry = TrajectoryEntry(
            timestamp="2024-01-01T12:00:00",
            phase="checking",
            scene_id=0,
            action="consistency_check",
            word_count=100,
            total_word_count=100,
            consistency_check={"is_consistent": True},
            metadata={},
        )
        json_str = entry.to_json()
        parsed = json.loads(json_str)
        assert parsed["phase"] == "checking"


class TestTrajectoryRecorder:
    def test_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record(
                phase="planning",
                action="start",
                metadata={"test": True},
            )

            entries = recorder.get_entries()
            assert len(entries) == 1
            assert entries[0].phase == "planning"

    def test_record_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record(phase="init", action="start")

            with open(recorder.trajectory_path) as f:
                lines = f.readlines()
            assert len(lines) == 1

            data = json.loads(lines[0])
            assert data["phase"] == "init"

    def test_record_phase_transition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record_phase_transition("planning", "generating", 0)

            entries = recorder.get_entries()
            assert len(entries) == 1
            assert "phase_transition" in entries[0].action

    def test_record_scene_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record_scene_start(0, "Opening scene", 0)
            recorder.record_scene_complete(0, 200, 200, 0)

            entries = recorder.get_entries()
            assert len(entries) == 2
            assert entries[0].action == "scene_start"
            assert entries[1].action == "scene_complete"

    def test_record_consistency_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record_consistency_check(
                scene_id=1,
                is_consistent=False,
                issues=["Eye color changed"],
                severity="major",
            )

            entries = recorder.get_entries()
            assert len(entries) == 1
            assert entries[0].consistency_check is not None
            assert entries[0].consistency_check["is_consistent"] is False

    def test_record_revision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record_revision(
                scene_id=1,
                revision_type="fix_issues",
                revision_number=1,
                word_count=250,
                total_word_count=500,
                issues_fixed=["Fixed eye color"],
            )

            entries = recorder.get_entries()
            assert len(entries) == 1
            assert "revision" in entries[0].action

    def test_record_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record_rollback(1, "Too many issues", 300)

            entries = recorder.get_entries()
            assert entries[0].action == "rollback"

    def test_get_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            recorder.record_phase_transition("init", "planning")
            recorder.record_scene_start(0, "Test", 0)
            recorder.record_consistency_check(0, False, ["Issue"], "minor")
            recorder.record_revision(0, "fix", 1, 100, 100, [])

            summary = recorder.get_summary()
            assert summary["total_entries"] == 4
            assert summary["total_revisions"] == 1
            assert summary["consistency_checks"] == 1
            assert summary["issues_found"] == 1

    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder1 = TrajectoryRecorder(tmpdir)
            recorder1.record(phase="test", action="entry1")
            recorder1.record(phase="test", action="entry2")

            recorder2 = TrajectoryRecorder(tmpdir)
            loaded = recorder2.load_from_file()

            assert loaded is True
            entries = recorder2.get_entries()
            assert len(entries) == 2
