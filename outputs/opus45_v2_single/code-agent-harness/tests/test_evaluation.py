"""Tests for the Evaluation module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.evaluation import StepType, TrajectoryLogger, TrajectoryStats, TrajectoryStep


class TestStepType:
    """Tests for StepType enum."""

    def test_step_types_are_strings(self):
        assert StepType.LLM_CALL.value == "llm_call"
        assert StepType.TOOL_CALL.value == "tool_call"
        assert StepType.PHASE_TRANSITION.value == "phase_transition"


class TestTrajectoryStep:
    """Tests for TrajectoryStep."""

    def test_to_dict(self):
        step = TrajectoryStep(
            step_id=1,
            step_type=StepType.LLM_CALL,
            timestamp=12345.0,
            phase="EDIT",
            operation="llm_completion",
            input_data={"messages": 5},
            output_data={"content": "response"},
            duration_ms=100.0,
            success=True,
        )

        d = step.to_dict()

        assert d["step_id"] == 1
        assert d["step_type"] == "llm_call"
        assert d["phase"] == "EDIT"
        assert d["success"] is True

    def test_to_jsonl(self):
        step = TrajectoryStep(
            step_id=1,
            step_type=StepType.TOOL_CALL,
            timestamp=12345.0,
            phase="LOCATE",
            operation="tool:search_code",
            input_data={"pattern": "test"},
            output_data={"results": 5},
            duration_ms=50.0,
            success=True,
        )

        jsonl = step.to_jsonl()
        parsed = json.loads(jsonl)

        assert parsed["step_id"] == 1
        assert parsed["operation"] == "tool:search_code"


class TestTrajectoryStats:
    """Tests for TrajectoryStats."""

    def test_default_values(self):
        stats = TrajectoryStats()

        assert stats.total_steps == 0
        assert stats.llm_calls == 0
        assert stats.tool_calls == 0
        assert stats.phases_visited == []


class TestTrajectoryLogger:
    """Tests for TrajectoryLogger."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def logger(self, temp_dir):
        return TrajectoryLogger(temp_dir)

    def test_initialization(self, logger, temp_dir):
        assert logger.output_dir == Path(temp_dir)
        assert logger.trajectory_path.name == "trajectory.jsonl"

    def test_start_session(self, logger):
        logger.start_session("Test task", metadata={"key": "value"})

        assert logger._start_time is not None
        assert logger.trajectory_path.exists()

        with open(logger.trajectory_path) as f:
            header = json.loads(f.readline())

        assert "session_start" in header
        assert header["task_description"] == "Test task"

    def test_end_session(self, logger):
        logger.start_session("Test task")
        path = logger.end_session("success", {"result": "done"})

        assert path == str(logger.trajectory_path)

        with open(logger.trajectory_path) as f:
            lines = f.readlines()
            footer = json.loads(lines[-1])

        assert footer["status"] == "success"
        assert "session_end" in footer

    def test_set_phase(self, logger):
        logger.start_session("Test task")
        logger.set_phase("EDIT")

        assert logger._current_phase == "EDIT"
        assert "EDIT" in logger._stats.phases_visited

    def test_log_step(self, logger):
        logger.start_session("Test task")

        step = logger.log_step(
            step_type=StepType.TOOL_CALL,
            operation="read_file",
            input_data={"path": "/test.py"},
            output_data={"content": "code"},
            success=True,
        )

        assert step.step_id == 1
        assert logger._stats.tool_calls == 1
        assert logger._stats.total_steps == 1

    def test_log_llm_call(self, logger):
        logger.start_session("Test task")

        messages = [{"role": "user", "content": "Hello"}]
        response = {"content": "Hi there"}

        step = logger.log_llm_call(messages, response, success=True, model="gpt-4")

        assert step.step_type == StepType.LLM_CALL
        assert logger._stats.llm_calls == 1

    def test_log_tool_call(self, logger):
        logger.start_session("Test task")

        step = logger.log_tool_call(
            tool_name="search_code",
            arguments={"pattern": "def"},
            result=[{"file": "a.py", "line": 1}],
            success=True,
        )

        assert step.step_type == StepType.TOOL_CALL
        assert "search_code" in step.operation

    def test_log_test_run(self, logger):
        logger.start_session("Test task")

        step = logger.log_test_run(
            command="pytest tests/",
            passed=10,
            failed=2,
            errors=["Error 1"],
        )

        assert step.step_type == StepType.TEST_RUN
        assert not step.success  # failed > 0

    def test_log_file_edit(self, logger):
        logger.start_session("Test task")

        step = logger.log_file_edit(
            file_path="/test/file.py",
            edit_type="write_file",
            diff_preview="+new line\n-old line",
            success=True,
        )

        assert step.step_type == StepType.FILE_EDIT
        assert logger._stats.file_edits == 1

    def test_log_error(self, logger):
        logger.start_session("Test task")

        step = logger.log_error(
            error=ValueError("test error"),
            context={"phase": "EDIT"},
        )

        assert step.step_type == StepType.ERROR
        assert not step.success
        assert logger._stats.errors == 1

    def test_log_decision(self, logger):
        logger.start_session("Test task")

        step = logger.log_decision(
            decision="retry",
            reasoning="Tests failed, need to modify approach",
            options_considered=["retry", "rollback", "give_up"],
        )

        assert step.step_type == StepType.DECISION
        assert step.success

    def test_get_stats(self, logger):
        logger.start_session("Test task")
        logger.log_step(StepType.LLM_CALL, "call1", {}, {}, True)
        logger.log_step(StepType.TOOL_CALL, "call2", {}, {}, True)

        stats = logger.get_stats()

        assert stats.total_steps == 2
        assert stats.llm_calls == 1
        assert stats.tool_calls == 1

    def test_read_trajectory(self, logger):
        logger.start_session("Test task")
        logger.log_step(StepType.LLM_CALL, "op1", {}, {}, True)
        logger.log_step(StepType.TOOL_CALL, "op2", {}, {}, True)
        logger.end_session("success")

        entries = logger.read_trajectory()

        assert len(entries) >= 3  # header + 2 steps + footer

    def test_sanitize_data(self, logger):
        data = {
            "string": "value",
            "number": 42,
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "custom": object(),
        }

        sanitized = logger._sanitize_data(data)

        assert sanitized["string"] == "value"
        assert sanitized["number"] == 42
        assert isinstance(sanitized["custom"], str)

    def test_truncate_value(self, logger):
        long_string = "x" * 1000
        truncated = logger._truncate_value(long_string, max_len=100)

        assert len(truncated) < len(long_string)
        assert truncated.endswith("...")

    def test_timing(self, logger):
        logger.start_session("Test task")

        logger.start_step()
        import time
        time.sleep(0.01)

        step = logger.log_step(StepType.TOOL_CALL, "timed", {}, {}, True)

        assert step.duration_ms >= 10  # at least 10ms
