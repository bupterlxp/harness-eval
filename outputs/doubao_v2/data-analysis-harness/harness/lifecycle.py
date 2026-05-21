"""
Lifecycle Hooks component - handles boundary checks and validation
"""

import os
import pandas as pd
from typing import List, Dict, Any, Optional


class LifecycleHooks:
    """Implements lifecycle hooks for execution boundaries"""

    def __init__(self):
        self.max_data_size = 100_000_000  # 100MB max memory usage
        self.min_rows = 1
        self.min_columns = 1
        self.max_chart_data_points = 10_000

    def on_before_execution(self, data_files: List[str], analysis_goal: str, output_dir: str) -> None:
        """Hook executed before analysis starts"""
        self._check_data_files(data_files)
        self._check_output_directory(output_dir)
        print(f"Starting analysis with goal: {analysis_goal}")
        print(f"Found {len(data_files)} data files")

    def on_after_execution(self, data: Dict[str, Any], insights: List[str], charts: List[Dict[str, str]]) -> None:
        """Hook executed after analysis completes"""
        self._validate_outputs(data, insights, charts)
        print(f"\nAnalysis completed!")
        print(f"Generated {len(insights)} insights")
        print(f"Generated {len(charts)} charts")

    def on_execution_failure(self, error_message: str) -> None:
        """Hook executed when analysis fails"""
        print(f"\nAnalysis failed: {error_message}")

    def on_step_complete(self, step: int, tool_name: str, result: Any) -> None:
        """Hook executed after each tool step"""
        pass

    def _check_data_files(self, data_files: List[str]) -> None:
        """Validate data files before execution"""
        if not data_files:
            raise ValueError("No data files found in current directory")

        for file_path in data_files:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Data file not found: {file_path}")

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                raise ValueError(f"Data file is empty: {file_path}")

        print(f"Validated {len(data_files)} data files")

    def _check_output_directory(self, output_dir: str) -> None:
        """Validate output directory"""
        os.makedirs(output_dir, exist_ok=True)
        if not os.access(output_dir, os.W_OK):
            raise PermissionError(f"Output directory is not writable: {output_dir}")

        print(f"Using output directory: {output_dir}")

    def _validate_outputs(self, data: Dict[str, Any], insights: List[str], charts: List[Dict[str, str]]) -> None:
        """Validate final outputs"""
        # Check if we have a dataframe
        df = data.get("df")
        if df is None:
            raise ValueError("No dataframe found after analysis")

        # Validate insights
        if not insights:
            print("Warning: No insights were generated")

        # Validate charts
        for chart in charts:
            if not os.path.exists(chart["path"]):
                print(f"Warning: Chart file not found: {chart['path']}")

        # Validate data integrity
        if len(df) == 0:
            raise ValueError("Dataframe is empty after analysis")

    def check_data_quality(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Check data quality before processing"""
        issues = {}

        # Check minimum size
        if len(df) < self.min_rows:
            issues["too_few_rows"] = f"Dataset has only {len(df)} rows, minimum required is {self.min_rows}"

        if len(df.columns) < self.min_columns:
            issues["too_few_columns"] = f"Dataset has only {len(df.columns)} columns, minimum required is {self.min_columns}"

        # Check for missing values
        total_missing = df.isnull().sum().sum()
        if total_missing > 0:
            issues["missing_values"] = f"Dataset has {total_missing} missing values"

        # Check memory size
        memory_usage = df.memory_usage(deep=True).sum()
        if memory_usage > self.max_data_size:
            issues["data_too_large"] = f"Dataset uses {memory_usage / 1e6:.2f}MB memory, max allowed is {self.max_data_size / 1e6:.2f}MB"

        return issues

    def should_skip_charting(self, df: pd.DataFrame) -> bool:
        """Check if we should skip chart generation due to data size"""
        total_points = len(df) * len(df.columns)
        return total_points > self.max_chart_data_points

    def validate_tool_input(self, tool_name: str, input_data: Dict[str, Any]) -> None:
        """Validate input before tool execution"""
        if "df" not in input_data:
            raise ValueError(f"Tool {tool_name} requires a dataframe but none was found")

        df = input_data["df"]
        if len(df) == 0:
            raise ValueError(f"Tool {tool_name} cannot operate on empty dataframe")

        # Additional validation based on tool type
        if tool_name in ["correlation_analysis", "grouped_analysis"]:
            numeric_cols = df.select_dtypes(include=["number"]).columns
            if len(numeric_cols) < 2:
                raise ValueError(f"Tool {tool_name} requires at least 2 numeric columns")

        if tool_name == "trend_analysis":
            date_cols = []
            for col in df.columns:
                try:
                    pd.to_datetime(df[col])
                    date_cols.append(col)
                except:
                    pass
            if not date_cols:
                raise ValueError(f"Tool {tool_name} requires at least one date/datetime column")