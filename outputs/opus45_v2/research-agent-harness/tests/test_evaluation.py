"""Tests for the Evaluation module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.evaluation import TrajectoryRecorder, StepType


class TestStepType:
    def test_step_type_values(self):
        assert StepType.SEARCH.value == "search"
        assert StepType.FACT_EXTRACTION.value == "fact_extraction"
        assert StepType.CROSS_VALIDATION.value == "cross_validation"


class TestTrajectoryRecorder:
    def test_recorder_initialization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)
            assert recorder.step_count == 0

    def test_record_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_step(
                StepType.SEARCH,
                {"query": "test query", "results": 10},
            )

            assert entry["step_number"] == 1
            assert entry["step_type"] == "search"
            assert entry["data"]["query"] == "test query"
            assert recorder.step_count == 1

    def test_record_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_search(
                query="machine learning",
                sources_returned=15,
                source_types={"web": 10, "academic": 5},
                new_sources=12,
                deduplicated=3,
            )

            assert entry["data"]["query"] == "machine learning"
            assert entry["data"]["sources_returned"] == 15
            assert entry["data"]["new_sources"] == 12
            assert entry["data"]["deduplicated"] == 3

    def test_record_evaluation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_evaluation(
                url="https://arxiv.org/paper",
                credibility="high",
                source_type="academic_paper",
                relevance_score=0.9,
                timeliness_score=0.85,
            )

            assert entry["data"]["credibility"] == "high"
            assert entry["data"]["relevance_score"] == 0.9

    def test_record_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_extraction(
                url="https://example.com",
                facts_extracted=5,
                content_length=1000,
            )

            assert entry["data"]["facts_extracted"] == 5
            assert entry["data"]["content_length"] == 1000

    def test_record_cross_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_cross_validation(
                fact_id=1,
                fact_content="Test fact content",
                verified_by=[2, 3],
                contradicted_by=[],
            )

            assert entry["data"]["fact_id"] == 1
            assert entry["data"]["verification_count"] == 2
            assert entry["data"]["contradiction_count"] == 0

    def test_record_hop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_hop(
                hop_number=2,
                reason="Insufficient coverage",
                new_queries=["follow-up query 1", "follow-up query 2"],
                sources_before=10,
                facts_before=25,
            )

            assert entry["data"]["hop_number"] == 2
            assert len(entry["data"]["new_queries"]) == 2

    def test_record_convergence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_convergence(
                converged=True,
                reason="Sufficient sources and facts",
                total_sources=15,
                total_facts=40,
                gaps_remaining=[],
            )

            assert entry["data"]["converged"] is True
            assert entry["data"]["total_sources"] == 15

    def test_record_section_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_section_draft(
                section_name="Introduction",
                citations_used=[1, 2, 3],
                word_count=500,
            )

            assert entry["data"]["section_name"] == "Introduction"
            assert entry["data"]["citation_count"] == 3
            assert entry["data"]["word_count"] == 500

    def test_record_citation_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_citation_check(
                total_citations=10,
                orphaned=0,
                unused=2,
                valid=True,
            )

            assert entry["data"]["total_citations"] == 10
            assert entry["data"]["orphaned"] == 0
            assert entry["data"]["valid"] is True

    def test_record_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_error(
                error_type="extraction_error",
                error_message="Failed to fetch URL",
                context={"url": "https://example.com"},
            )

            assert entry["step_type"] == "error"
            assert entry["data"]["error_type"] == "extraction_error"

    def test_record_report_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            entry = recorder.record_report_generation(
                sections=["Introduction", "Findings", "Conclusion"],
                total_citations=15,
                word_count=3000,
                sources_used=12,
            )

            assert entry["data"]["sections"] == ["Introduction", "Findings", "Conclusion"]
            assert entry["data"]["total_citations"] == 15

    def test_load_trajectory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            recorder.record_search("query1", 10, {"web": 10}, 10, 0)
            recorder.record_search("query2", 8, {"web": 8}, 5, 3)

            entries = recorder.load_trajectory()
            assert len(entries) == 2
            assert entries[0]["data"]["query"] == "query1"
            assert entries[1]["data"]["query"] == "query2"

    def test_get_trajectory_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            recorder.record_search("query1", 10, {"web": 10}, 10, 0)
            recorder.record_extraction("url1", 5, 1000)
            recorder.record_extraction("url2", 3, 800)

            summary = recorder.get_trajectory_summary()
            assert summary["total_steps"] == 3
            assert summary["step_types"]["search"] == 1
            assert summary["step_types"]["fact_extraction"] == 2
            assert summary["total_searches"] == 1
            assert summary["total_sources_found"] == 10
            assert summary["total_facts_extracted"] == 8

    def test_step_counter_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trajectory.jsonl"
            recorder = TrajectoryRecorder(path)

            recorder.record_step(StepType.SEARCH, {})
            recorder.record_step(StepType.SEARCH, {})
            recorder.record_step(StepType.FACT_EXTRACTION, {})

            assert recorder.step_count == 3

    def test_empty_trajectory_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.jsonl"
            recorder = TrajectoryRecorder(path)

            summary = recorder.get_trajectory_summary()
            assert summary["total_steps"] == 0
            assert summary["step_types"] == {}
