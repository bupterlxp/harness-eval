"""Tests for state management and rollback functionality."""

import pytest
import pandas as pd
from pathlib import Path
import tempfile

from harness.state import ExecutionState
from harness.schemas import AnalysisState


@pytest.fixture
def execution_state():
    """Create a fresh execution state for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state = ExecutionState(output_dir=tmpdir)
        yield state


@pytest.fixture
def sample_dataframe():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
        "region": ["华东", "华北", "华南"],
        "sales": [1000.0, 2000.0, 1500.0],
    })


class TestExecutionState:
    """Tests for ExecutionState class."""

    def test_initial_state(self, execution_state):
        """Test initial state is INIT."""
        assert execution_state.current_state == AnalysisState.INIT
        assert execution_state.step_number == 0
        assert len(execution_state.variables) == 0

    def test_set_and_get_variable(self, execution_state):
        """Test setting and getting variables."""
        execution_state.set_variable("test_var", 42)
        assert execution_state.get_variable("test_var") == 42
        assert execution_state.has_variable("test_var")
        assert not execution_state.has_variable("nonexistent")

    def test_get_dataframe(self, execution_state, sample_dataframe):
        """Test getting DataFrame variables."""
        execution_state.set_variable("df", sample_dataframe)
        result = execution_state.get_dataframe("df")
        assert result is not None
        assert len(result) == 3

        execution_state.set_variable("not_df", "string")
        assert execution_state.get_dataframe("not_df") is None

    def test_start_and_complete_step(self, execution_state):
        """Test starting and completing steps."""
        step = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load data",
            input_vars=["config"],
            output_vars=["df_raw"],
            validation_conditions=["df_raw is not None"],
        )

        assert execution_state.step_number == 1
        assert execution_state.current_state == AnalysisState.LOAD
        assert step.state == AnalysisState.LOAD
        assert not step.success

        execution_state.complete_step(step, success=True, findings=["Loaded 100 rows"])

        assert step.success
        assert step.completed_at is not None
        assert step.findings == ["Loaded 100 rows"]

    def test_snapshot_and_rollback(self, execution_state, sample_dataframe):
        """Test taking snapshots and rolling back."""
        step1 = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load data",
            input_vars=[],
            output_vars=["df_raw"],
            validation_conditions=[],
        )
        execution_state.set_variable("df_raw", sample_dataframe.copy())
        execution_state.complete_step(step1, success=True)

        assert execution_state.can_rollback_to(1)

        step2 = execution_state.start_step(
            state=AnalysisState.QUALITY_CHECK,
            description="Check quality",
            input_vars=["df_raw"],
            output_vars=["quality_report"],
            validation_conditions=[],
        )
        execution_state.set_variable("quality_report", {"issues": 0})
        execution_state.complete_step(step2, success=True)

        assert execution_state.step_number == 2
        assert execution_state.has_variable("quality_report")

        success = execution_state.rollback_to_step(1)

        assert success
        assert execution_state.step_number == 1
        assert execution_state.current_state == AnalysisState.LOAD
        assert not execution_state.has_variable("quality_report")
        assert execution_state.has_variable("df_raw")

    def test_rollback_preserves_dataframe(self, execution_state, sample_dataframe):
        """Test that rollback preserves DataFrame data correctly."""
        step = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load data",
            input_vars=[],
            output_vars=["df_raw"],
            validation_conditions=[],
        )
        execution_state.set_variable("df_raw", sample_dataframe.copy())
        execution_state.complete_step(step, success=True)

        df_before = execution_state.get_dataframe("df_raw")
        df_before["sales"] = df_before["sales"] * 2

        execution_state.rollback_to_step(1)
        df_after = execution_state.get_dataframe("df_raw")

        assert df_after["sales"].iloc[0] == 1000.0

    def test_rollback_to_state(self, execution_state, sample_dataframe):
        """Test rolling back to a specific state."""
        step1 = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load",
            input_vars=[],
            output_vars=["df_raw"],
            validation_conditions=[],
        )
        execution_state.set_variable("df_raw", sample_dataframe)
        execution_state.complete_step(step1, success=True)

        step2 = execution_state.start_step(
            state=AnalysisState.QUALITY_CHECK,
            description="Quality",
            input_vars=["df_raw"],
            output_vars=["report"],
            validation_conditions=[],
        )
        execution_state.set_variable("report", {})
        execution_state.complete_step(step2, success=True)

        success = execution_state.rollback_to_state(AnalysisState.LOAD)

        assert success
        assert execution_state.current_state == AnalysisState.LOAD

    def test_cannot_rollback_to_missing_snapshot(self, execution_state):
        """Test that rollback fails for missing snapshots."""
        assert not execution_state.can_rollback_to(99)
        assert not execution_state.rollback_to_step(99)

    def test_get_available_rollback_points(self, execution_state, sample_dataframe):
        """Test getting available rollback points."""
        step1 = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load data",
            input_vars=[],
            output_vars=["df"],
            validation_conditions=[],
        )
        execution_state.set_variable("df", sample_dataframe)
        execution_state.complete_step(step1, success=True)

        step2 = execution_state.start_step(
            state=AnalysisState.QUALITY_CHECK,
            description="Check quality",
            input_vars=["df"],
            output_vars=["report"],
            validation_conditions=[],
        )
        execution_state.set_variable("report", {})
        execution_state.complete_step(step2, success=True)

        points = execution_state.get_available_rollback_points()

        assert len(points) == 2
        assert points[0][0] == 1
        assert points[0][1] == AnalysisState.LOAD
        assert points[1][0] == 2
        assert points[1][1] == AnalysisState.QUALITY_CHECK

    def test_execution_summary(self, execution_state, sample_dataframe):
        """Test getting execution summary."""
        step = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load",
            input_vars=[],
            output_vars=["df"],
            validation_conditions=[],
        )
        execution_state.set_variable("df", sample_dataframe)
        execution_state.complete_step(step, success=True)

        summary = execution_state.get_execution_summary()

        assert summary["current_state"] == "load"
        assert summary["step_number"] == 1
        assert summary["successful_steps"] == 1
        assert summary["variables_count"] == 1
        assert summary["elapsed_time"] >= 0

    def test_clear_state(self, execution_state, sample_dataframe):
        """Test clearing state."""
        step = execution_state.start_step(
            state=AnalysisState.LOAD,
            description="Load",
            input_vars=[],
            output_vars=["df"],
            validation_conditions=[],
        )
        execution_state.set_variable("df", sample_dataframe)
        execution_state.complete_step(step, success=True)

        execution_state.clear()

        assert execution_state.current_state == AnalysisState.INIT
        assert execution_state.step_number == 0
        assert len(execution_state.variables) == 0
