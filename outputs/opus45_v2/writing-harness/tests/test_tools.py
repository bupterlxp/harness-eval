"""Tests for the tools module."""

import pytest
from unittest.mock import patch, MagicMock

from harness.tools import (
    ToolRegistry,
    ParseTaskTool,
    PlanPlotTool,
    DraftSceneTool,
    CheckConsistencyTool,
    ReviseSceneTool,
    ParseTaskInput,
    PlanPlotInput,
    DraftSceneInput,
    CheckConsistencyInput,
    ReviseSceneInput,
)


class TestToolRegistry:
    def test_default_tools_registered(self):
        registry = ToolRegistry()
        tools = registry.list_tools()
        assert "parse_task" in tools
        assert "plan_plot" in tools
        assert "draft_scene" in tools
        assert "check_consistency" in tools
        assert "revise_scene" in tools

    def test_get_tool(self):
        registry = ToolRegistry()
        tool = registry.get("parse_task")
        assert tool is not None
        assert tool.name == "parse_task"

    def test_get_unknown_tool(self):
        registry = ToolRegistry()
        tool = registry.get("nonexistent")
        assert tool is None

    def test_get_schemas(self):
        registry = ToolRegistry()
        schemas = registry.get_schemas()
        assert len(schemas) > 0
        assert all("name" in s for s in schemas)


class TestParseTaskTool:
    @patch("harness.tools.call_llm")
    def test_parse_task_success(self, mock_llm):
        mock_llm.return_value = '''{"genre": "mystery", "premise": "Murder at mansion", "target_words": 2000, "pov": "third-person-limited", "style_directives": ["noir"], "structural_constraints": ["twist ending"]}'''

        tool = ParseTaskTool()
        result = tool.execute(ParseTaskInput(prompt="Write a mystery story"))

        assert result.success is True
        assert result.genre == "mystery"
        assert result.target_words == 2000
        assert "noir" in result.style_directives

    @patch("harness.tools.call_llm")
    def test_parse_task_with_code_fence(self, mock_llm):
        mock_llm.return_value = '''```json
{"genre": "romance", "premise": "Love at first sight", "target_words": 1500, "pov": "first-person", "style_directives": [], "structural_constraints": []}
```'''

        tool = ParseTaskTool()
        result = tool.execute(ParseTaskInput(prompt="Romance story"))

        assert result.success is True
        assert result.genre == "romance"


class TestPlanPlotTool:
    @patch("harness.tools.call_llm")
    def test_plan_plot_success(self, mock_llm):
        mock_llm.return_value = '''{"beats": ["Setup", "Conflict", "Resolution"], "scenes": [{"id": 0, "summary": "Opening"}, {"id": 1, "summary": "Crisis"}, {"id": 2, "summary": "Ending"}], "character_arcs": {"Hero": ["Doubt", "Growth", "Victory"]}}'''

        tool = PlanPlotTool()
        result = tool.execute(PlanPlotInput(
            premise="Hero's journey",
            genre="fantasy",
            target_words=1500,
        ))

        assert result.success is True
        assert len(result.beats) == 3
        assert len(result.scenes) == 3
        assert "Hero" in result.character_arcs

    @patch("harness.tools.call_llm")
    def test_plan_plot_fallback_on_error(self, mock_llm):
        mock_llm.side_effect = Exception("API error")

        tool = PlanPlotTool()
        result = tool.execute(PlanPlotInput(
            premise="Test",
            genre="general",
            target_words=1000,
        ))

        assert result.success is False
        assert len(result.scenes) == 3


class TestDraftSceneTool:
    @patch("harness.tools.call_llm")
    def test_draft_scene_success(self, mock_llm):
        mock_llm.return_value = "The detective stepped into the dimly lit room. Something felt wrong."

        tool = DraftSceneTool()
        result = tool.execute(DraftSceneInput(
            scene_id=0,
            scene_summary="Detective arrives at crime scene",
            target_words=200,
            context_injection="Style: noir thriller",
        ))

        assert result.success is True
        assert len(result.content) > 0
        assert result.word_count > 0


class TestCheckConsistencyTool:
    @patch("harness.tools.call_llm")
    def test_check_consistency_pass(self, mock_llm):
        mock_llm.return_value = '{"is_consistent": true, "issues": [], "entity_updates": [], "severity": "none"}'

        tool = CheckConsistencyTool()
        result = tool.execute(CheckConsistencyInput(
            scene_content="Sarah walked in with her blue eyes.",
            scene_id=1,
            entity_registry={"sarah": {"name": "Sarah", "attributes": {"eye_color": "blue"}}},
            prior_content="",
        ))

        assert result.success is True
        assert result.is_consistent is True
        assert len(result.issues) == 0

    @patch("harness.tools.call_llm")
    def test_check_consistency_drift_detected(self, mock_llm):
        mock_llm.return_value = '{"is_consistent": false, "issues": ["Sarah\'s eye color changed from blue to brown"], "entity_updates": [], "severity": "major"}'

        tool = CheckConsistencyTool()
        result = tool.execute(CheckConsistencyInput(
            scene_content="Sarah walked in with her brown eyes.",
            scene_id=1,
            entity_registry={"sarah": {"name": "Sarah", "attributes": {"eye_color": "blue"}}},
            prior_content="Sarah looked up with her striking blue eyes.",
        ))

        assert result.success is True
        assert result.is_consistent is False
        assert len(result.issues) > 0
        assert result.severity == "major"


class TestReviseSceneTool:
    @patch("harness.tools.call_llm")
    def test_revise_scene_success(self, mock_llm):
        mock_llm.return_value = "Sarah walked in with her blue eyes, just as she always had."

        tool = ReviseSceneTool()
        result = tool.execute(ReviseSceneInput(
            scene_content="Sarah walked in with her brown eyes.",
            scene_id=1,
            revision_type="fix_issues",
            issues=["Eye color inconsistency - should be blue"],
        ))

        assert result.success is True
        assert "blue" in result.revised_content
        assert result.word_count > 0
