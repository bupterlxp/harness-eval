"""Tests for the execution module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness.execution import ExecutionLoop
from harness.state import StateStore, WritingPhase
from harness.context import ContextManager
from harness.tools import ToolRegistry
from harness.lifecycle import LifecycleHooks
from harness.evaluation import TrajectoryRecorder


@pytest.fixture
def execution_setup():
    tmpdir = tempfile.mkdtemp()
    output_dir = Path(tmpdir)

    state_store = StateStore(output_dir)
    context_manager = ContextManager()
    tool_registry = ToolRegistry()
    trajectory_recorder = TrajectoryRecorder(output_dir)
    lifecycle_hooks = LifecycleHooks(context_manager, trajectory_recorder)

    loop = ExecutionLoop(
        state_store=state_store,
        context_manager=context_manager,
        tool_registry=tool_registry,
        lifecycle_hooks=lifecycle_hooks,
        trajectory_recorder=trajectory_recorder,
        max_revisions=3,
        timeout=60,
    )

    return loop, output_dir


class TestExecutionLoop:
    @patch("harness.tools.call_llm")
    def test_full_pipeline(self, mock_llm, execution_setup):
        loop, output_dir = execution_setup

        parse_response = '{"genre": "thriller", "premise": "A mystery unfolds", "target_words": 500, "pov": "first-person", "style_directives": [], "structural_constraints": []}'
        plan_response = '{"beats": ["Setup", "Conflict", "Resolution"], "scenes": [{"id": 0, "summary": "Opening"}, {"id": 1, "summary": "Middle"}], "character_arcs": {}}'
        draft_response = "The night was dark. I stepped forward into the unknown. Something moved in the shadows."
        check_response = '{"is_consistent": true, "issues": [], "entity_updates": [], "severity": "none"}'

        mock_llm.side_effect = [
            parse_response,
            plan_response,
            draft_response,
            check_response,
            draft_response,
            check_response,
        ]

        result = loop.run("Write a thriller story", output_dir)

        assert result["status"] == "success"
        assert result["word_count"] > 0
        assert len(result["outline"]["scenes"]) == 2
        assert Path(result["manuscript_path"]).exists()
        assert Path(result["trajectory"]).exists()

    @patch("harness.tools.call_llm")
    def test_consistency_triggers_revision(self, mock_llm, execution_setup):
        loop, output_dir = execution_setup

        parse_response = '{"genre": "mystery", "premise": "Whodunit", "target_words": 300, "pov": "third-person-limited", "style_directives": [], "structural_constraints": []}'
        plan_response = '{"beats": ["Setup"], "scenes": [{"id": 0, "summary": "Scene one"}], "character_arcs": {}}'
        draft_response = "Sarah looked up with her brown eyes."
        check_fail = '{"is_consistent": false, "issues": ["Sarah\'s eyes were blue before"], "entity_updates": [], "severity": "major"}'
        revised = "Sarah looked up with her blue eyes."
        check_pass = '{"is_consistent": true, "issues": [], "entity_updates": [], "severity": "none"}'

        mock_llm.side_effect = [
            parse_response,
            plan_response,
            draft_response,
            check_fail,
            revised,
            check_pass,
        ]

        result = loop.run("Mystery story", output_dir)

        assert result["status"] == "success"
        with open(result["trajectory"]) as f:
            lines = f.readlines()
        actions = [json.loads(l)["action"] for l in lines]
        assert any("revision" in a for a in actions)

    @patch("harness.tools.call_llm")
    def test_max_revisions_limit(self, mock_llm, execution_setup):
        loop, output_dir = execution_setup
        loop._max_revisions = 2

        parse_response = '{"genre": "test", "premise": "Test", "target_words": 200, "pov": "first-person", "style_directives": [], "structural_constraints": []}'
        plan_response = '{"beats": ["Test"], "scenes": [{"id": 0, "summary": "Test scene"}], "character_arcs": {}}'
        draft = "Test content here."
        check_fail = '{"is_consistent": false, "issues": ["Perpetual issue"], "entity_updates": [], "severity": "major"}'

        mock_llm.side_effect = [
            parse_response,
            plan_response,
            draft,
            check_fail,
            draft,
            check_fail,
            draft,
            check_fail,
        ]

        result = loop.run("Test", output_dir)

        scene = loop._state_store.get_scene(0)
        assert scene.revision_count <= 2

    @patch("harness.tools.call_llm")
    def test_state_persistence(self, mock_llm, execution_setup):
        loop, output_dir = execution_setup

        parse_response = '{"genre": "fantasy", "premise": "Magic story", "target_words": 300, "pov": "third-person-omniscient", "style_directives": [], "structural_constraints": []}'
        plan_response = '{"beats": ["Magic"], "scenes": [{"id": 0, "summary": "Spell cast"}], "character_arcs": {}}'
        draft = "The wizard raised his staff."
        check_pass = '{"is_consistent": true, "issues": [], "entity_updates": [], "severity": "none"}'

        mock_llm.side_effect = [parse_response, plan_response, draft, check_pass]

        loop.run("Fantasy story", output_dir)

        state_file = output_dir / "writing_state.json"
        assert state_file.exists()

        with open(state_file) as f:
            saved_state = json.load(f)
        assert saved_state["task_spec"]["genre"] == "fantasy"

    @patch("harness.tools.call_llm")
    def test_phase_transitions_recorded(self, mock_llm, execution_setup):
        loop, output_dir = execution_setup

        parse_response = '{"genre": "test", "premise": "Test", "target_words": 200, "pov": "first-person", "style_directives": [], "structural_constraints": []}'
        plan_response = '{"beats": ["Test"], "scenes": [{"id": 0, "summary": "Test"}], "character_arcs": {}}'
        draft = "Test."
        check_pass = '{"is_consistent": true, "issues": [], "entity_updates": [], "severity": "none"}'

        mock_llm.side_effect = [parse_response, plan_response, draft, check_pass]

        result = loop.run("Test", output_dir)

        with open(result["trajectory"]) as f:
            entries = [json.loads(l) for l in f.readlines()]

        phases_seen = set()
        for e in entries:
            phases_seen.add(e["phase"])

        assert "planning" in phases_seen
        assert "generating" in phases_seen
        assert "completed" in phases_seen


class TestExecutionLoopRollback:
    @patch("harness.tools.call_llm")
    def test_snapshot_created_per_scene(self, mock_llm, execution_setup):
        loop, output_dir = execution_setup

        parse_response = '{"genre": "test", "premise": "Test", "target_words": 400, "pov": "first-person", "style_directives": [], "structural_constraints": []}'
        plan_response = '{"beats": ["A", "B"], "scenes": [{"id": 0, "summary": "S0"}, {"id": 1, "summary": "S1"}], "character_arcs": {}}'
        draft0 = "Scene zero content."
        draft1 = "Scene one content."
        check_pass = '{"is_consistent": true, "issues": [], "entity_updates": [], "severity": "none"}'

        mock_llm.side_effect = [
            parse_response, plan_response,
            draft0, check_pass,
            draft1, check_pass,
        ]

        loop.run("Test", output_dir)

        snapshots_dir = output_dir / ".snapshots"
        assert snapshots_dir.exists()
        snapshots = list(snapshots_dir.glob("*.json"))
        assert len(snapshots) >= 2
