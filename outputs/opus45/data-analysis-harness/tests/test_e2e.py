"""End-to-end tests for the complete harness."""

import pytest
import tempfile
from pathlib import Path

import pandas as pd

from harness.core import AnalysisConfig, DataAnalysisHarness
from harness.schemas import AnalysisState


@pytest.fixture
def sample_csv_file():
    """Create a temporary CSV file with test data."""
    data = """date,region,product,category,quantity,unit_price,discount,customer_id,channel
2024-01-01,华东,ProductA,电子产品,10,100.0,0.1,C001,线上
2024-01-01,华北,ProductB,服饰,5,200.0,0.2,C002,线下
2024-01-02,华南,ProductA,电子产品,8,100.0,0.0,C003,线上
2024-01-02,华东,ProductB,服饰,12,200.0,0.15,C001,线下
2024-01-03,华北,ProductC,家居,6,150.0,0.05,C004,线上
2024-01-03,华南,ProductD,食品,15,50.0,0.1,C002,线下
2024-01-04,华东,ProductA,电子产品,20,100.0,0.0,C005,线上
2024-01-04,华北,ProductB,服饰,7,200.0,0.1,C006,线下"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(data)
        return f.name


@pytest.fixture
def harness(sample_csv_file):
    """Create a harness instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = AnalysisConfig(
            data_file=sample_csv_file,
            output_dir=tmpdir,
            analysis_goal="Test analysis",
        )
        yield DataAnalysisHarness(config)


class TestHarnessInitialization:
    """Tests for harness initialization."""

    def test_harness_creates_output_dir(self, sample_csv_file):
        """Test that harness creates output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            config = AnalysisConfig(
                data_file=sample_csv_file,
                output_dir=str(output_dir),
            )
            harness = DataAnalysisHarness(config)

            assert output_dir.exists()

    def test_harness_initial_state(self, harness):
        """Test harness starts in INIT state."""
        assert harness.state.current_state == AnalysisState.INIT


class TestStepExecution:
    """Tests for individual step execution."""

    def test_execute_init_step(self, harness):
        """Test executing INIT step."""
        result = harness.execute_step(AnalysisState.INIT)

        assert result.success
        assert harness.state.has_variable("config")

    def test_execute_load_step(self, harness):
        """Test executing LOAD step."""
        harness.execute_step(AnalysisState.INIT)
        result = harness.execute_step(AnalysisState.LOAD)

        assert result.success
        df = harness.get_dataframe("df_raw")
        assert df is not None
        assert len(df) == 8

    def test_execute_quality_check_step(self, harness):
        """Test executing QUALITY_CHECK step."""
        harness.execute_step(AnalysisState.INIT)
        harness.execute_step(AnalysisState.LOAD)
        result = harness.execute_step(AnalysisState.QUALITY_CHECK)

        assert result.success
        assert harness.state.has_variable("quality_report")
        assert harness.state.has_variable("anomalies")

    def test_execute_preprocess_step(self, harness):
        """Test executing PREPROCESS step."""
        harness.execute_step(AnalysisState.INIT)
        harness.execute_step(AnalysisState.LOAD)
        harness.execute_step(AnalysisState.QUALITY_CHECK)
        result = harness.execute_step(AnalysisState.PREPROCESS)

        assert result.success
        df = harness.get_dataframe("df_clean")
        assert df is not None
        assert "sales_amount" in df.columns


class TestCompleteAnalysis:
    """Tests for complete analysis run."""

    def test_run_complete_analysis(self, harness):
        """Test running complete analysis."""
        results = harness.run()

        assert len(results) > 0
        success_count = sum(1 for r in results if r.success)
        assert success_count == len(results)

    def test_charts_generated(self, harness):
        """Test that charts are generated during analysis."""
        harness.run()

        charts = harness.get_charts()
        assert len(charts) >= 5  # At least 5 charts expected

    def test_insights_generated(self, harness):
        """Test that insights are generated during analysis."""
        harness.run()

        insights = harness.get_insights()
        assert len(insights) >= 3

    def test_report_generated(self, harness):
        """Test that report is generated."""
        harness.run()

        report = harness.get_variable("final_report")
        assert report is not None
        assert "Sales Analysis Report" in report

    def test_trajectory_recorded(self, harness):
        """Test that trajectory is recorded."""
        harness.run()

        trajectory = harness.get_trajectory()
        assert "Execution Trajectory Report" in trajectory
        assert "Step" in trajectory


class TestRollback:
    """Tests for rollback functionality."""

    def test_rollback_to_step(self, harness):
        """Test rolling back to a specific step."""
        harness.execute_step(AnalysisState.INIT)
        harness.execute_step(AnalysisState.LOAD)
        harness.execute_step(AnalysisState.QUALITY_CHECK)

        assert harness.state.has_variable("quality_report")

        success = harness.rollback_to_step(2)  # After LOAD
        assert success
        assert harness.state.current_state == AnalysisState.LOAD
        assert not harness.state.has_variable("quality_report")
        assert harness.state.has_variable("df_raw")

    def test_rollback_to_state(self, harness):
        """Test rolling back to a state."""
        harness.run_until(AnalysisState.EXPLORE)

        success = harness.rollback_to(AnalysisState.PREPROCESS)
        assert success
        assert harness.state.current_state == AnalysisState.PREPROCESS

    def test_re_execute_after_rollback(self, harness):
        """Test re-executing steps after rollback."""
        harness.run_until(AnalysisState.TREND)

        harness.rollback_to(AnalysisState.PREPROCESS)

        result = harness.execute_step(AnalysisState.EXPLORE)
        assert result.success

        result = harness.execute_step(AnalysisState.TREND)
        assert result.success


class TestProgressTracking:
    """Tests for progress tracking."""

    def test_get_progress(self, harness):
        """Test getting progress information."""
        harness.execute_step(AnalysisState.INIT)
        harness.execute_step(AnalysisState.LOAD)

        progress = harness.get_progress()

        assert progress["current_state"] == "load"
        assert progress["step_number"] == 2
        assert progress["progress_percent"] > 0

    def test_context_summary(self, harness):
        """Test getting context summary."""
        harness.execute_step(AnalysisState.INIT)
        harness.execute_step(AnalysisState.LOAD)

        summary = harness.get_context_summary()

        assert "Analysis Progress" in summary
        assert "load" in summary.lower()


class TestExport:
    """Tests for export functionality."""

    def test_export_script(self, harness):
        """Test exporting analysis as Python script."""
        harness.run()

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            filepath = f.name

        result = harness.export_script(filepath)

        assert Path(result).exists()
        with open(result) as f:
            content = f.read()

        assert "pandas" in content
        assert "sales_amount" in content


class TestValidation:
    """Tests for validation during analysis."""

    def test_validation_step_passes(self, harness):
        """Test that validation step passes with consistent data."""
        results = harness.run_until(AnalysisState.VALIDATE)

        validate_result = results[-1]
        assert validate_result.success

    def test_all_totals_consistent(self, harness):
        """Test that all analysis totals are consistent."""
        harness.run()

        df = harness.get_dataframe("df_clean")
        df_total = df["sales_amount"].sum()

        trend = harness.get_variable("trend_analysis")
        category = harness.get_variable("category_analysis")
        channel = harness.get_variable("channel_analysis")

        assert abs(trend["total_sales"] - df_total) < 0.01
        assert abs(category["total_sales"] - df_total) < 0.01
        assert abs(channel["total_sales"] - df_total) < 0.01


class TestWithRealData:
    """Tests using the actual sample data file."""

    @pytest.fixture
    def real_harness(self):
        """Create harness with real sample data."""
        sample_file = Path("./samples/sales_data.csv")
        if not sample_file.exists():
            pytest.skip("Sample data file not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = AnalysisConfig(
                data_file=str(sample_file),
                output_dir=tmpdir,
                analysis_goal="Analyze e-commerce sales data",
            )
            yield DataAnalysisHarness(config)

    def test_real_data_analysis(self, real_harness):
        """Test complete analysis with real sample data."""
        results = real_harness.run()

        assert all(r.success for r in results)

        charts = real_harness.get_charts()
        assert len(charts) >= 6

        insights = real_harness.get_insights()
        assert len(insights) >= 3

    def test_real_data_numeric_accuracy(self, real_harness):
        """Test numeric accuracy with real data."""
        real_harness.run_until(AnalysisState.PREPROCESS)

        df = real_harness.get_dataframe("df_clean")

        first_row = df.iloc[0]
        expected = first_row["quantity"] * first_row["unit_price"] * (1 - first_row["discount"])
        assert abs(first_row["sales_amount"] - expected) < 0.01
