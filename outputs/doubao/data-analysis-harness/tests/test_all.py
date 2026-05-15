import pandas as pd
import numpy as np
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile
import shutil
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.schemas import *
from harness.state import ExecutionStateManager
from harness.tools import ToolRegistry
from harness.context import AnalysisContext, DataContext
from harness.lifecycle import get_default_lifecycle_hooks
from harness.evaluation import TrajectoryTracker
from harness.execution import AnalysisStateMachine
from harness.core import DataAnalysisAgent, AgentHarness
from harness.domain.tools import *


class TestSchemas:
    """Test schema definitions"""

    def test_data_profile(self):
        """Test DataProfile schema"""
        df = pd.DataFrame({
            'a': [1, 2, 3],
            'b': [4.5, 5.5, 6.5],
            'c': ['x', 'y', 'z']
        })

        profile = DataProfile(
            shape=(3, 3),
            columns=['a', 'b', 'c'],
            dtypes={'a': 'int64', 'b': 'float64', 'c': 'object'},
            missing_values={'a': 0, 'b': 0, 'c': 0},
            missing_rate={'a': 0.0, 'b': 0.0, 'c': 0.0},
            summary_stats={
                'a': {'mean': 2.0, 'min': 1.0, 'max': 3.0},
                'b': {'mean': 5.5, 'min': 4.5, 'max': 6.5}
            }
        )

        assert profile.shape == (3, 3)
        assert len(profile.columns) == 3
        assert profile.missing_values['a'] == 0
        print("✓ DataProfile test passed")


class TestStateManagement:
    """Test state management"""

    def test_execution_state_manager(self):
        """Test state manager with snapshots"""
        manager = ExecutionStateManager()

        # Test initial state
        initial_state = manager.get_current_state()
        assert initial_state.current_step == "LOAD"
        assert len(initial_state.dataframes) == 0

        # Add test dataframe
        df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
        initial_state.dataframes["test_df"] = df
        manager.update_current_state(initial_state)

        # Create snapshot
        snapshot_id = manager.create_snapshot("test_snapshot")
        assert snapshot_id in manager.list_snapshots()

        # Test rollback
        assert manager.rollback("test_snapshot")
        assert manager.current_state_id == "test_snapshot"
        assert "test_df" in manager.get_current_state().dataframes

        print("✓ ExecutionStateManager test passed")


class TestDataTools:
    """Test domain tools"""

    def test_data_loader(self):
        """Test CSV data loader"""
        # Create test CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("date,region,product,quantity,unit_price,discount\n")
            f.write("2024-01-01,华北,产品A,10,100,0.1\n")
            f.write("2024-01-02,华东,产品B,20,200,0.2\n")

        try:
            df, validation = DataLoaderTools.load_csv(f.name)
            assert df is not None
            assert validation.is_valid
            assert len(df) == 2
            assert list(df.columns) == ['date', 'region', 'product', 'quantity', 'unit_price', 'discount']
        finally:
            os.unlink(f.name)

        print("✓ DataLoaderTools test passed")

    def test_data_cleaning(self):
        """Test data cleaning tools"""
        df = pd.DataFrame({
            'date': ['2024-01-01', '2024-01-02', '2024-01-03'],
            'region': [None, '华东', '华北'],
            'product': ['A', 'B', None],
            'quantity': [10, -5, 30],
            'unit_price': [100, 200, 300],
            'discount': [1.5, -0.1, 0.2]
        })

        cleaned_df, validation = DataQualityTools.clean_data(df)

        assert validation.is_valid
        assert 'revenue' in cleaned_df.columns
        assert cleaned_df['region'].isnull().sum() == 0
        assert cleaned_df['discount'].between(0, 1).all()
        assert (cleaned_df['quantity'] >= 0).all()

        print("✓ DataQualityTools test passed")


class TestAnalysisTools:
    """Test analysis tools"""

    def test_revenue_calculation(self):
        """Test revenue calculation"""
        df = pd.DataFrame({
            'quantity': [10, 20, 30],
            'unit_price': [100, 200, 300],
            'discount': [0.1, 0.2, 0.3]
        })

        df['revenue'] = df['quantity'] * df['unit_price'] * (1 - df['discount'])

        # Test validation
        validation = ValidationTools.validate_revenue_calculation(df)
        assert validation.is_valid

        # Test manual calculation
        assert abs(df['revenue'].iloc[0] - 900) < 0.01
        assert abs(df['revenue'].iloc[1] - 3200) < 0.01

        print("✓ Revenue calculation test passed")


class TestEvaluation:
    """Test trajectory tracking"""

    def test_trajectory_tracker(self):
        """Test trajectory tracking"""
        tracker = TrajectoryTracker()

        # Add test steps
        tracker.add_step(
            step_name="LOAD_DATA",
            description="Load test data",
            input_shape=(0, 0),
            output_shape=(10, 5)
        )

        tracker.add_step(
            step_name="QUALITY_CHECK",
            description="Check data quality",
            input_shape=(10, 5),
            output_shape=(10, 5),
            validation_result=ValidationResult(is_valid=True, warnings=["Test warning"])
        )

        assert len(tracker.trajectory) == 2
        assert tracker.count_charts() == 0
        assert tracker.count_insights() == 0

        # Test saving
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            pass

        try:
            saved_path = tracker.save_trajectory(f.name)
            assert os.path.exists(saved_path)
        finally:
            os.unlink(f.name)

        print("✓ TrajectoryTracker test passed")


class TestFullIntegration:
    """Test full agent integration"""

    def test_agent_creation(self):
        """Test full agent creation and basic flow"""
        # Create test data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("date,region,product,category,quantity,unit_price,discount,customer_id,channel\n")
            f.write("2024-01-01,华北,坚果礼盒N8,食品,6,168.0,0.25,C032,线上\n")
            f.write("2024-01-01,华东,蓝牙耳机X3,电子产品,8,399.0,0.15,C032,线下\n")
            f.write("2024-01-02,华北,保温杯S2,家居,12,129.0,0.25,C056,线上\n")

        try:
            # Create agent
            agent = DataAnalysisAgent(
                analysis_goal="Test analysis",
                data_file=f.name,
                requirements=["Data overview", "Sales trends"]
            )

            # Test initial state
            assert agent.current_state.current_step == "LOAD"

            # Execute first step
            data, validation = agent.execute_next_step()
            assert data is not None
            assert validation.is_valid
            assert agent.current_state.current_step == "QUALITY_CHECK"

            # Execute quality check
            quality, validation = agent.execute_next_step()
            assert quality is not None
            assert agent.current_state.current_step == "PREPROCESS"

            print("✓ Full integration test passed")

        finally:
            os.unlink(f.name)


def run_all_tests():
    """Run all tests"""
    print("="*80)
    print("Running data analysis agent harness tests")
    print("="*80)
    print()

    try:
        # Run schema tests
        print("1. Testing schemas...")
        schemas_test = TestSchemas()
        schemas_test.test_data_profile()
        print()

        # Run state management tests
        print("2. Testing state management...")
        state_test = TestStateManagement()
        state_test.test_execution_state_manager()
        print()

        # Run data tools tests
        print("3. Testing data tools...")
        data_tools_test = TestDataTools()
        data_tools_test.test_data_loader()
        data_tools_test.test_data_cleaning()
        print()

        # Run analysis tools tests
        print("4. Testing analysis tools...")
        analysis_tools_test = TestAnalysisTools()
        analysis_tools_test.test_revenue_calculation()
        print()

        # Run evaluation tests
        print("5. Testing evaluation...")
        evaluation_test = TestEvaluation()
        evaluation_test.test_trajectory_tracker()
        print()

        # Run full integration tests
        print("6. Running full integration tests...")
        integration_test = TestFullIntegration()
        integration_test.test_agent_creation()
        print()

        print("="*80)
        print("✅ All tests passed successfully!")
        print("="*80)

    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()