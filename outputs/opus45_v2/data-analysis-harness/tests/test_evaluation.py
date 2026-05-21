"""Tests for the Evaluation module."""

import pytest
import pandas as pd
from pathlib import Path
import tempfile
import shutil
import json

from harness.evaluation import (
    TrajectoryLogger, TrajectoryStep, EvaluationMetrics, create_evaluation_report
)


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory."""
    dirpath = tempfile.mkdtemp()
    yield Path(dirpath)
    shutil.rmtree(dirpath)


@pytest.fixture
def sample_df():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'value': [10.5, 20.3, 15.7, 8.2, 25.1]
    })


class TestTrajectoryStep:
    """Tests for TrajectoryStep dataclass."""

    def test_to_dict(self):
        step = TrajectoryStep(
            step_id=0,
            timestamp="2024-01-01T00:00:00",
            action="load_data",
            action_input={"path": "test.csv"},
            input_shapes={"df": (100, 5)},
            code_executed=None,
            output_shape={"rows": 100, "cols": 5},
            charts_generated=[],
            insights_added=[],
            tool_result={"success": True},
            duration_ms=150.5,
            success=True,
            error=None
        )

        d = step.to_dict()

        assert d["step_id"] == 0
        assert d["action"] == "load_data"
        assert d["success"] is True


class TestTrajectoryLogger:
    """Tests for TrajectoryLogger class."""

    def test_initialization(self, temp_output_dir):
        logger = TrajectoryLogger(temp_output_dir)

        assert logger.trajectory_path.exists() or not logger.steps

    def test_log_step(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        step = logger.log_step(
            action="load_data",
            action_input={"path": "test.csv"},
            input_dataframes={"df": sample_df},
            code_executed=None,
            output_shape={"rows": 5, "cols": 2},
            charts_generated=[],
            insights_added=[],
            tool_result={"success": True, "result": None, "error": None},
            duration_ms=100.0,
            success=True
        )

        assert step.step_id == 0
        assert step.action == "load_data"
        assert len(logger.steps) == 1

    def test_multiple_steps(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        for i in range(5):
            logger.log_step(
                action=f"action_{i}",
                action_input={},
                input_dataframes={"df": sample_df},
                code_executed=f"code_{i}",
                output_shape=None,
                charts_generated=[],
                insights_added=[],
                tool_result={"success": True, "result": None, "error": None},
                duration_ms=50.0,
                success=True
            )

        assert len(logger.steps) == 5
        assert logger.steps[4].step_id == 4

    def test_get_step(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        logger.log_step(
            action="test",
            action_input={},
            input_dataframes={},
            code_executed=None,
            output_shape=None,
            charts_generated=[],
            insights_added=[],
            tool_result={"success": True, "result": None, "error": None},
            duration_ms=50.0,
            success=True
        )

        step = logger.get_step(0)
        assert step is not None
        assert step.action == "test"

        assert logger.get_step(99) is None

    def test_get_summary(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        logger.log_step(
            action="load",
            action_input={},
            input_dataframes={},
            code_executed=None,
            output_shape=None,
            charts_generated=["chart1.png"],
            insights_added=["Insight 1 with 42 items"],
            tool_result={"success": True, "result": None, "error": None},
            duration_ms=100.0,
            success=True
        )

        logger.log_step(
            action="analyze",
            action_input={},
            input_dataframes={},
            code_executed="x = 1",
            output_shape=None,
            charts_generated=["chart2.png"],
            insights_added=[],
            tool_result={"success": False, "result": None, "error": "test error"},
            duration_ms=50.0,
            success=False
        )

        summary = logger.get_summary()

        assert summary["total_steps"] == 2
        assert summary["successful_steps"] == 1
        assert summary["failed_steps"] == 1
        assert summary["charts_generated"] == 2
        assert summary["insights_recorded"] == 1
        assert summary["total_duration_ms"] == 150.0

    def test_empty_summary(self, temp_output_dir):
        logger = TrajectoryLogger(temp_output_dir)
        summary = logger.get_summary()

        assert summary["total_steps"] == 0

    def test_export_trajectory(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        logger.log_step(
            action="test",
            action_input={"key": "value"},
            input_dataframes={"df": sample_df},
            code_executed="print('hello')",
            output_shape={"rows": 5},
            charts_generated=[],
            insights_added=[],
            tool_result={"success": True, "result": None, "error": None},
            duration_ms=75.0,
            success=True
        )

        filepath = logger.export_trajectory()

        assert filepath.exists()

        with open(filepath) as f:
            line = f.readline()
            data = json.loads(line)

        assert data["action"] == "test"

    def test_load_trajectory(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        for i in range(3):
            logger.log_step(
                action=f"action_{i}",
                action_input={},
                input_dataframes={},
                code_executed=None,
                output_shape=None,
                charts_generated=[],
                insights_added=[],
                tool_result={"success": True, "result": None, "error": None},
                duration_ms=50.0,
                success=True
            )

        filepath = logger.export_trajectory()

        new_logger = TrajectoryLogger(temp_output_dir / "new_dir")
        steps = new_logger.load_trajectory(filepath)

        assert len(steps) == 3


class TestEvaluationMetrics:
    """Tests for EvaluationMetrics class."""

    def test_compute_metrics_success(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        for i in range(5):
            logger.log_step(
                action="analyze",
                action_input={},
                input_dataframes={},
                code_executed=None,
                output_shape=None,
                charts_generated=["chart.png"] if i == 2 else [],
                insights_added=["Insight with 100 items"] if i == 3 else [],
                tool_result={"success": True, "result": None, "error": None},
                duration_ms=50.0,
                success=True
            )

        logger.log_step(
            action="finish",
            action_input={},
            input_dataframes={},
            code_executed=None,
            output_shape=None,
            charts_generated=[],
            insights_added=[],
            tool_result={"success": True, "result": {"finished": True}, "error": None},
            duration_ms=10.0,
            success=True
        )

        metrics = EvaluationMetrics(logger)
        computed = metrics.compute_metrics()

        assert computed["completion"] is True
        assert computed["success_rate"] == 1.0
        assert computed["total_steps"] == 6

    def test_compute_metrics_failure(self, temp_output_dir):
        logger = TrajectoryLogger(temp_output_dir)

        for i in range(3):
            logger.log_step(
                action="analyze",
                action_input={},
                input_dataframes={},
                code_executed=None,
                output_shape=None,
                charts_generated=[],
                insights_added=[],
                tool_result={"success": False, "result": None, "error": "error"},
                duration_ms=50.0,
                success=False
            )

        metrics = EvaluationMetrics(logger)
        computed = metrics.compute_metrics()

        assert computed["completion"] is False
        assert computed["success_rate"] == 0.0

    def test_check_data_backed_insights(self, temp_output_dir):
        logger = TrajectoryLogger(temp_output_dir)
        metrics = EvaluationMetrics(logger)

        insights = [
            "Revenue increased 25% to $1.5M",
            "Sales improved significantly",
            "Top 3 products account for 45% of revenue"
        ]

        result = metrics.check_data_backed_insights(insights)

        assert result["total_insights"] == 3
        assert result["data_backed_insights"] == 2
        assert result["details"][0]["is_data_backed"] is True
        assert result["details"][1]["is_data_backed"] is False


class TestCreateEvaluationReport:
    """Tests for evaluation report creation."""

    def test_create_report(self, temp_output_dir, sample_df):
        logger = TrajectoryLogger(temp_output_dir)

        logger.log_step(
            action="load_data",
            action_input={"path": "test.csv"},
            input_dataframes={"df": sample_df},
            code_executed=None,
            output_shape={"rows": 5, "cols": 2},
            charts_generated=[],
            insights_added=[],
            tool_result={"success": True, "result": None, "error": None},
            duration_ms=100.0,
            success=True
        )

        report_path = temp_output_dir / "eval_report.json"
        result = create_evaluation_report(logger, report_path)

        assert result.exists()

        with open(result) as f:
            report = json.load(f)

        assert "summary" in report
        assert "metrics" in report
        assert "steps" in report
