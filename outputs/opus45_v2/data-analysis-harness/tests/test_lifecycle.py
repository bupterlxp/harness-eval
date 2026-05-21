"""Tests for the Lifecycle Hooks module."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import tempfile
import shutil

from harness.state import StateStore
from harness.lifecycle import (
    LifecycleHooks, HookPhase, HookResult, HookDefinition,
    validate_dataframe_transform, validate_calculation
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
        'value': [10.5, 20.3, 15.7, 8.2, 25.1],
        'category': ['A', 'B', 'A', 'C', 'B']
    })


class TestLifecycleHooks:
    """Tests for LifecycleHooks class."""

    def test_initialization(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        assert hooks is not None

    def test_register_custom_hook(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        def custom_hook(state, **kwargs):
            return HookResult(True, "Custom hook passed", [])

        hooks.register(HookDefinition(
            name="custom",
            phase=HookPhase.PRE_STEP,
            func=custom_hook,
            description="Custom test hook"
        ))

        results = hooks.run_hooks(HookPhase.PRE_STEP, max_steps=20)
        assert any(r.message == "Custom hook passed" for r in results)

    def test_unregister_hook(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        initial_count = len(hooks._hooks[HookPhase.PRE_STEP])
        hooks.unregister("check_max_steps_not_exceeded", HookPhase.PRE_STEP)

        assert len(hooks._hooks[HookPhase.PRE_STEP]) == initial_count - 1


class TestDataNotEmptyHook:
    """Tests for data not empty validation."""

    def test_passes_with_data(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", sample_df)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_LOAD, dataframe_name="test")

        data_check = [r for r in results if "rows" in r.message.lower() or "data" in r.message.lower()]
        assert all(r.passed for r in data_check)

    def test_fails_with_empty_data(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.set_dataframe("empty", pd.DataFrame())
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_LOAD, dataframe_name="empty")

        assert any(not r.passed for r in results)

    def test_fails_with_no_data(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_LOAD)

        assert any(not r.passed for r in results)


class TestSchemaValidationHook:
    """Tests for schema validation."""

    def test_detects_all_null_columns(self, temp_output_dir):
        df = pd.DataFrame({
            'good': [1, 2, 3],
            'bad': [None, None, None]
        })
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", df)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_LOAD, dataframe_name="test")

        warnings = hooks.get_warnings(results)
        assert any("null" in w.lower() for w in warnings)


class TestDataQualityHook:
    """Tests for data quality detection."""

    def test_detects_high_null_percentage(self, temp_output_dir):
        df = pd.DataFrame({
            'id': [1, 2, 3, 4, 5],
            'sparse': [1, None, None, None, None]
        })
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", df)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_LOAD, dataframe_name="test")

        warnings = hooks.get_warnings(results)
        assert any("null" in w.lower() for w in warnings)

    def test_detects_duplicates(self, temp_output_dir):
        df = pd.DataFrame({
            'id': [1, 1, 2, 2, 3],
            'value': [10, 10, 20, 20, 30]
        })
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", df)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_LOAD, dataframe_name="test")

        warnings = hooks.get_warnings(results)
        assert any("duplicate" in w.lower() for w in warnings)


class TestOutputValidationHook:
    """Tests for output validation."""

    def test_passes_valid_output(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_ANALYSIS, result=sample_df)

        assert all(r.passed for r in results)

    def test_fails_empty_result(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_ANALYSIS, result=pd.DataFrame())

        assert any(not r.passed for r in results)


class TestNumericValidationHook:
    """Tests for numeric result validation."""

    def test_detects_nan(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_ANALYSIS, result=float('nan'))

        assert any(not r.passed for r in results)

    def test_detects_inf(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_ANALYSIS, result=float('inf'))

        assert any(not r.passed for r in results)

    def test_passes_valid_number(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.POST_ANALYSIS, result=42.5)

        assert all(r.passed for r in results)


class TestChartValidationHooks:
    """Tests for chart-related hooks."""

    def test_chart_data_sufficient(self, temp_output_dir, sample_df):
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", sample_df)
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.PRE_CHART, dataframe_name="test")

        check_results = [r for r in results if "data" in r.message.lower() or "sufficient" in r.message.lower()]
        assert all(r.passed for r in check_results)

    def test_chart_data_insufficient(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.set_dataframe("test", pd.DataFrame())
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.PRE_CHART, dataframe_name="test", min_rows=1)

        assert any(not r.passed for r in results)

    def test_chart_file_created(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        hooks = LifecycleHooks(state)

        test_file = temp_output_dir / "test_chart.png"
        test_file.write_text("fake image")

        results = hooks.run_hooks(HookPhase.POST_CHART, chart_path=str(test_file))

        chart_check = [r for r in results if "chart" in r.message.lower()]
        assert all(r.passed for r in chart_check)


class TestMaxStepsHook:
    """Tests for max steps validation."""

    def test_passes_under_limit(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.current_step = 5
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.PRE_STEP, max_steps=20)

        step_check = [r for r in results if "step" in r.message.lower()]
        assert all(r.passed for r in step_check)

    def test_fails_at_limit(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.current_step = 20
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.PRE_STEP, max_steps=20)

        assert any(not r.passed for r in results)

    def test_warns_near_limit(self, temp_output_dir):
        state = StateStore(temp_output_dir)
        state.current_step = 18
        hooks = LifecycleHooks(state)

        results = hooks.run_hooks(HookPhase.PRE_STEP, max_steps=20)

        warnings = hooks.get_warnings(results)
        assert any("approaching" in w.lower() or "limit" in w.lower() for w in warnings)


class TestHelperFunctions:
    """Tests for helper validation functions."""

    def test_validate_dataframe_transform_valid(self, sample_df):
        after = sample_df[sample_df['value'] > 10]
        result = validate_dataframe_transform(sample_df, after, "filter")

        assert result.passed

    def test_validate_dataframe_transform_empty_result(self, sample_df):
        after = pd.DataFrame()
        result = validate_dataframe_transform(sample_df, after, "filter")

        assert not result.passed

    def test_validate_calculation_valid(self):
        result = validate_calculation(42.5, name="test")
        assert result.passed

    def test_validate_calculation_nan(self):
        result = validate_calculation(float('nan'), name="test")
        assert not result.passed

    def test_validate_calculation_out_of_range(self):
        result = validate_calculation(150, expected_range=(0, 100), name="percentage")
        assert result.passed
        assert len(result.warnings) > 0
