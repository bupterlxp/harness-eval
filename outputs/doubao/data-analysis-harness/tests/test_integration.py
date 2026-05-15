#!/usr/bin/env python3
"""Integration tests for data analysis agent harness"""

import pandas as pd
import numpy as np
import os
import sys
import tempfile
import shutil
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.core import DataAnalysisAgent, AgentHarness
from harness.domain.tools import DataLoaderTools, DataQualityTools


class TestSalesDataAnalysis:
    """Test complete sales data analysis workflow"""

    def setup_method(self):
        """Setup test environment"""
        # Create temporary directory for test outputs
        self.temp_dir = tempfile.mkdtemp()

        # Create test sales data similar to the sample
        self.test_data = """date,region,product,category,quantity,unit_price,discount,customer_id,channel
2024-01-01,华北,坚果礼盒N8,食品,6,168.0,0.25,C032,线上
2024-01-01,华东,蓝牙耳机X3,电子产品,8,399.0,0.15,C032,线下
2024-01-01,华南,台灯L1,家居,29,199.0,0.05,C055,线下
2024-01-02,华北,保温杯S2,家居,12,129.0,0.25,C056,线上
2024-01-03,华东,平板电脑T10,电子产品,20,2499.0,1.2,C039,线下
2024-01-04,西北,坚果礼盒N8,食品,25,168.0,0.2,C069,线上
"""

        # Create test file
        self.test_file = os.path.join(self.temp_dir, "test_sales.csv")
        with open(self.test_file, 'w') as f:
            f.write(self.test_data)

    def teardown_method(self):
        """Cleanup test environment"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_full_analysis_flow(self):
        """Test complete analysis workflow with sample data"""
        # Create agent
        agent = DataAnalysisAgent(
            analysis_goal="Test sales analysis for January 2024",
            data_file=self.test_file,
            requirements=[
                "Data overview and quality checks",
                "Sales trend analysis",
                "Regional sales comparison",
                "Category performance analysis",
                "Key business insights"
            ]
        )

        # Track the flow
        steps_executed = []

        # Step 1: Load data
        data, validation = agent.execute_next_step()
        steps_executed.append("LOAD")
        assert validation.is_valid
        assert len(data) == 6
        assert 'revenue' not in data.columns  # Should be added in preprocess

        # Step 2: Quality check
        quality_result, validation = agent.execute_next_step()
        steps_executed.append("QUALITY_CHECK")
        assert validation is not None
        assert 'anomalies' in quality_result

        # Step 3: Preprocess
        processed_df, validation = agent.execute_next_step()
        steps_executed.append("PREPROCESS")
        assert validation.is_valid
        assert 'revenue' in processed_df.columns
        assert processed_df['discount'].between(0, 1).all()

        # Step 4: Explore
        stats, validation = agent.execute_next_step()
        steps_executed.append("EXPLORE")
        assert validation.is_valid
        assert stats['total_revenue'] > 0

        # Check revenue calculation
        expected_revenue = 6 * 168.0 * (1 - 0.25) + 8 * 399.0 * (1 - 0.15) + 29 * 199.0 * (1 - 0.05)
        expected_revenue += 12 * 129.0 * (1 - 0.25) + 20 * 2499.0 * (1 - 1.2) + 25 * 168.0 * (1 - 0.2)
        assert abs(stats['total_revenue'] - expected_revenue) < 0.01

        print(f"✓ Completed steps: {', '.join(steps_executed)}")
        print(f"✓ Total revenue calculated: ${stats['total_revenue']:,.2f}")

    def test_data_quality_anomalies(self):
        """Test data quality detection"""
        # Load test data
        df, _ = DataLoaderTools.load_csv(self.test_file)

        # Introduce anomalies
        df.loc[6] = ["2024-01-05", None, "InvalidProduct", "Unknown", 150, 100, 1.5, "C001", "online"]
        df.loc[7] = ["2024-01-06", "华东", "BadProduct", "Electronics", -5, 200, 0.1, "C002", "offline"]

        # Detect anomalies
        anomalies = DataQualityTools.detect_anomalies(df)
        assert len(anomalies["invalid_discount"]) > 0
        assert len(anomalies["large_quantity"]) > 0
        assert len(anomalies["negative_values"]) > 0

        # Test cleaning
        cleaned_df, validation = DataQualityTools.clean_data(df)
        assert validation.is_valid
        assert cleaned_df['region'].isnull().sum() == 0
        assert cleaned_df['discount'].between(0, 1).all()
        assert (cleaned_df['quantity'] >= 0).all()

        print("✓ Data quality anomaly detection and cleaning works correctly")

    def test_revenue_calculation(self):
        """Test revenue calculation accuracy"""
        df, _ = DataLoaderTools.load_csv(self.test_file)

        # Add revenue calculation
        df['revenue'] = df['quantity'] * df['unit_price'] * (1 - df['discount'])

        # Check first row calculation
        row0 = df.iloc[0]
        calculated = row0['quantity'] * row0['unit_price'] * (1 - row0['discount'])
        assert abs(row0['revenue'] - calculated) < 0.01

        # Check with known values
        expected = 6 * 168.0 * 0.75  # 6*168=1008 * 0.75=756
        assert abs(row0['revenue'] - 756) < 0.01

        print("✓ Revenue calculation is accurate")


def test_agent_harness_api():
    """Test the AgentHarness high-level API"""
    # Create temporary test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("date,region,product,quantity,unit_price,discount\n")
        f.write("2024-01-01,华北,产品A,10,100,0.1\n")
        f.write("2024-01-02,华东,产品B,20,200,0.2\n")
        f.write("2024-01-03,华南,产品C,30,300,0.3\n")

    try:
        # Run standard analysis
        results = AgentHarness.run_standard_analysis(
            data_file=f.name,
            analysis_goal="Test API analysis",
            requirements=["Data overview", "Basic analysis"]
        )

        assert results["success"] is True
        assert "load" in results
        assert "quality_check" in results
        assert "preprocess" in results
        assert "save_paths" in results

        print("✓ AgentHarness API works correctly")

    finally:
        os.unlink(f.name)


def run_integration_tests():
    """Run all integration tests"""
    print("="*70)
    print("Running Data Analysis Agent Harness Integration Tests")
    print("="*70)

    try:
        # Test 1: Basic sales analysis flow
        print("\n--- Test 1: Complete sales analysis workflow ---")
        test1 = TestSalesDataAnalysis()
        test1.setup_method()
        try:
            test1.test_full_analysis_flow()
            test1.test_data_quality_anomalies()
            test1.test_revenue_calculation()
        finally:
            test1.teardown_method()

        # Test 2: AgentHarness API
        print("\n--- Test 2: AgentHarness API ---")
        test_agent_harness_api()

        print("\n" + "="*70)
        print("✅ All integration tests passed!")
        print("="*70)

    except Exception as e:
        print(f"\n❌ Integration test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_integration_tests()