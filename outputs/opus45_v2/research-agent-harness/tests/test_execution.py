"""Tests for the Execution module."""

import tempfile
from pathlib import Path

import pytest

from harness.execution import (
    ExecutionLoop,
    TaskSpec,
    Result,
    ResearchState,
)


class TestTaskSpec:
    def test_default_values(self):
        spec = TaskSpec(research_questions=["What is AI?"])
        assert spec.min_sources == 10
        assert spec.max_words == 3000
        assert spec.max_hops == 3
        assert "Introduction" in spec.required_sections

    def test_custom_values(self):
        spec = TaskSpec(
            research_questions=["Question 1", "Question 2"],
            min_sources=5,
            max_words=2000,
            max_hops=2,
            required_sections=["Summary", "Analysis"],
        )
        assert spec.min_sources == 5
        assert spec.max_hops == 2
        assert len(spec.required_sections) == 2

    def test_from_dict(self):
        data = {
            "research_questions": ["What is ML?"],
            "min_sources": 15,
            "max_words": 5000,
        }
        spec = TaskSpec.from_dict(data)
        assert spec.research_questions == ["What is ML?"]
        assert spec.min_sources == 15
        assert spec.max_words == 5000

    def test_to_dict(self):
        spec = TaskSpec(
            research_questions=["Test question"],
            min_sources=8,
        )
        d = spec.to_dict()
        assert d["research_questions"] == ["Test question"]
        assert d["min_sources"] == 8


class TestResult:
    def test_result_creation(self):
        result = Result(
            status="success",
            report_path="/path/to/report.md",
            sources=[{"id": 1, "url": "https://example.com", "title": "Example", "credibility": "high"}],
            citation_integrity={"total_citations": 10, "orphaned": 0, "unused": 1},
            gaps=[],
            trajectory="/path/to/trajectory.jsonl",
        )
        assert result.status == "success"
        assert len(result.sources) == 1

    def test_result_to_dict(self):
        result = Result(
            status="partial",
            report_path="/path/to/report.md",
            sources=[],
            citation_integrity={"total_citations": 5, "orphaned": 1, "unused": 0},
            gaps=["Unanswered question"],
            trajectory="/path/to/trajectory.jsonl",
        )
        d = result.to_dict()
        assert d["status"] == "partial"
        assert d["citation_integrity"]["orphaned"] == 1
        assert len(d["gaps"]) == 1


class TestResearchState:
    def test_state_values(self):
        assert ResearchState.INIT.value == "init"
        assert ResearchState.SEARCHING.value == "searching"
        assert ResearchState.COMPLETE.value == "complete"


class TestExecutionLoop:
    @pytest.fixture
    def task_spec(self, tmp_path):
        return TaskSpec(
            research_questions=["What is machine learning?"],
            min_sources=3,
            max_words=1000,
            max_hops=2,
            required_sections=["Introduction", "Conclusion"],
            output_dir=str(tmp_path / "output"),
        )

    def test_executor_initialization(self, task_spec):
        executor = ExecutionLoop(task_spec)
        assert executor.current_state == ResearchState.INIT
        assert executor.task == task_spec
        assert executor.state_store is not None
        assert executor.context is not None
        assert executor.tools is not None
        assert executor.lifecycle is not None
        assert executor.trajectory is not None

    def test_state_transition(self, task_spec):
        executor = ExecutionLoop(task_spec)
        assert executor.current_state == ResearchState.INIT

        executor._transition(ResearchState.SEARCHING)
        assert executor.current_state == ResearchState.SEARCHING

        executor._transition(ResearchState.EXTRACTING)
        assert executor.current_state == ResearchState.EXTRACTING

    def test_output_directory_created(self, task_spec):
        executor = ExecutionLoop(task_spec)
        assert Path(task_spec.output_dir).exists()

    def test_build_failed_result(self, task_spec):
        executor = ExecutionLoop(task_spec)
        result = executor._build_failed_result("Test error")

        assert result.status == "failed"
        assert result.report_path == ""
        assert "Test error" in result.gaps

    def test_verify_citations_empty(self, task_spec):
        executor = ExecutionLoop(task_spec)
        integrity = executor._verify_citations()

        assert integrity["total_citations"] == 0
        assert integrity["orphaned"] == 0

    def test_build_result_success(self, task_spec):
        executor = ExecutionLoop(task_spec)

        for i in range(5):
            source = executor.state_store.add_source(
                f"https://example{i}.com",
                f"Example {i}",
                "high",
            )
            executor.state_store.add_fact(f"Fact {i}", source.id)
            executor.state_store.add_citation_mapping(source.id, [])

        for section in task_spec.required_sections:
            executor.state_store.add_section_draft(section, "Content", [])
            executor.state_store.update_section_draft(section, "Content", [], complete=True)

        result = executor._build_result(
            str(executor.output_dir / "report.md"),
            {"total_citations": 5, "orphaned": 0, "unused": 0},
        )

        assert result.status in ("success", "partial")
        assert len(result.sources) == 5

    def test_build_result_partial(self, task_spec):
        executor = ExecutionLoop(task_spec)

        executor.state_store.add_source("https://example.com", "Example", "high")

        for section in task_spec.required_sections:
            executor.state_store.add_section_draft(section, "Content", [])
            executor.state_store.update_section_draft(section, "Content", [], complete=True)

        result = executor._build_result(
            str(executor.output_dir / "report.md"),
            {"total_citations": 1, "orphaned": 0, "unused": 0},
        )

        assert result.status == "partial"


class TestMainParseTaskDescription:
    def test_parse_simple_question(self):
        from harness.__main__ import parse_task_description

        spec = parse_task_description("What is machine learning?")
        assert "What is machine learning?" in spec.research_questions

    def test_parse_multiple_questions(self):
        from harness.__main__ import parse_task_description

        spec = parse_task_description("""
        - What is AI?
        - How does machine learning work?
        - What are neural networks?
        """)
        assert len(spec.research_questions) == 3

    def test_parse_min_sources(self):
        from harness.__main__ import parse_task_description

        spec = parse_task_description("Research AI with minimum 15 sources")
        assert spec.min_sources == 15

    def test_parse_max_words(self):
        from harness.__main__ import parse_task_description

        spec = parse_task_description("Write a 5000 max words report on AI")
        assert spec.max_words == 5000

    def test_parse_max_hops(self):
        from harness.__main__ import parse_task_description

        spec = parse_task_description("Research with 5 hops maximum")
        assert spec.max_hops == 5

    def test_parse_sections(self):
        from harness.__main__ import parse_task_description

        spec = parse_task_description("Include sections: Overview, Methods, Results")
        assert "Overview" in spec.required_sections
        assert "Methods" in spec.required_sections
        assert "Results" in spec.required_sections
