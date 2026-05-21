"""Tests for the Context Manager module."""

import pytest
import pandas as pd
from pathlib import Path
import tempfile
import shutil

from harness.state import StateStore
from harness.context import ContextManager


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
        'id': range(100),
        'value': [i * 1.5 for i in range(100)],
        'category': ['A', 'B', 'C'] * 33 + ['A']
    })


@pytest.fixture
def large_df():
    """Create a large DataFrame for compression testing."""
    return pd.DataFrame({
        'id': range(10000),
        'value': [i * 1.5 for i in range(10000)],
        'name': [f'item_{i}' for i in range(10000)]
    })


class TestContextManager:
    """Tests for ContextManager class."""

    def test_initialization(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        assert ctx.analysis_goal == ""
        assert ctx.constraints == []

    def test_set_analysis_goal(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        ctx.set_analysis_goal("Analyze sales data")
        assert ctx.analysis_goal == "Analyze sales data"

    def test_set_constraints(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        ctx.set_constraints(["Revenue = Quantity * Price", "No negative values"])
        assert len(ctx.constraints) == 2

    def test_build_user_context_with_data(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("sales", sample_df)

        ctx = ContextManager(state)
        ctx.set_analysis_goal("Analyze sales trends")

        context = ctx.build_user_context()

        assert "ANALYSIS GOAL" in context
        assert "Analyze sales trends" in context
        assert "sales" in context
        assert "100 rows" in context
        assert str(sample_df.to_string()) not in context

    def test_no_full_dataframe_in_context(self, temp_output_dir, large_df):
        """Verify that full DataFrame content is never in context."""
        state = StateStore(temp_output_dir)
        state.set_dataframe("large", large_df)

        ctx = ContextManager(state)
        context = ctx.build_user_context()

        assert "item_5000" not in context
        assert "item_9999" not in context
        assert "10000 rows" in context or "10000" in context

    def test_format_df_summary_includes_schema(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", sample_df)

        ctx = ContextManager(state)
        summary = ctx._format_df_summary("test", sample_df)

        assert "id" in summary
        assert "value" in summary
        assert "category" in summary
        assert "100 rows" in summary

    def test_format_charts(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.add_chart("/path/chart1.png", "bar", "Sales by category")
        state.add_chart("/path/chart2.png", "line", "Revenue trend")

        ctx = ContextManager(state)
        charts_str = ctx._format_charts()

        assert "chart1.png" in charts_str
        assert "bar" in charts_str
        assert "Sales by category" in charts_str

    def test_format_insights(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.add_insight("Revenue grew 15% year-over-year")
        state.add_insight("Top category accounts for 45% of sales")

        ctx = ContextManager(state)
        insights_str = ctx._format_insights()

        assert "15%" in insights_str
        assert "45%" in insights_str

    def test_build_system_prompt(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        prompt = ctx.build_system_prompt()

        assert "data analysis" in prompt.lower()
        assert "savefig" in prompt.lower() or "plt.show()" in prompt
        assert "JSON" in prompt or "json" in prompt

    def test_get_messages(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", sample_df)

        ctx = ContextManager(state)
        ctx.set_analysis_goal("Test goal")

        messages = ctx.get_messages()

        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_add_message(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        ctx.add_message("assistant", "I will analyze the data")
        ctx.add_message("user", "Looks good")

        assert len(ctx.conversation_history) == 2

    def test_clear_history(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        ctx.add_message("assistant", "test")
        ctx.clear_history()

        assert len(ctx.conversation_history) == 0

    def test_compress_for_large_data(self, temp_output_dir, large_df):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        compressed = ctx.compress_for_large_data(large_df, max_rows=1000)

        assert len(compressed) == 1000

    def test_compress_for_small_data(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        ctx = ContextManager(state)

        result = ctx.compress_for_large_data(sample_df, max_rows=1000)

        assert len(result) == len(sample_df)

    def test_estimate_token_count(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", sample_df)

        ctx = ContextManager(state)
        ctx.set_analysis_goal("Test goal")

        tokens = ctx.estimate_token_count()

        assert tokens > 0
        assert isinstance(tokens, int)
