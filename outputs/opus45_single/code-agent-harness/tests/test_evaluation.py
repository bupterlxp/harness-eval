"""Tests for harness.evaluation module."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest

from harness.evaluation import (
    TrajectoryLogger,
    TrajectoryStep,
    TrajectorySummary,
    EvaluationMetrics,
)


class TestTrajectoryStep:
    """Tests for TrajectoryStep."""

    def test_creation(self):
        """Test creating a trajectory step."""
        step = TrajectoryStep(
            step_id=1,
            timestamp=1000.0,
            phase="understand",
            action="read_file",
            action_input={"path": "test.py"},
            result="content",
            success=True,
            duration_ms=100.0
        )
        assert step.step_id == 1
        assert step.phase == "understand"
        assert step.success is True

    def test_to_dict(self):
        """Test serialization to dict."""
        step = TrajectoryStep(
            step_id=1,
            timestamp=1000.0,
            phase="edit",
            action="write_file",
            action_input={"path": "test.py"},
            result=True,
            success=True,
            duration_ms=50.0,
            metadata={"extra": "data"}
        )
        d = step.to_dict()
        assert d["step_id"] == 1
        assert d["phase"] == "edit"
        assert d["metadata"]["extra"] == "data"


class TestTrajectoryLogger:
    """Tests for TrajectoryLogger."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d)

    @pytest.fixture
    def logger(self, temp_dir):
        """Create a TrajectoryLogger instance."""
        return TrajectoryLogger(temp_dir / "trajectory.jsonl")

    def test_log_step(self, logger):
        """Test logging a single step."""
        step = logger.log_step(
            phase="understand",
            action="tool:read_file",
            action_input={"path": "test.py"},
            result="file contents",
            success=True,
            duration_ms=100.0
        )
        assert step.step_id == 1
        assert len(logger.steps) == 1

    def test_step_counter_increments(self, logger):
        """Test step counter increments correctly."""
        logger.log_step("p1", "a1", {}, None, True, 0)
        logger.log_step("p2", "a2", {}, None, True, 0)
        logger.log_step("p3", "a3", {}, None, True, 0)

        assert logger.steps[-1].step_id == 3

    def test_tracks_tools_used(self, logger):
        """Test tracking of tools used."""
        logger.log_step("edit", "tool:read_file", {}, None, True, 0)
        logger.log_step("edit", "tool:read_file", {}, None, True, 0)
        logger.log_step("edit", "tool:write_file", {}, None, True, 0)

        summary = logger.get_summary()
        assert summary.tools_used["read_file"] == 2
        assert summary.tools_used["write_file"] == 1

    def test_tracks_llm_calls(self, logger):
        """Test tracking of LLM calls."""
        logger.log_step("understand", "llm_call", {}, "response", True, 100)
        logger.log_step("plan", "llm_call", {}, "response", True, 100)

        summary = logger.get_summary()
        assert summary.llm_calls == 2

    def test_log_retry(self, logger):
        """Test logging a retry event."""
        logger.log_retry("Test failed")
        assert logger._retries == 1

        summary = logger.get_summary()
        assert summary.retries == 1

    def test_log_phase_transition(self, logger):
        """Test logging phase transitions."""
        logger.log_phase_transition("understand", "locate", "analysis complete")

        assert len(logger.steps) == 1
        assert logger.steps[0].action == "phase_transition"
        assert logger.steps[0].result == "locate"

    def test_timed_step(self, logger):
        """Test timed step context manager."""
        with logger.timed_step("edit", "test_action", {"param": 1}) as result:
            result["result"] = "done"

        assert len(logger.steps) == 1
        assert logger.steps[0].success is True
        assert logger.steps[0].duration_ms > 0

    def test_timed_step_on_error(self, logger):
        """Test timed step records errors."""
        with pytest.raises(ValueError):
            with logger.timed_step("edit", "failing_action", {}) as result:
                raise ValueError("Test error")

        assert len(logger.steps) == 1
        assert logger.steps[0].success is False

    def test_get_summary(self, logger):
        """Test getting trajectory summary."""
        logger.log_step("understand", "llm_call", {}, None, True, 100)
        logger.log_step("locate", "tool:search", {}, None, True, 50)
        logger.log_step("edit", "tool:write", {}, None, False, 30)

        summary = logger.get_summary()
        assert summary.total_steps == 3
        assert summary.successful_steps == 2
        assert summary.failed_steps == 1
        assert summary.total_duration_ms == 180
        assert "understand" in summary.phases_visited
        assert "locate" in summary.phases_visited

    def test_finalize_creates_file(self, logger, temp_dir):
        """Test finalize writes file and returns path."""
        logger.log_step("test", "action", {}, None, True, 0)

        path = logger.finalize()
        assert path.exists()
        assert path.suffix == ".jsonl"

    def test_output_is_valid_jsonl(self, logger, temp_dir):
        """Test that output is valid JSONL format."""
        logger.log_step("p1", "a1", {}, "r1", True, 10)
        logger.log_step("p2", "a2", {}, "r2", True, 20)
        path = logger.finalize()

        lines = path.read_text().strip().split("\n")
        for line in lines:
            parsed = json.loads(line)
            assert isinstance(parsed, dict)

    def test_get_recent_steps(self, logger):
        """Test getting recent steps."""
        for i in range(10):
            logger.log_step(f"phase_{i}", f"action_{i}", {}, None, True, 0)

        recent = logger.get_recent_steps(3)
        assert len(recent) == 3
        assert recent[0].step_id == 8

    def test_get_steps_by_phase(self, logger):
        """Test filtering steps by phase."""
        logger.log_step("understand", "a1", {}, None, True, 0)
        logger.log_step("edit", "a2", {}, None, True, 0)
        logger.log_step("understand", "a3", {}, None, True, 0)

        understand_steps = logger.get_steps_by_phase("understand")
        assert len(understand_steps) == 2


class TestTrajectorySummary:
    """Tests for TrajectorySummary."""

    def test_to_dict(self):
        """Test serialization to dict."""
        summary = TrajectorySummary(
            total_steps=10,
            successful_steps=8,
            failed_steps=2,
            total_duration_ms=1000.0,
            phases_visited=["understand", "edit"],
            tools_used={"read": 5, "write": 3},
            llm_calls=4,
            retries=1
        )
        d = summary.to_dict()
        assert d["total_steps"] == 10
        assert d["successful_steps"] == 8
        assert d["llm_calls"] == 4


class TestEvaluationMetrics:
    """Tests for EvaluationMetrics."""

    @pytest.fixture
    def metrics(self):
        """Create an EvaluationMetrics instance."""
        return EvaluationMetrics()

    def test_record_test_result(self, metrics):
        """Test recording test results."""
        metrics.record_test_result(passed=5, failed=2, errors=["error1"])

        assert metrics.test_results["passed"] == 5
        assert metrics.test_results["failed"] == 2
        assert "error1" in metrics.test_results["errors"]

    def test_record_edit(self, metrics):
        """Test recording file edits."""
        metrics.record_edit("file.py", "+new line\n-old line")

        assert len(metrics.edits) == 1
        assert metrics.edits[0]["file"] == "file.py"

    def test_record_token_usage(self, metrics):
        """Test recording token usage."""
        metrics.record_token_usage(prompt=100, completion=50)
        metrics.record_token_usage(prompt=80, completion=40)

        assert metrics.llm_token_usage["prompt_tokens"] == 180
        assert metrics.llm_token_usage["completion_tokens"] == 90
        assert metrics.llm_token_usage["total_tokens"] == 270

    def test_to_dict(self, metrics):
        """Test serialization to dict."""
        metrics.record_test_result(1, 0, [])
        metrics.record_edit("test.py", "diff")

        d = metrics.to_dict()
        assert "test_results" in d
        assert "edits" in d
        assert "llm_token_usage" in d
