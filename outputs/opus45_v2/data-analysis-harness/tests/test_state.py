"""Tests for the State Store module."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile
import shutil

from harness.state import StateStore, StepSnapshot, DataFrameStore, get_df_schema, get_df_stats


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


class TestDataFrameStore:
    """Tests for DataFrameStore class."""

    def test_set_and_get(self, sample_df):
        store = DataFrameStore()
        store.set("test", sample_df)

        retrieved = store.get("test")
        assert retrieved is not None
        pd.testing.assert_frame_equal(retrieved, sample_df)

    def test_get_nonexistent(self):
        store = DataFrameStore()
        assert store.get("nonexistent") is None

    def test_list_names(self, sample_df):
        store = DataFrameStore()
        store.set("df1", sample_df)
        store.set("df2", sample_df)

        names = store.list_names()
        assert set(names) == {"df1", "df2"}

    def test_remove(self, sample_df):
        store = DataFrameStore()
        store.set("test", sample_df)
        store.remove("test")

        assert store.get("test") is None

    def test_snapshot_and_restore(self, sample_df):
        store = DataFrameStore()
        store.set("test", sample_df)
        store.snapshot(0)

        modified = sample_df.copy()
        modified['value'] = modified['value'] * 2
        store.set("test", modified)

        assert store.restore(0)
        retrieved = store.get("test")
        pd.testing.assert_frame_equal(retrieved, sample_df)


class TestStateStore:
    """Tests for StateStore class."""

    def test_initialization(self, temp_output_dir):
        store = StateStore(temp_output_dir)
        assert store.current_step == 0
        assert store.list_dataframes() == []

    def test_set_and_get_dataframe(self, temp_output_dir, sample_df):
        store = StateStore(temp_output_dir)
        store.set_dataframe("test", sample_df)

        retrieved = store.get_dataframe("test")
        assert retrieved is not None
        pd.testing.assert_frame_equal(retrieved, sample_df)

    def test_set_and_get_variable(self, temp_output_dir):
        store = StateStore(temp_output_dir)
        store.set_variable("count", 42)
        store.set_variable("name", "test")

        assert store.get_variable("count") == 42
        assert store.get_variable("name") == "test"
        assert store.get_variable("nonexistent", "default") == "default"

    def test_add_chart(self, temp_output_dir):
        store = StateStore(temp_output_dir)
        store.add_chart("/path/to/chart.png", "bar", "Test chart")

        assert len(store.charts) == 1
        assert store.charts[0]["path"] == "/path/to/chart.png"
        assert store.charts[0]["chart_type"] == "bar"

    def test_add_insight(self, temp_output_dir):
        store = StateStore(temp_output_dir)
        store.add_insight("Revenue increased 23% to $1.5M")

        assert len(store.insights) == 1
        assert "23%" in store.insights[0]

    def test_snapshot(self, temp_output_dir, sample_df):
        store = StateStore(temp_output_dir)
        store.set_dataframe("test", sample_df)
        store.set_variable("step", 1)
        store.record_code("print('hello')")

        snap = store.snapshot()

        assert snap.step_id == 0
        assert "test" in snap.dataframes
        assert snap.variables["step"] == 1
        assert snap.code_executed == "print('hello')"

    def test_rollback(self, temp_output_dir, sample_df):
        store = StateStore(temp_output_dir)

        store.set_dataframe("test", sample_df)
        store.set_variable("value", 10)
        store.snapshot()

        modified = sample_df.copy()
        modified['value'] = modified['value'] * 2
        store.set_dataframe("test", modified)
        store.set_variable("value", 20)
        store.snapshot()

        assert store.rollback(0)

        assert store.get_variable("value") == 10
        retrieved = store.get_dataframe("test")
        pd.testing.assert_frame_equal(retrieved, sample_df)

    def test_rollback_invalid_step(self, temp_output_dir):
        store = StateStore(temp_output_dir)
        assert not store.rollback(99)

    def test_save_and_load_state(self, temp_output_dir, sample_df):
        store = StateStore(temp_output_dir)
        store.set_dataframe("test", sample_df)
        store.set_variable("value", 42)
        store.add_insight("Test insight with 100 items")
        store.snapshot()

        filepath = store.save_state()

        new_store = StateStore(temp_output_dir)
        assert new_store.load_state(filepath)
        assert new_store.get_variable("value") == 42
        assert len(new_store.insights) == 1


class TestSchemaAndStats:
    """Tests for schema and statistics functions."""

    def test_get_df_schema(self, sample_df):
        schema = get_df_schema(sample_df)

        assert "id" in schema
        assert "name" in schema
        assert "value" in schema
        assert "int" in schema["id"].lower()

    def test_get_df_stats(self, sample_df):
        stats = get_df_stats(sample_df)

        assert stats["shape"] == [5, 4]
        assert "columns" in stats
        assert "null_counts" in stats
        assert "numeric_summary" in stats
        assert "value" in stats["numeric_summary"]
