"""Tests for the state module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.state import (
    StateStore,
    WritingState,
    WritingPhase,
    TaskSpec,
    OutlineState,
    SceneState,
)


class TestTaskSpec:
    def test_to_dict(self):
        spec = TaskSpec(
            genre="thriller",
            premise="A detective story",
            target_words=5000,
            pov="first-person",
        )
        d = spec.to_dict()
        assert d["genre"] == "thriller"
        assert d["target_words"] == 5000

    def test_from_dict(self):
        data = {
            "genre": "romance",
            "premise": "Love story",
            "target_words": 3000,
            "pov": "third-person-limited",
            "style_directives": ["emotional"],
            "structural_constraints": ["happy ending"],
            "max_revisions": 5,
            "output_dir": "./out/",
        }
        spec = TaskSpec.from_dict(data)
        assert spec.genre == "romance"
        assert spec.max_revisions == 5


class TestSceneState:
    def test_defaults(self):
        scene = SceneState(id=0, summary="Opening scene")
        assert scene.content == ""
        assert scene.word_count == 0
        assert scene.status == "pending"

    def test_to_dict(self):
        scene = SceneState(id=1, summary="Test", content="Hello", word_count=1)
        d = scene.to_dict()
        assert d["id"] == 1
        assert d["content"] == "Hello"


class TestWritingState:
    def test_to_dict_and_from_dict(self):
        state = WritingState()
        state.phase = WritingPhase.PLANNING
        state.scenes[0] = SceneState(id=0, summary="First scene")
        state.total_word_count = 100

        d = state.to_dict()
        restored = WritingState.from_dict(d)

        assert restored.phase == WritingPhase.PLANNING
        assert 0 in restored.scenes
        assert restored.total_word_count == 100


class TestStateStore:
    def test_initialize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            spec = TaskSpec(genre="sci-fi", premise="Space adventure")
            store.initialize(spec)

            assert store.state.task_spec.genre == "sci-fi"
            assert store.state.phase == WritingPhase.INIT

    def test_set_phase(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            store.set_phase(WritingPhase.GENERATING)
            assert store.state.phase == WritingPhase.GENERATING

    def test_set_outline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            outline = OutlineState(
                beats=["Setup", "Conflict", "Resolution"],
                scenes=[
                    {"id": 0, "summary": "Opening"},
                    {"id": 1, "summary": "Middle"},
                ],
            )
            store.set_outline(outline)

            assert len(store.state.outline.beats) == 3
            assert len(store.state.scenes) == 2
            assert store.state.scenes[0].summary == "Opening"

    def test_update_scene(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            store.update_scene(0, "Scene content here", 3)

            scene = store.get_scene(0)
            assert scene is not None
            assert scene.content == "Scene content here"
            assert scene.word_count == 3
            assert store.state.total_word_count == 3

    def test_snapshot_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            outline = OutlineState(
                scenes=[{"id": 0, "summary": "S0"}, {"id": 1, "summary": "S1"}]
            )
            store.set_outline(outline)

            store.update_scene(0, "Scene 0 content", 3)
            store.snapshot(0)

            store.update_scene(1, "Scene 1 content", 3)
            assert store.state.total_word_count == 6

            store.rollback(1)
            scene1 = store.get_scene(1)
            assert scene1.content == ""
            assert scene1.word_count == 0

    def test_get_prior_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            store.update_scene(0, "First scene", 2)
            store.update_scene(1, "Second scene", 2)
            store.update_scene(2, "Third scene", 2)

            prior = store.get_prior_context(2, max_scenes=2)
            assert "First scene" in prior
            assert "Second scene" in prior

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store1 = StateStore(tmpdir)
            store1.initialize(TaskSpec(genre="mystery", premise="Whodunit"))
            store1.update_scene(0, "The body was found", 4)
            store1.save()

            store2 = StateStore(tmpdir)
            assert store2.load() is True
            assert store2.state.task_spec.genre == "mystery"
            assert store2.get_scene(0).content == "The body was found"

    def test_get_manuscript_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            store.update_scene(0, "Chapter one.", 2)
            store.update_scene(1, "Chapter two.", 2)

            text = store.get_manuscript_text()
            assert "Chapter one." in text
            assert "Chapter two." in text
