"""Tests for the Tool Registry module."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile
import shutil
import os

from harness.state import StateStore
from harness.tools import ToolRegistry, ToolDefinition


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
        'name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
        'value': [10.5, 20.3, 15.7, 8.2, 25.1],
        'category': ['A', 'B', 'A', 'C', 'B']
    })


@pytest.fixture
def sample_csv(temp_output_dir):
    """Create a sample CSV file."""
    df = pd.DataFrame({
        'id': [1, 2, 3],
        'value': [10, 20, 30]
    })
    path = temp_output_dir / "test.csv"
    df.to_csv(path, index=False)
    return path


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_initialization(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        tools = registry.list_tools()
        assert len(tools) > 0
        assert "load_data" in tools
        assert "execute_code" in tools

    def test_get_tool(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        tool = registry.get("load_data")
        assert tool is not None
        assert tool.name == "load_data"
        assert "path" in tool.input_schema

    def test_get_nonexistent_tool(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        tool = registry.get("nonexistent")
        assert tool is None

    def test_list_by_category(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        data_tools = registry.list_by_category("data")
        assert "load_data" in data_tools

        viz_tools = registry.list_by_category("visualization")
        assert len(viz_tools) > 0


class TestLoadDataTool:
    """Tests for load_data tool."""

    def test_load_csv(self, temp_output_dir, sample_csv):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("load_data", path=str(sample_csv))

        assert result["success"]
        assert result["result"]["shape"] == (3, 2)
        assert state.get_dataframe("test") is not None

    def test_load_nonexistent_file(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("load_data", path="/nonexistent/file.csv")

        assert not result["success"]
        assert "not found" in result["error"].lower()

    def test_load_with_custom_name(self, temp_output_dir, sample_csv):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("load_data", path=str(sample_csv))

        assert result["success"]
        assert state.get_dataframe("test") is not None


class TestExecuteCodeTool:
    """Tests for execute_code tool."""

    def test_simple_code(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", sample_df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("execute_code", code="result = df['value'].sum()")

        assert result["success"]
        assert float(result["result"]) == pytest.approx(79.8)

    def test_code_with_pandas(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", sample_df)
        registry = ToolRegistry(state, temp_output_dir)

        code = """
grouped = df.groupby('category')['value'].mean()
result = grouped.to_dict()
"""
        result = registry.execute("execute_code", code=code)

        assert result["success"]

    def test_code_creates_new_dataframe(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", sample_df)
        registry = ToolRegistry(state, temp_output_dir)

        code = "new_df = df[df['value'] > 15]"
        result = registry.execute("execute_code", code=code)

        assert result["success"]
        assert state.get_dataframe("new_df") is not None

    def test_code_error_handling(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("execute_code", code="1/0")

        assert not result["success"]
        assert "ZeroDivision" in result["error"]


class TestStatisticsTool:
    """Tests for compute_statistics tool."""

    def test_compute_statistics(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", sample_df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("compute_statistics", dataframe_name="df")

        assert result["success"]
        stats = result["result"]["statistics"]
        assert "value" in stats
        assert "mean" in stats["value"]

    def test_statistics_specific_columns(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", sample_df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("compute_statistics", dataframe_name="df", columns=["value"])

        assert result["success"]

    def test_statistics_nonexistent_df(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("compute_statistics", dataframe_name="nonexistent")

        assert not result["success"]


class TestOutlierDetection:
    """Tests for detect_outliers tool."""

    def test_detect_outliers_iqr(self, temp_output_dir):
        df = pd.DataFrame({'value': [1, 2, 3, 4, 5, 100]})
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("detect_outliers", dataframe_name="df",
                                   column="value", method="iqr")

        assert result["success"]
        assert result["result"]["outlier_count"] >= 1

    def test_detect_outliers_zscore(self, temp_output_dir):
        df = pd.DataFrame({'value': [1, 2, 3, 4, 5, 100]})
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("detect_outliers", dataframe_name="df",
                                   column="value", method="zscore")

        assert result["success"]


class TestCorrelationTool:
    """Tests for compute_correlation tool."""

    def test_compute_correlation(self, temp_output_dir):
        df = pd.DataFrame({
            'a': [1, 2, 3, 4, 5],
            'b': [2, 4, 6, 8, 10],
            'c': [5, 4, 3, 2, 1]
        })
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("compute_correlation", dataframe_name="df")

        assert result["success"]
        corr = result["result"]["correlation_matrix"]
        assert corr["a"]["b"] == pytest.approx(1.0)
        assert corr["a"]["c"] == pytest.approx(-1.0)


class TestGroupAggregate:
    """Tests for group_aggregate tool."""

    def test_group_aggregate(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("df", sample_df)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("group_aggregate",
                                   dataframe_name="df",
                                   group_by=["category"],
                                   aggregations={"value": "sum"})

        assert result["success"]
        assert state.get_dataframe("df_grouped") is not None


class TestRecordInsight:
    """Tests for record_insight tool."""

    def test_record_valid_insight(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("record_insight",
                                   insight="Revenue increased 25% to $1.5M")

        assert result["success"]
        assert len(state.insights) == 1

    def test_record_insight_without_numbers(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("record_insight",
                                   insight="Revenue increased significantly")

        assert not result["success"]
        assert "numbers" in result["error"].lower()


class TestFinishTool:
    """Tests for finish tool."""

    def test_finish(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        registry = ToolRegistry(state, temp_output_dir)

        result = registry.execute("finish")

        assert result["success"]
        assert result["result"]["finished"]
