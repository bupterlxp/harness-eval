"""Tests for the evaluation module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.evaluation import Trajectory, TrajectoryAnalyzer, TrajectoryRecorder, TrajectoryStep
from harness.execution import ExecutionContext, ExecutionState


class TestTrajectoryStep:
    """Tests for TrajectoryStep class."""

    def test_step_creation(self) -> None:
        """Test creating a trajectory step."""
        step = TrajectoryStep(
            timestamp=1000.0,
            step_number=1,
            state="UNDERSTAND",
            action="analyze_task",
            result={"success": True},
            duration=0.5,
            llm_calls=1,
            iteration=0,
        )

        assert step.step_number == 1
        assert step.state == "UNDERSTAND"
        assert step.action == "analyze_task"
        assert step.duration == 0.5


class TestTrajectoryRecorder:
    """Tests for TrajectoryRecorder."""

    def create_test_context(self, tmpdir: str) -> ExecutionContext:
        """Create a test execution context."""
        return ExecutionContext(
            task_type="test",
            description="test task",
            repo_path=tmpdir,
            test_command=None,
            constraints=[],
        )

    def test_recorder_creation(self) -> None:
        """Test creating a recorder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            assert recorder.output_dir.exists()

    def test_start_recording(self) -> None:
        """Test starting a recording."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            task_id = recorder.start(ctx)

            assert task_id.startswith("task_")
            trajectory = recorder.get_trajectory()
            assert trajectory is not None
            assert trajectory.task_type == "test"

    def test_record_step(self) -> None:
        """Test recording a step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_step(ctx, "test_action", {"result": "ok"})

            trajectory = recorder.get_trajectory()
            assert len(trajectory.steps) == 1
            assert trajectory.steps[0].action == "test_action"

    def test_record_tool_call(self) -> None:
        """Test recording a tool call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_tool_call(
                tool_name="read_file",
                params={"path": "/test.txt"},
                result={"content": "test"},
                duration=0.1,
            )

    def test_record_llm_call(self) -> None:
        """Test recording an LLM call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_llm_call(
                prompt_tokens=100,
                completion_tokens=50,
                model="gpt-4",
                duration=1.5,
            )

    def test_record_error(self) -> None:
        """Test recording an error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_error("Test error", {"context": "test"})

    def test_finish_recording(self) -> None:
        """Test finishing a recording."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_step(ctx, "action1", {})
            trajectory_path = recorder.finish(ctx)

            assert trajectory_path.endswith(".jsonl")
            assert Path(trajectory_path).exists()

    def test_jsonl_output_format(self) -> None:
        """Test that output is valid JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_step(ctx, "action1", {"key": "value"})
            trajectory_path = recorder.finish(ctx)

            with open(trajectory_path) as f:
                lines = f.readlines()
                for line in lines:
                    data = json.loads(line)
                    assert "event" in data
                    assert "timestamp" in data

    def test_get_statistics(self) -> None:
        """Test getting trajectory statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            ctx.current_state = ExecutionState.UNDERSTAND
            recorder.record_step(ctx, "understand", {})
            ctx.current_state = ExecutionState.LOCATE
            recorder.record_step(ctx, "locate", {})

            stats = recorder.get_statistics()

            assert stats["total_steps"] == 2
            assert "UNDERSTAND" in stats["states_visited"]
            assert "LOCATE" in stats["states_visited"]

    def test_export_summary(self) -> None:
        """Test exporting trajectory summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            recorder.record_step(ctx, "action", {})
            recorder.finish(ctx)

            summary = recorder.export_summary()

            assert "task_id" in summary
            assert "status" in summary
            assert "duration" in summary

    def test_sanitize_large_results(self) -> None:
        """Test that large results are sanitized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = TrajectoryRecorder(tmpdir)
            ctx = self.create_test_context(tmpdir)

            recorder.start(ctx)
            large_result = {"content": "x" * 5000}
            recorder.record_step(ctx, "action", large_result)

            trajectory = recorder.get_trajectory()
            result_content = trajectory.steps[0].result.get("content", "")
            assert len(result_content) <= 1100


class TestTrajectoryAnalyzer:
    """Tests for TrajectoryAnalyzer."""

    def create_test_trajectory(self, tmpdir: str) -> str:
        """Create a test trajectory file."""
        recorder = TrajectoryRecorder(tmpdir)
        ctx = ExecutionContext(
            task_type="test",
            description="test task",
            repo_path=tmpdir,
            test_command=None,
            constraints=[],
        )

        recorder.start(ctx)
        ctx.current_state = ExecutionState.UNDERSTAND
        recorder.record_step(ctx, "understand", {})
        ctx.current_state = ExecutionState.LOCATE
        recorder.record_step(ctx, "locate", {})
        ctx.current_state = ExecutionState.SUCCESS
        return recorder.finish(ctx)

    def test_load_trajectory(self) -> None:
        """Test loading a trajectory file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = self.create_test_trajectory(tmpdir)
            analyzer = TrajectoryAnalyzer(trajectory_path)

            loaded = analyzer.load()

            assert loaded is True

    def test_get_summary(self) -> None:
        """Test getting trajectory summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = self.create_test_trajectory(tmpdir)
            analyzer = TrajectoryAnalyzer(trajectory_path)
            analyzer.load()

            summary = analyzer.get_summary()

            assert summary["task_type"] == "test"
            assert summary["total_steps"] == 2

    def test_get_state_flow(self) -> None:
        """Test getting state flow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = self.create_test_trajectory(tmpdir)
            analyzer = TrajectoryAnalyzer(trajectory_path)
            analyzer.load()

            flow = analyzer.get_state_flow()

            assert "UNDERSTAND" in flow
            assert "LOCATE" in flow

    def test_get_bottlenecks(self) -> None:
        """Test identifying bottlenecks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            trajectory_path = self.create_test_trajectory(tmpdir)
            analyzer = TrajectoryAnalyzer(trajectory_path)
            analyzer.load()

            bottlenecks = analyzer.get_bottlenecks()

            assert len(bottlenecks) <= 5
            for b in bottlenecks:
                assert "duration" in b
                assert "state" in b

    def test_load_nonexistent_file(self) -> None:
        """Test loading a nonexistent file."""
        analyzer = TrajectoryAnalyzer("/nonexistent/path.jsonl")
        loaded = analyzer.load()

        assert loaded is False
