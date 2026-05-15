#!/usr/bin/env python3
"""Simple verification script for the data analysis agent harness"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("="*70)
print("Data Analysis Agent Harness - Verification Test")
print("="*70)

# Test imports
try:
    from harness.schemas import DataProfile, AnalysisStep, Insight, ValidationResult
    from harness.state import ExecutionStateManager
    from harness.tools import ToolRegistry
    from harness.context import AnalysisContext, DataContext
    from harness.evaluation import TrajectoryTracker
    from harness.execution import AnalysisStateMachine
    from harness.core import DataAnalysisAgent, AgentHarness

    print("✅ All core modules imported successfully")
except ImportError as e:
    print(f"❌ Failed to import modules: {str(e)}")
    sys.exit(1)

# Test schemas
print("\n--- Testing Schemas ---")
try:
    profile = DataProfile(
        shape=(100, 10),
        columns=["col1", "col2"],
        dtypes={"col1": "int64", "col2": "float64"},
        missing_values={"col1": 5, "col2": 0},
        missing_rate={"col1": 5.0, "col2": 0.0},
        summary_stats={"col1": {"mean": 50.0}}
    )
    print("✅ DataProfile created successfully")

    step = AnalysisStep(
        name="test_step",
        description="Test step",
        input_shape=(100, 10),
        output_shape=(50, 5)
    )
    print("✅ AnalysisStep created successfully")

    insight = Insight(
        title="Test Insight",
        description="Test description",
        supporting_data=["Data1", "Data2"]
    )
    print("✅ Insight created successfully")

except Exception as e:
    print(f"❌ Schema tests failed: {str(e)}")

# Test state management
print("\n--- Testing State Management ---")
try:
    manager = ExecutionStateManager()
    state = manager.get_current_state()
    assert state.current_step == "LOAD"
    print("✅ ExecutionStateManager initialized successfully")
except Exception as e:
    print(f"❌ State management tests failed: {str(e)}")

# Test tool registry
print("\n--- Testing Tool Registry ---")
try:
    registry = ToolRegistry()

    def test_func(a, b):
        return a + b

    registry.register_tool(
        category="explorer",
        name="test_tool",
        func=test_func
    )

    tool = registry.get_tool("explorer", "test_tool")
    assert tool is not None
    print("✅ ToolRegistry registered and retrieved tool successfully")
except Exception as e:
    print(f"❌ Tool registry tests failed: {str(e)}")

# Test context
print("\n--- Testing Context Management ---")
try:
    context = AnalysisContext(
        analysis_goal="Test analysis",
        data_file="test.csv",
        requirements=["Test req1", "Test req2"]
    )
    print("✅ AnalysisContext created successfully")

    # Test data context
    try:
        import pandas as pd
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        data_context = DataContext(df)
        print("✅ DataContext created successfully with pandas")
    except ImportError:
        print("ℹ️  pandas not available, skipping data context with data")

except Exception as e:
    print(f"❌ Context management tests failed: {str(e)}")

# Test trajectory tracker
print("\n--- Testing Trajectory Tracker ---")
try:
    tracker = TrajectoryTracker()
    tracker.add_step(
        step_name="TEST_STEP",
        description="Test step",
        input_shape=(10, 10),
        output_shape=(5, 5)
    )
    assert len(tracker.trajectory) == 1
    print("✅ TrajectoryTracker created and tracked step successfully")
except Exception as e:
    print(f"❌ Trajectory tracker tests failed: {str(e)}")

print("\n" + "="*70)
print("✅ Basic functionality verification completed!")
print("ℹ️  Some advanced tests require pandas and other dependencies")
print("="*70)

# Show project structure
print("\n--- Project Structure ---")
import os
for root, dirs, files in os.walk('.', topdown=True):
    if '.git' in root:
        continue
    level = root.replace('.', '').count(os.sep)
    indent = ' ' * 2 * level
    print(f'{indent}{os.path.basename(root)}/')
    subindent = ' ' * 2 * (level + 1)
    for file in files:
        if file.endswith('.py') or file.endswith('.md') or file.endswith('.csv'):
            print(f'{subindent}{file}')