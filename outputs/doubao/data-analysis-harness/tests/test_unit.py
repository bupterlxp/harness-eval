#!/usr/bin/env python3
"""Unit tests for data analysis agent harness"""

import pandas as pd
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.schemas import *
from harness.state import ExecutionStateManager
from harness.tools import ToolRegistry
from harness.context import *
from harness.lifecycle import *
from harness.evaluation import *


class TestSchemas:
    """Test individual schema components"""

    def test_data_profile(self):
        """Test DataProfile dataclass"""
        profile = DataProfile(
            shape=(100, 10),
            columns=["col1", "col2"],
            dtypes={"col1": "int64", "col2": "float64"},
            missing_values={"col1": 5, "col2": 0},
            missing_rate={"col1": 5.0, "col2": 0.0},
            summary_stats={"col1": {"mean": 50.0}}
        )
        assert profile.shape == (100, 10)
        assert profile.missing_values["col1"] == 5
        assert "col2" in profile.columns

    def test_analysis_step(self):
        """Test AnalysisStep dataclass"""
        step = AnalysisStep(
            name="test_step",
            description="Test analysis step",
            input_shape=(100, 10),
            output_shape=(50, 5)
        )
        assert step.name == "test_step"
        assert step.input_shape == (100, 10)
        assert step.output_shape == (50, 5)

    def test_insight(self):
        """Test Insight dataclass"""
        insight = Insight(
            title="Test Insight",
            description="This is a test insight",
            supporting_data=["Data point 1", "Data point 2"],
            confidence=0.9
        )
        assert insight.title == "Test Insight"
        assert len(insight.supporting_data) == 2
        assert insight.confidence == 0.9


class TestStateManager:
    """Test execution state management"""

    def test_initial_state(self):
        """Test initial state creation"""
        manager = ExecutionStateManager()
        state = manager.get_current_state()
        assert state.current_step == "LOAD"
        assert len(state.dataframes) == 0
        assert len(state.analysis_history) == 0

    def test_snapshot_and_rollback(self):
        """Test snapshot creation and rollback"""
        manager = ExecutionStateManager()
        state = manager.get_current_state()

        # Add test data
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        state.dataframes["test_df"] = df
        state.variables["test_var"] = 42
        manager.update_current_state(state)

        # Create snapshot
        snapshot_id = manager.create_snapshot("test_step_1")
        assert snapshot_id == "test_step_1"
        assert snapshot_id in manager.list_snapshots()

        # Modify current state
        state2 = manager.get_current_state()
        state2.dataframes["another_df"] = pd.DataFrame({'x': [7, 8, 9]})
        state2.variables["test_var"] = 100
        manager.update_current_state(state2)

        # Rollback
        success = manager.rollback(snapshot_id)
        assert success is True
        current_state = manager.get_current_state()
        assert "test_df" in current_state.dataframes
        assert "another_df" not in current_state.dataframes
        assert current_state.variables["test_var"] == 42


class TestToolRegistry:
    """Test tool registry functionality"""

    def test_register_and_execute_tool(self):
        """Test tool registration and execution"""
        registry = ToolRegistry()

        # Define a test tool
        def test_tool(a, b):
            return a + b

        # Register tool
        registry.register_tool(
            category="explorer",
            name="add_numbers",
            func=test_tool,
            input_schema={"required_fields": ["a", "b"]},
            output_schema={"shape": ()}
        )

        # Get and execute tool
        tool = registry.get_tool("explorer", "add_numbers")
        assert tool is not None
        assert tool["description"] == ""

        # Execute tool
        result, validation = registry.execute_tool("explorer", "add_numbers", 5, 3)
        assert result == 8
        assert validation.is_valid is True

    def test_tool_validation(self):
        """Test input validation for tools"""
        registry = ToolRegistry()

        def test_tool(df):
            return df.sum()

        registry.register_tool(
            category="explorer",
            name="sum_df",
            func=test_tool,
            input_schema={"required_columns": ["a", "b"]}
        )

        # Test with invalid dataframe
        df = pd.DataFrame({'x': [1, 2, 3]})
        result, validation = registry.execute_tool("explorer", "sum_df", df)
        assert result is None
        assert validation.is_valid is False
        assert len(validation.errors) > 0


class TestContextManagement:
    """Test context management"""

    def test_data_context(self):
        """Test data context with profile"""
        df = pd.DataFrame({
            'a': [1, 2, 3, 4, 5],
            'b': [10.5, 20.5, 30.5, 40.5, 50.5],
            'c': ['x', 'y', 'z', 'x', 'y']
        })

        context = DataContext(df)
        assert context.data_profile is not None
        assert context.data_profile.shape == (5, 3)
        assert context.data_profile.missing_values["a"] == 0
        assert len(context.data_profile.summary_stats) == 2

        summary = context.get_summary_string()
        assert "Data shape: 5 rows, 3 columns" in summary
        assert "Missing values:" in summary

    def test_analysis_history(self):
        """Test analysis history tracking"""
        history = AnalysisHistory()
        history.add_step(
            name="LOAD_DATA",
            description="Load test data",
            input_shape=(0, 0),
            output_shape=(100, 10)
        )

        assert len(history.steps) == 1
        assert history.current_step == 1

        step = history.get_step(1)
        assert step["name"] == "LOAD_DATA"
        assert step["input_shape"] == (0, 0)

    def test_intent_context(self):
        """Test intent context tracking"""
        requirements = ["Data quality", "Sales trends", "Regional analysis"]
        intent = IntentContext(
            analysis_goal="Test sales analysis",
            data_file="test_data.csv",
            requirements=requirements
        )

        assert intent.analysis_goal == "Test sales analysis"
        assert intent.data_file == "test_data.csv"
        assert len(intent.requirements) == 3

        intent.update_progress("Data quality")
        assert "Data quality" in intent.completed_modules
        assert len(intent.completed_modules) == 1


class TestLifecycleHooks:
    """Test lifecycle hooks"""

    def test_default_hooks(self):
        """Test default lifecycle hooks"""
        hooks = get_default_lifecycle_hooks()
        assert hooks is not None
        assert len(hooks.pre_execute_hooks) > 0
        assert len(hooks.pre_plot_hooks) > 0

    def test_pre_execute_validation(self):
        """Test pre-execute validation hooks"""
        hooks = LifecycleHooks()
        state = ExecutionState()

        # Add test dataframe
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        state.dataframes["main"] = df

        # Test hook
        @hooks.add_pre_execute_hook
        def test_hook(state):
            if "main" not in state.dataframes:
                return ValidationResult(is_valid=False, errors=["No main dataframe"])
            return ValidationResult(is_valid=True)

        result = hooks.run_pre_execute(state)
        assert result.is_valid is True


class TestEvaluationTracker:
    """Test trajectory tracking"""

    def test_trajectory_basic(self):
        """Test basic trajectory tracking"""
        tracker = TrajectoryTracker()

        # Add test steps
        tracker.add_step(
            step_name="LOAD_DATA",
            description="Load test data",
            input_shape=(0, 0),
            output_shape=(100, 10)
        )

        tracker.add_step(
            step_name="QUALITY_CHECK",
            description="Check data quality",
            input_shape=(100, 10),
            output_shape=(100, 10),
            validation_result=ValidationResult(is_valid=True, warnings=["Test warning"])
        )

        assert len(tracker.trajectory) == 2
        assert tracker.count_charts() == 0

    def test_save_trajectory(self):
        """Test saving trajectory to file"""
        tracker = TrajectoryTracker()
        tracker.add_step(
            step_name="TEST_STEP",
            description="Test step",
            input_shape=(10, 10),
            output_shape=(5, 5)
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            pass

        try:
            saved_path = tracker.save_trajectory(f.name)
            assert os.path.exists(saved_path)

            # Check file was created and has content
            with open(saved_path, 'r') as f:
                lines = f.readlines()
                assert len(lines) == 1

        finally:
            os.unlink(f.name)


def run_unit_tests():
    """Run all unit tests"""
    print("="*70)
    print("Running Data Analysis Agent Harness Unit Tests")
    print("="*70)

    test_classes = [
        TestSchemas,
        TestStateManager,
        TestToolRegistry,
        TestContextManagement,
        TestLifecycleHooks,
        TestEvaluationTracker
    ]

    passed = 0
    failed = 0

    for test_class in test_classes:
        class_name = test_class.__name__
        print(f"\n--- Testing {class_name} ---")

        test_instance = test_class()
        test_methods = [getattr(test_instance, attr) for attr in dir(test_instance) if attr.startswith('test_')]

        for test_method in test_methods:
            try:
                test_method()
                print(f"  ✓ {test_method.__name__}")
                passed += 1
            except Exception as e:
                print(f"  ✗ {test_method.__name__}: FAILED - {str(e)}")
                failed += 1

    print("\n" + "="*70)
    print(f"Tests completed: {passed} passed, {failed} failed")
    print("="*70)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_unit_tests()