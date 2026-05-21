"""
Tool Registry component - registers and manages analysis tools
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Type
from pathlib import Path
from abc import ABC, abstractmethod


class ToolResult:
    """Represents the result of a tool execution"""
    def __init__(
        self,
        data_updates: Dict[str, Any] = None,
        context_updates: Dict[str, Any] = None,
        insights: List[str] = None,
        charts: List[Dict[str, str]] = None,
        input_shape: Tuple = None,
        output_shape: Tuple = None
    ):
        self.data_updates = data_updates or {}
        self.context_updates = context_updates or {}
        self.insights = insights or []
        self.charts = charts or []
        self.input_shape = input_shape
        self.output_shape = output_shape


class BaseTool(ABC):
    """Abstract base class for all analysis tools"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        """Execute the tool with given parameters and current data"""
        pass


class LoadDataTool(BaseTool):
    """Tool for loading data files"""

    def __init__(self):
        super().__init__(
            name="load_data",
            description="Load data from files (CSV/Excel/JSON/Parquet)"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        data_files = params.get("data_files", [])
        if not data_files:
            return ToolResult(
                error="No data files provided"
            )

        dfs = []
        for file_path in data_files:
            ext = Path(file_path).suffix.lower()

            try:
                if ext == '.csv':
                    df = pd.read_csv(file_path)
                elif ext in ['.xlsx', '.xls']:
                    df = pd.read_excel(file_path)
                elif ext == '.json':
                    df = pd.read_json(file_path)
                elif ext in ['.parquet', '.pq']:
                    df = pd.read_parquet(file_path)
                else:
                    continue

                dfs.append(df)
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                continue

        # Combine multiple dataframes if needed
        df = pd.concat(dfs) if len(dfs) > 1 else dfs[0] if dfs else None

        if df is None:
            return ToolResult(
                error="Could not load any data files"
            )

        return ToolResult(
            data_updates={"df": df, "original_df": df.copy()},
            input_shape=(0, 0),
            output_shape=df.shape
        )


class DataQualityTool(BaseTool):
    """Tool for assessing data quality"""

    def __init__(self):
        super().__init__(
            name="assess_data_quality",
            description="Assess data quality: missing values, duplicates, outliers"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        # Calculate missing values
        missing = df.isnull().sum()
        missing_percent = (missing / len(df)) * 100

        # Calculate duplicates
        duplicates = df.duplicated().sum()
        duplicates_percent = (duplicates / len(df)) * 100

        # Detect outliers using IQR method for numeric columns
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        outlier_info = {}

        for col in numeric_cols:
            q1 = df[col].quantile(0.25)
            q3 = df[col].quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            outliers = df[(df[col] < lower_bound) | (df[col] > upper_bound)][col]
            outlier_info[col] = {
                "count": len(outliers),
                "percent": (len(outliers) / len(df)) * 100,
                "lower_bound": lower_bound,
                "upper_bound": upper_bound
            }

        # Generate insights
        insights = []
        insights.append(f"Dataset shape: {df.shape[0]} rows, {df.shape[1]} columns")
        insights.append(f"Missing values: {missing.sum()} total ({missing_percent.sum():.2f}%)")
        insights.append(f"Duplicate rows: {duplicates} ({duplicates_percent:.2f}%)")

        for col in missing[missing > 0].index:
            insights.append(f"  - {col}: {missing[col]} missing ({missing_percent[col]:.2f}%)")

        insights.append(f"\nOutliers detected in {len([c for c in outlier_info if outlier_info[c]['count'] > 0])} columns")

        return ToolResult(
            data_updates={
                "data_quality": {
                    "missing_values": missing.to_dict(),
                    "missing_percent": missing_percent.to_dict(),
                    "duplicates": duplicates,
                    "duplicates_percent": duplicates_percent,
                    "outliers": outlier_info
                }
            },
            insights=insights,
            input_shape=df.shape,
            output_shape=(len(missing), 6)
        )


class DescriptiveStatsTool(BaseTool):
    """Tool for generating descriptive statistics"""

    def __init__(self):
        super().__init__(
            name="descriptive_stats",
            description="Generate descriptive statistics for numeric columns"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        numeric_df = df.select_dtypes(include=[np.number])
        stats = numeric_df.describe().transpose()

        # Add additional statistics
        stats['median'] = numeric_df.median()
        stats['variance'] = numeric_df.var()
        stats['skew'] = numeric_df.skew()
        stats['kurtosis'] = numeric_df.kurtosis()

        insights = []
        insights.append(f"Descriptive statistics for {len(numeric_df.columns)} numeric columns:")

        for col in numeric_df.columns:
            if col in stats.index:
                insights.append(f"  - {col}: mean={stats.loc[col, 'mean']:.2f}, median={stats.loc[col, 'median']:.2f}")

        return ToolResult(
            data_updates={"descriptive_stats": stats.to_dict()},
            insights=insights,
            input_shape=df.shape,
            output_shape=stats.shape
        )


class CorrelationAnalysisTool(BaseTool):
    """Tool for correlation analysis"""

    def __init__(self):
        super().__init__(
            name="correlation_analysis",
            description="Analyze correlations between numeric variables"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        numeric_df = df.select_dtypes(include=[np.number])
        if len(numeric_df.columns) < 2:
            return ToolResult(error="Need at least 2 numeric columns for correlation analysis")

        corr_matrix = numeric_df.corr()

        # Generate chart
        output_dir = current_data.get("output_dir", ".")
        chart_path = os.path.join(output_dir, f"correlation_heatmap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

        plt.figure(figsize=(12, 8))
        sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', vmin=-1, vmax=1, center=0)
        plt.title("Correlation Heatmap")
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()

        # Find strong correlations
        strong_correlations = []
        threshold = params.get("threshold", 0.7)

        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                corr_val = corr_matrix.iloc[i, j]
                if abs(corr_val) >= threshold:
                    strong_correlations.append({
                        "var1": corr_matrix.columns[i],
                        "var2": corr_matrix.columns[j],
                        "correlation": corr_val
                    })

        insights = []
        insights.append(f"Correlation analysis found {len(strong_correlations)} strong correlations (|r| >= {threshold}):")

        for corr in strong_correlations:
            insights.append(f"  - {corr['var1']} & {corr['var2']}: {corr['correlation']:.2f}")

        return ToolResult(
            data_updates={"correlation_matrix": corr_matrix.to_dict()},
            insights=insights,
            charts=[{
                "path": chart_path,
                "chart_type": "heatmap",
                "description": f"Correlation heatmap of numeric variables"
            }],
            input_shape=df.shape,
            output_shape=corr_matrix.shape
        )


class GroupedAnalysisTool(BaseTool):
    """Tool for grouped analysis"""

    def __init__(self):
        super().__init__(
            name="grouped_analysis",
            description="Perform grouped analysis by categorical columns"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        group_by = params.get("group_by")
        if not group_by:
            # Auto-select first categorical column
            cat_cols = df.select_dtypes(include=['object', 'category']).columns
            if len(cat_cols) > 0:
                group_by = cat_cols[0]
            else:
                return ToolResult(error="No categorical columns found for grouping")

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) == 0:
            return ToolResult(error="No numeric columns found for grouped analysis")

        # Perform grouping
        grouped = df.groupby(group_by)[numeric_cols].agg(['mean', 'median', 'count', 'std'])

        # Generate chart
        output_dir = current_data.get("output_dir", ".")
        chart_path = os.path.join(output_dir, f"grouped_analysis_{group_by}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

        plt.figure(figsize=(12, 6))
        sns.boxplot(data=df, x=group_by, y=numeric_cols[0])
        plt.title(f"{numeric_cols[0]} by {group_by}")
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()

        insights = []
        insights.append(f"Grouped analysis by {group_by}:")
        insights.append(f"  Groups found: {len(grouped)}")

        for col in numeric_cols[:3]:  # Show top 3 numeric columns
            if col in grouped.columns:
                mean_val = grouped[col]['mean'].mean()
                insights.append(f"  - {col}: overall mean={mean_val:.2f}")

        return ToolResult(
            data_updates={"grouped_analysis": grouped.to_dict(), "last_group_by": group_by},
            insights=insights,
            charts=[{
                "path": chart_path,
                "chart_type": "boxplot",
                "description": f"Grouped analysis of {numeric_cols[0]} by {group_by}"
            }],
            input_shape=df.shape,
            output_shape=grouped.shape
        )


class TrendAnalysisTool(BaseTool):
    """Tool for trend analysis"""

    def __init__(self):
        super().__init__(
            name="trend_analysis",
            description="Analyze trends over time"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        date_col = params.get("date_col")
        value_col = params.get("value_col")

        # Auto-detect date and value columns if not provided
        if not date_col:
            date_candidates = df.select_dtypes(include=['datetime64']).columns
            if len(date_candidates) > 0:
                date_col = date_candidates[0]
            else:
                # Try to detect date-like columns
                for col in df.columns:
                    try:
                        pd.to_datetime(df[col])
                        date_col = col
                        break
                    except:
                        pass
                if not date_col:
                    return ToolResult(error="No date column found for trend analysis")

        if not value_col:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                value_col = numeric_cols[0]
            else:
                return ToolResult(error="No numeric columns found for trend analysis")

        # Convert date column to datetime
        df[date_col] = pd.to_datetime(df[date_col])
        df_sorted = df.sort_values(date_col)

        # Resample by time period
        resampled = df_sorted.set_index(date_col).resample('D')[value_col].mean()

        # Generate chart
        output_dir = current_data.get("output_dir", ".")
        chart_path = os.path.join(output_dir, f"trend_analysis_{date_col}_{value_col}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

        plt.figure(figsize=(12, 6))
        # Convert to dataframe for seaborn
        plot_data = pd.DataFrame({
            date_col: resampled.index,
            value_col: resampled.values
        })
        sns.lineplot(data=plot_data, x=date_col, y=value_col)
        plt.title(f"Trend of {value_col} over {date_col}")
        plt.xlabel(date_col)
        plt.ylabel(value_col)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()

        insights = []
        insights.append(f"Trend analysis for {value_col} by {date_col}:")
        insights.append(f"  Time range: {resampled.index.min()} to {resampled.index.max()}")
        insights.append(f"  Average {value_col}: {resampled.mean():.2f}")

        return ToolResult(
            data_updates={"trend_data": resampled.to_dict(), "last_trend": {
                "date_col": date_col,
                "value_col": value_col
            }},
            insights=insights,
            charts=[{
                "path": chart_path,
                "chart_type": "linechart",
                "description": f"Trend of {value_col} over {date_col}"
            }],
            input_shape=df.shape,
            output_shape=resampled.shape
        )


class DistributionAnalysisTool(BaseTool):
    """Tool for distribution analysis"""

    def __init__(self):
        super().__init__(
            name="distribution_analysis",
            description="Analyze distribution of numeric variables"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) == 0:
            return ToolResult(error="No numeric columns found for distribution analysis")

        # Analyze first numeric column by default
        col = params.get("column", numeric_cols[0])

        # Generate statistics
        mean = df[col].mean()
        median = df[col].median()
        std = df[col].std()
        skewness = df[col].skew()
        kurtosis = df[col].kurtosis()

        # Generate chart
        output_dir = current_data.get("output_dir", ".")
        chart_path = os.path.join(output_dir, f"distribution_{col}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

        plt.figure(figsize=(12, 6))

        # Histogram with density curve
        sns.histplot(data=df, x=col, kde=True)
        plt.axvline(mean, color='r', linestyle='--', label=f'Mean: {mean:.2f}')
        plt.axvline(median, color='g', linestyle='--', label=f'Median: {median:.2f}')
        plt.title(f"Distribution of {col}")
        plt.xlabel(col)
        plt.ylabel("Frequency")
        plt.legend()
        plt.tight_layout()
        plt.savefig(chart_path, dpi=300, bbox_inches='tight')
        plt.close()

        insights = []
        insights.append(f"Distribution analysis for {col}:")
        insights.append(f"  Mean: {mean:.2f}, Median: {median:.2f}")
        insights.append(f"  Std Dev: {std:.2f}")
        insights.append(f"  Skewness: {skewness:.2f}")
        insights.append(f"  Kurtosis: {kurtosis:.2f}")

        return ToolResult(
            data_updates={"distribution_stats": {
                "column": col,
                "mean": mean,
                "median": median,
                "std": std,
                "skewness": skewness,
                "kurtosis": kurtosis
            }},
            insights=insights,
            charts=[{
                "path": chart_path,
                "chart_type": "histogram",
                "description": f"Distribution analysis of {col}"
            }],
            input_shape=df.shape,
            output_shape=(6,)
        )


class ExploratoryAnalysisTool(BaseTool):
    """Tool for general exploratory analysis"""

    def __init__(self):
        super().__init__(
            name="exploratory_analysis",
            description="Perform general exploratory data analysis"
        )

    def execute(self, current_data: Dict[str, Any], params: Dict[str, Any]) -> ToolResult:
        df = current_data.get("df")
        if df is None:
            return ToolResult(error="No dataframe found")

        insights = []
        charts = []

        # Quick overview
        insights.append(f"Exploratory analysis complete. Dataset has {df.shape[0]} rows and {df.shape[1]} columns.")

        # Check data types
        dtype_counts = df.dtypes.value_counts()
        insights.append(f"\nData types:")
        for dtype, count in dtype_counts.items():
            insights.append(f"  - {dtype}: {count} columns")

        # Numeric columns summary
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if len(numeric_cols) > 0:
            insights.append(f"\nNumeric columns ({len(numeric_cols)}):")
            for col in numeric_cols[:5]:  # Show top 5
                insights.append(f"  - {col}: range={df[col].min():.2f} to {df[col].max():.2f}")

        # Categorical columns summary
        cat_cols = df.select_dtypes(include=['object', 'category']).columns
        if len(cat_cols) > 0:
            insights.append(f"\nCategorical columns ({len(cat_cols)}):")
            for col in cat_cols[:5]:  # Show top 5
                insights.append(f"  - {col}: {df[col].nunique()} unique values")

        return ToolResult(
            insights=insights,
            input_shape=df.shape,
            output_shape=(len(numeric_cols) + len(cat_cols),)
        )


class ToolRegistry:
    """Registry for all analysis tools"""

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register all default tools"""
        self.register_tool(LoadDataTool())
        self.register_tool(DataQualityTool())
        self.register_tool(DescriptiveStatsTool())
        self.register_tool(CorrelationAnalysisTool())
        self.register_tool(GroupedAnalysisTool())
        self.register_tool(TrendAnalysisTool())
        self.register_tool(DistributionAnalysisTool())
        self.register_tool(ExploratoryAnalysisTool())

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool in the registry"""
        self.tools[tool.name] = tool

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """Get a tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """List all registered tool names"""
        return list(self.tools.keys())

    def get_tool_descriptions(self) -> Dict[str, str]:
        """Get descriptions of all registered tools"""
        return {name: tool.description for name, tool in self.tools.items()}