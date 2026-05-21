"""Tests for the lifecycle module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.lifecycle import LifecycleHooks, HookResult
from harness.context import ContextManager
from harness.evaluation import TrajectoryRecorder


@pytest.fixture
def lifecycle_setup():
    tmpdir = tempfile.mkdtemp()
    context_manager = ContextManager()
    trajectory_recorder = TrajectoryRecorder(tmpdir)
    hooks = LifecycleHooks(context_manager, trajectory_recorder)
    return hooks, context_manager, trajectory_recorder, tmpdir


class TestLifecycleHooks:
    def test_before_scene_generation(self, lifecycle_setup):
        hooks, context_manager, recorder, _ = lifecycle_setup

        context_manager.create_style_anchor("first-person", "thriller", [])
        context_manager.register_entity("Hero", "character", {"trait": "brave"}, 0)

        result = hooks.before_scene_generation(
            scene_id=1,
            scene_summary="Hero faces danger",
            prior_content="Previous content",
        )

        assert result.success is True
        assert "context_injection" in result.data
        assert result.data["style_anchor_injected"] is True
        assert "first-person" in result.data["context_injection"]

    def test_after_scene_generation(self, lifecycle_setup):
        hooks, _, _, _ = lifecycle_setup

        result = hooks.after_scene_generation(
            scene_id=0,
            scene_content="The story begins with action.",
        )

        assert result.success is True
        assert result.data["word_count"] == 5
        assert result.data["needs_consistency_check"] is True

    def test_on_consistency_check_complete_updates_entities(self, lifecycle_setup):
        hooks, context_manager, recorder, _ = lifecycle_setup

        result = hooks.on_consistency_check_complete(
            scene_id=0,
            is_consistent=True,
            issues=[],
            severity="none",
            entity_updates=[
                {"entity": "Alice", "attribute": "hair_color", "value": "blonde"},
            ],
        )

        assert result.success is True
        entity = context_manager.get_entity("alice")
        assert entity is not None
        assert entity.attributes["hair_color"] == "blonde"

    def test_on_consistency_check_complete_requires_revision(self, lifecycle_setup):
        hooks, _, recorder, _ = lifecycle_setup

        result = hooks.on_consistency_check_complete(
            scene_id=0,
            is_consistent=False,
            issues=["Eye color changed"],
            severity="major",
            entity_updates=[],
        )

        assert result.data["requires_revision"] is True

    def test_on_revision_start(self, lifecycle_setup):
        hooks, context_manager, _, _ = lifecycle_setup

        context_manager.create_style_anchor("third-person-limited", "mystery", [])

        result = hooks.on_revision_start(
            scene_id=1,
            revision_type="fix_issues",
            revision_number=1,
            issues=["Timeline inconsistency"],
        )

        assert result.success is True
        assert result.data["style_anchor_injected"] is True

    def test_on_phase_transition(self, lifecycle_setup):
        hooks, _, recorder, _ = lifecycle_setup

        result = hooks.on_phase_transition("init", "planning", 0)

        assert result.success is True
        entries = recorder.get_entries()
        assert len(entries) == 1
        assert "phase_transition" in entries[0].action

    def test_on_error(self, lifecycle_setup):
        hooks, _, recorder, _ = lifecycle_setup

        save_called = False
        def mock_save():
            nonlocal save_called
            save_called = True

        result = hooks.on_error(
            phase="generating",
            error="Test error",
            scene_id=1,
            save_callback=mock_save,
        )

        assert result.success is True
        assert result.data["error_logged"] is True
        assert save_called is True

    def test_on_completion(self, lifecycle_setup):
        hooks, _, recorder, _ = lifecycle_setup

        result = hooks.on_completion(
            status="success",
            total_word_count=5000,
            num_scenes=5,
            consistency_issues=[],
        )

        assert result.success is True
        entries = recorder.get_entries()
        assert entries[-1].action == "completion"

    def test_inject_style_anchor(self, lifecycle_setup):
        hooks, context_manager, recorder, _ = lifecycle_setup

        anchor = hooks.inject_style_anchor(
            pov="first-person",
            genre="romance",
            style_directives=["emotional"],
        )

        assert anchor.pov == "first-person"
        assert context_manager.style_anchor is not None

        entries = recorder.get_entries()
        assert any(e.action == "style_anchor_set" for e in entries)

    def test_on_rollback(self, lifecycle_setup):
        hooks, _, recorder, _ = lifecycle_setup

        result = hooks.on_rollback(
            scene_id=2,
            reason="Too many revision attempts",
            total_word_count=1000,
        )

        assert result.success is True
        entries = recorder.get_entries()
        assert entries[-1].action == "rollback"

    def test_register_custom_pre_hook(self, lifecycle_setup):
        hooks, context_manager, _, _ = lifecycle_setup

        custom_data = {}
        def custom_hook(scene_id, summary, prior):
            custom_data["called"] = True
            custom_data["scene_id"] = scene_id
            return HookResult(success=True, data={"custom": "value"})

        hooks.register_pre_scene_hook(custom_hook)
        context_manager.create_style_anchor("first-person", "test", [])

        result = hooks.before_scene_generation(0, "Test scene", "")

        assert custom_data["called"] is True
        assert custom_data["scene_id"] == 0
        assert result.data.get("custom") == "value"

    def test_register_custom_post_hook(self, lifecycle_setup):
        hooks, _, _, _ = lifecycle_setup

        custom_data = {}
        def custom_hook(scene_id, content):
            custom_data["called"] = True
            return HookResult(success=True, data={"post_custom": True})

        hooks.register_post_scene_hook(custom_hook)

        result = hooks.after_scene_generation(0, "Test content")

        assert custom_data["called"] is True
        assert result.data.get("post_custom") is True
