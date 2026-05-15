"""Tests for chart generation."""

import pytest
import tempfile
from pathlib import Path

from harness.domain.tools import (
    generate_line_chart,
    generate_bar_chart,
    generate_pie_chart,
    generate_heatmap,
    generate_comparison_chart,
)
from harness.schemas import AnalysisState


@pytest.fixture
def output_dir():
    """Create a temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_time_series():
    """Sample time series data."""
    return {
        "2024-01-01": 10000.0,
        "2024-01-02": 12000.0,
        "2024-01-03": 8000.0,
        "2024-01-04": 15000.0,
        "2024-01-05": 11000.0,
    }


@pytest.fixture
def sample_category_data():
    """Sample category data."""
    return {
        "电子产品": 50000.0,
        "服饰": 35000.0,
        "家居": 28000.0,
        "食品": 22000.0,
    }


@pytest.fixture
def sample_matrix_data():
    """Sample matrix data for heatmap."""
    return {
        "华东": {"电子产品": 15000, "服饰": 12000, "家居": 8000, "食品": 6000},
        "华北": {"电子产品": 12000, "服饰": 10000, "家居": 9000, "食品": 7000},
        "华南": {"电子产品": 11000, "服饰": 8000, "家居": 7000, "食品": 5000},
    }


class TestLineChart:
    """Tests for line chart generation."""

    def test_generates_file(self, output_dir, sample_time_series):
        """Test that line chart generates a file."""
        chart = generate_line_chart(
            data=sample_time_series,
            title="Test Line Chart",
            xlabel="Date",
            ylabel="Sales",
            output_dir=output_dir,
        )

        assert Path(chart.file_path).exists()
        assert chart.chart_type == "line"
        assert chart.title == "Test Line Chart"

    def test_chart_record_metadata(self, output_dir, sample_time_series):
        """Test chart record contains correct metadata."""
        chart = generate_line_chart(
            data=sample_time_series,
            title="Trend Chart",
            xlabel="Date",
            ylabel="Amount",
            output_dir=output_dir,
        )

        assert chart.chart_id is not None
        assert chart.x_label == "Date"
        assert chart.y_label == "Amount"
        assert "5 data points" in chart.data_summary

    def test_empty_data_handling(self, output_dir):
        """Test handling of empty data."""
        chart = generate_line_chart(
            data={},
            title="Empty Chart",
            xlabel="X",
            ylabel="Y",
            output_dir=output_dir,
        )

        assert Path(chart.file_path).exists()


class TestBarChart:
    """Tests for bar chart generation."""

    def test_generates_file(self, output_dir, sample_category_data):
        """Test that bar chart generates a file."""
        chart = generate_bar_chart(
            data=sample_category_data,
            title="Test Bar Chart",
            xlabel="Category",
            ylabel="Sales",
            output_dir=output_dir,
        )

        assert Path(chart.file_path).exists()
        assert chart.chart_type == "bar"

    def test_horizontal_bar(self, output_dir, sample_category_data):
        """Test horizontal bar chart."""
        chart = generate_bar_chart(
            data=sample_category_data,
            title="Horizontal Bar",
            xlabel="Category",
            ylabel="Sales",
            output_dir=output_dir,
            horizontal=True,
        )

        assert Path(chart.file_path).exists()


class TestPieChart:
    """Tests for pie chart generation."""

    def test_generates_file(self, output_dir, sample_category_data):
        """Test that pie chart generates a file."""
        chart = generate_pie_chart(
            data=sample_category_data,
            title="Test Pie Chart",
            output_dir=output_dir,
        )

        assert Path(chart.file_path).exists()
        assert chart.chart_type == "pie"

    def test_chart_slices_match_data(self, output_dir, sample_category_data):
        """Test chart metadata matches data."""
        chart = generate_pie_chart(
            data=sample_category_data,
            title="Category Distribution",
            output_dir=output_dir,
        )

        assert "4 slices" in chart.data_summary


class TestHeatmap:
    """Tests for heatmap generation."""

    def test_generates_file(self, output_dir, sample_matrix_data):
        """Test that heatmap generates a file."""
        chart = generate_heatmap(
            data=sample_matrix_data,
            title="Test Heatmap",
            xlabel="Category",
            ylabel="Region",
            output_dir=output_dir,
        )

        assert Path(chart.file_path).exists()
        assert chart.chart_type == "heatmap"

    def test_matrix_dimensions(self, output_dir, sample_matrix_data):
        """Test heatmap matrix dimensions in metadata."""
        chart = generate_heatmap(
            data=sample_matrix_data,
            title="Category-Region Matrix",
            output_dir=output_dir,
        )

        assert "matrix" in chart.data_summary


class TestComparisonChart:
    """Tests for comparison chart generation."""

    def test_generates_file(self, output_dir):
        """Test that comparison chart generates a file."""
        data = {
            "线上": {"电子产品": 30000, "服饰": 20000},
            "线下": {"电子产品": 25000, "服饰": 18000},
        }

        chart = generate_comparison_chart(
            data=data,
            title="Channel Comparison",
            xlabel="Channel",
            ylabel="Sales",
            output_dir=output_dir,
        )

        assert Path(chart.file_path).exists()
        assert chart.chart_type == "comparison"


class TestChartFilePaths:
    """Tests for chart file path handling."""

    def test_unique_filenames(self, output_dir, sample_category_data):
        """Test that multiple charts get unique filenames."""
        chart1 = generate_bar_chart(
            data=sample_category_data,
            title="Chart 1",
            xlabel="X",
            ylabel="Y",
            output_dir=output_dir,
        )
        chart2 = generate_bar_chart(
            data=sample_category_data,
            title="Chart 2",
            xlabel="X",
            ylabel="Y",
            output_dir=output_dir,
        )

        assert chart1.file_path != chart2.file_path
        assert Path(chart1.file_path).exists()
        assert Path(chart2.file_path).exists()

    def test_creates_output_directory(self):
        """Test that output directory is created if not exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "charts" / "nested"

            chart = generate_bar_chart(
                data={"A": 100, "B": 200},
                title="Test",
                xlabel="X",
                ylabel="Y",
                output_dir=new_dir,
            )

            assert new_dir.exists()
            assert Path(chart.file_path).exists()


class TestChartStateAssignment:
    """Tests for chart state assignment."""

    def test_chart_state_updated(self, output_dir, sample_time_series):
        """Test that chart state can be updated after generation."""
        chart = generate_line_chart(
            data=sample_time_series,
            title="Trend",
            xlabel="Date",
            ylabel="Sales",
            output_dir=output_dir,
        )

        chart.step_number = 5
        chart.state = AnalysisState.TREND

        assert chart.step_number == 5
        assert chart.state == AnalysisState.TREND
