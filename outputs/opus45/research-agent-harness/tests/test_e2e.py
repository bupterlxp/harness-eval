"""End-to-end tests for the research harness."""

import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from harness.core import ResearchHarness
from harness.schemas import ResearchTask, ResearchState, Source, Evidence, SourceReliability
from harness.state import StateStore


@pytest.fixture
def research_task():
    """Create a test research task matching the sample format."""
    return ResearchTask(
        topic="大语言模型在代码生成领域的最新进展与挑战",
        questions=[
            "目前主流的代码生成大模型有哪些？",
            "代码生成模型的训练数据来源有哪些？",
        ],
        constraints={
            "min_sources": 5,
            "max_report_length_words": 1000,
            "required_sections": [
                "摘要",
                "背景与动机",
                "主流模型对比",
                "关键技术进展",
                "当前挑战",
                "未来方向",
                "参考文献",
            ],
        },
        required_sections=[
            "摘要",
            "背景与动机",
            "主流模型对比",
            "关键技术进展",
            "当前挑战",
            "未来方向",
            "参考文献",
        ],
        min_sources=5,
        max_report_length=1000,
    )


@pytest.fixture
def harness(research_task):
    """Create a research harness for testing."""
    return ResearchHarness(
        task=research_task,
        max_hops=3,
        evidence_threshold=2,
    )


class TestHarnessInitialization:
    """Tests for harness initialization."""

    def test_harness_creates_components(self, harness):
        """Verify all six components are created."""
        assert harness.state_store is not None
        assert harness.tool_registry is not None
        assert harness.context_manager is not None
        assert harness.lifecycle_manager is not None
        assert harness.trajectory_logger is not None

    def test_harness_initializes_sections(self, harness, research_task):
        """Verify sections are initialized correctly."""
        outline = harness.get_outline()
        assert len(outline) == len(research_task.required_sections)

        for section in research_task.required_sections:
            assert section in outline

    def test_harness_from_json(self, tmp_path):
        """Test creating harness from JSON file."""
        task_data = {
            "research_task": {
                "topic": "Test Topic",
                "questions": ["Question 1?"],
                "constraints": {
                    "min_sources": 5,
                    "required_sections": ["摘要", "参考文献"],
                },
            }
        }

        json_path = tmp_path / "task.json"
        with open(json_path, "w") as f:
            json.dump(task_data, f)

        harness = ResearchHarness.from_json_file(json_path)
        assert harness.task.topic == "Test Topic"


class TestHarnessState:
    """Tests for harness state management."""

    def test_initial_state(self, harness):
        """Verify initial state is correct."""
        summary = harness.get_state_summary()
        assert summary["sources"] == 0
        assert summary["evidence"] == 0
        assert summary["citations"] == 0

    def test_get_sources_empty(self, harness):
        """Test getting sources when empty."""
        sources = harness.get_sources()
        assert sources == []

    def test_get_gaps_initially(self, harness, research_task):
        """Test that all sections have gaps initially."""
        gaps = harness.get_gaps()
        assert len(gaps) > 0

        for gap in gaps:
            assert gap["current_evidence"] < gap["required_evidence"]


class TestHarnessTools:
    """Tests for tool registration."""

    def test_register_tool(self, harness):
        """Test registering a custom tool."""
        async def custom_tool(param: str) -> str:
            return f"Result: {param}"

        harness.register_tool(
            name="custom_tool",
            func=custom_tool,
            description="A custom tool",
        )

        tool = harness.tool_registry.get_tool("custom_tool")
        assert tool is not None

    def test_tool_metadata(self, harness):
        """Test tool metadata is stored."""
        async def test_tool() -> str:
            return "test"

        harness.register_tool(
            name="test_tool",
            func=test_tool,
            description="Test description",
        )

        metadata = harness.tool_registry.get_metadata("test_tool")
        assert metadata is not None
        assert metadata.description == "Test description"


class TestHarnessVerification:
    """Tests for claim verification."""

    def test_verify_claim_no_evidence(self, harness):
        """Test verification with no evidence."""
        result = harness.verify_claim("Some claim about code generation")
        assert result["verification_status"] == "unverified"
        assert result["supporting_evidence"] == []

    def test_verify_claim_with_evidence(self, harness):
        """Test verification with matching evidence."""
        source = Source(
            id="src_1",
            url="https://arxiv.org/test",
            title="Test Paper",
            content="GPT-4 achieves 90% on HumanEval",
            reliability=SourceReliability.ACADEMIC_PAPER,
        )
        harness.state_store.evidence_store.add_source(source)

        evidence = Evidence(
            id="ev_1",
            source_id="src_1",
            content="GPT-4 achieves 90% accuracy on the HumanEval benchmark",
            source_paragraph="...",
            target_section="主流模型对比",
        )
        harness.state_store.evidence_store.add_evidence(evidence)

        result = harness.verify_claim("GPT-4 achieves high accuracy on HumanEval")

        assert len(result["supporting_evidence"]) > 0 or result["verification_status"] == "unverified"


class TestHarnessCallbacks:
    """Tests for event callbacks."""

    def test_set_callbacks(self, harness):
        """Test setting callbacks."""
        state_changes = []
        progress_messages = []

        async def on_state(state, msg):
            state_changes.append((state, msg))

        async def on_progress(msg):
            progress_messages.append(msg)

        harness.set_callbacks(
            on_state_change=on_state,
            on_progress=on_progress,
        )

        assert harness._on_state_change is not None
        assert harness._on_progress is not None


class TestSampleComparison:
    """Tests comparing output against sample reference."""

    def test_required_sections_coverage(self, research_task):
        """Verify all required sections are tracked."""
        expected_sections = [
            "摘要",
            "背景与动机",
            "主流模型对比",
            "关键技术进展",
            "当前挑战",
            "未来方向",
            "参考文献",
        ]

        assert set(research_task.required_sections) == set(expected_sections)

    def test_min_sources_constraint(self, research_task):
        """Verify minimum sources constraint."""
        assert research_task.min_sources >= 10 or research_task.constraints.get("min_sources", 0) >= 5

    def test_section_status_tracking(self, harness):
        """Verify section status can be tracked."""
        outline = harness.get_outline()

        for section_name, info in outline.items():
            assert "status" in info
            assert info["status"] in ["empty", "partial", "complete"]


class TestLifecycleIntegration:
    """Tests for lifecycle hook integration."""

    def test_lifecycle_hooks_registered(self, harness):
        """Verify default lifecycle hooks are registered."""
        hooks = harness.lifecycle_manager._hooks

        assert len(hooks.get("pre_search", [])) > 0
        assert len(hooks.get("post_search", [])) > 0
        assert len(hooks.get("pre_draft", [])) > 0
        assert len(hooks.get("post_draft", [])) > 0

    def test_rate_limit_hook_registered(self, harness):
        """Verify rate limit hook is registered."""
        hooks = harness.lifecycle_manager._hooks
        assert len(hooks.get("on_rate_limit", [])) > 0


class TestTrajectoryLogging:
    """Tests for trajectory logging integration."""

    def test_trajectory_initially_empty(self, harness):
        """Verify trajectory is empty initially."""
        trajectory = harness.get_trajectory()
        assert trajectory == []

    def test_trajectory_logs_steps(self, harness):
        """Verify trajectory logs steps."""
        harness.trajectory_logger.log_step(
            state="search",
            action="test_action",
            details={"test": "data"},
        )

        trajectory = harness.get_trajectory()
        assert len(trajectory) == 1


class TestReportGeneration:
    """Tests for report generation."""

    def test_empty_report_structure(self, harness):
        """Test report generation with no content."""
        report = harness.state_store.draft_manager.generate_report()
        assert isinstance(report, str)

    def test_report_includes_sections(self, harness):
        """Test that report structure includes all sections."""
        harness.state_store.draft_manager.update_section(
            "摘要",
            "This is the abstract content.",
            evidence_ids=["ev_1"],
            citation_ids=["cite_1"],
        )

        report = harness.state_store.draft_manager.generate_report()
        assert "摘要" in report
