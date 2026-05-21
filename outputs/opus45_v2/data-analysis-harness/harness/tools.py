"""
Tool Registry (T) - Analysis tools with typed input/output declarations.

Provides data loading, statistical computation, and visualization capabilities.
"""

import os
import io
import json
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

from harness.state import StateStore


class ToolInput(TypedDict, total=False):
    """Base type for tool inputs."""
    pass


class ToolOutput(TypedDict):
    """Standard tool output format."""
    success: bool
    result: Any
    error: Optional[str]


@dataclass
class ToolDefinition:
    """Definition of an analysis tool."""
    name: str
    description: str
    input_schema: dict[str, type]
    output_schema: dict[str, type]
    func: Callable[..., ToolOutput]
    category: str = "general"


class ToolRegistry:
    """
    Registry for analysis tools.
    Each tool has declared input/output types and belongs to a category.
    """

    def __init__(self, state_store: StateStore, output_dir: Path):
        self.state = state_store
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list[str]:
        """List tools in a specific category."""
        return [name for name, tool in self._tools.items() if tool.category == category]

    def execute(self, name: str, **kwargs) -> ToolOutput:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            return {"success": False, "result": None, "error": f"Unknown tool: {name}"}

        try:
            return tool.func(**kwargs)
        except Exception as e:
            return {"success": False, "result": None, "error": f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"}

    def get_tool_descriptions(self) -> str:
        """Get formatted descriptions of all tools."""
        lines = []
        categories = set(t.category for t in self._tools.values())
        for cat in sorted(categories):
            lines.append(f"\n{cat.upper()} TOOLS:")
            for name, tool in self._tools.items():
                if tool.category == cat:
                    inputs = ", ".join(f"{k}: {v.__name__}" for k, v in tool.input_schema.items())
                    lines.append(f"  - {name}({inputs}): {tool.description}")
        return "\n".join(lines)

    def _register_builtin_tools(self) -> None:
        """Register built-in analysis tools."""

        self.register(ToolDefinition(
            name="load_data",
            description="Load data from CSV, Excel, JSON, or Parquet file",
            input_schema={"path": str, "name": str},
            output_schema={"dataframe_name": str, "shape": tuple, "columns": list},
            func=self._load_data,
            category="data"
        ))

        self.register(ToolDefinition(
            name="get_dataframe",
            description="Get a DataFrame by name",
            input_schema={"name": str},
            output_schema={"exists": bool, "shape": tuple},
            func=self._get_dataframe,
            category="data"
        ))

        self.register(ToolDefinition(
            name="execute_code",
            description="Execute Python code for data analysis. Code can access loaded DataFrames via state.get_dataframe(name).",
            input_schema={"code": str},
            output_schema={"result": Any, "stdout": str},
            func=self._execute_code,
            category="analysis"
        ))

        self.register(ToolDefinition(
            name="compute_statistics",
            description="Compute descriptive statistics for a DataFrame",
            input_schema={"dataframe_name": str, "columns": list},
            output_schema={"statistics": dict},
            func=self._compute_statistics,
            category="analysis"
        ))

        self.register(ToolDefinition(
            name="detect_outliers",
            description="Detect outliers using IQR or Z-score method",
            input_schema={"dataframe_name": str, "column": str, "method": str},
            output_schema={"outlier_count": int, "outlier_indices": list},
            func=self._detect_outliers,
            category="analysis"
        ))

        self.register(ToolDefinition(
            name="compute_correlation",
            description="Compute correlation matrix for numeric columns",
            input_schema={"dataframe_name": str, "columns": list},
            output_schema={"correlation_matrix": dict},
            func=self._compute_correlation,
            category="analysis"
        ))

        self.register(ToolDefinition(
            name="group_aggregate",
            description="Group by columns and aggregate with specified functions",
            input_schema={"dataframe_name": str, "group_by": list, "aggregations": dict},
            output_schema={"result_name": str, "shape": tuple},
            func=self._group_aggregate,
            category="analysis"
        ))

        self.register(ToolDefinition(
            name="save_chart",
            description="Save a matplotlib figure to file",
            input_schema={"figure": object, "name": str, "chart_type": str, "description": str},
            output_schema={"path": str},
            func=self._save_chart,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="create_line_chart",
            description="Create a line chart",
            input_schema={"dataframe_name": str, "x": str, "y": str, "title": str},
            output_schema={"path": str},
            func=self._create_line_chart,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="create_bar_chart",
            description="Create a bar chart",
            input_schema={"dataframe_name": str, "x": str, "y": str, "title": str},
            output_schema={"path": str},
            func=self._create_bar_chart,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="create_scatter_plot",
            description="Create a scatter plot",
            input_schema={"dataframe_name": str, "x": str, "y": str, "title": str},
            output_schema={"path": str},
            func=self._create_scatter_plot,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="create_heatmap",
            description="Create a heatmap (typically for correlation matrix)",
            input_schema={"dataframe_name": str, "title": str},
            output_schema={"path": str},
            func=self._create_heatmap,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="create_boxplot",
            description="Create a box plot",
            input_schema={"dataframe_name": str, "column": str, "title": str},
            output_schema={"path": str},
            func=self._create_boxplot,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="create_histogram",
            description="Create a histogram",
            input_schema={"dataframe_name": str, "column": str, "title": str, "bins": int},
            output_schema={"path": str},
            func=self._create_histogram,
            category="visualization"
        ))

        self.register(ToolDefinition(
            name="record_insight",
            description="Record a data-driven insight (must include specific numbers)",
            input_schema={"insight": str},
            output_schema={"recorded": bool},
            func=self._record_insight,
            category="output"
        ))

        self.register(ToolDefinition(
            name="finish",
            description="Mark analysis as complete",
            input_schema={},
            output_schema={"finished": bool},
            func=self._finish,
            category="control"
        ))

    def _load_data(self, path: str, name: Optional[str] = None) -> ToolOutput:
        """Load data from file."""
        path = Path(path)
        if not path.exists():
            return {"success": False, "result": None, "error": f"File not found: {path}"}

        name = name or path.stem

        try:
            suffix = path.suffix.lower()
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']

            if suffix == '.csv':
                df = None
                for enc in encodings:
                    try:
                        df = pd.read_csv(path, encoding=enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if df is None:
                    df = pd.read_csv(path, encoding='utf-8', errors='replace')
            elif suffix in ['.xlsx', '.xls']:
                df = pd.read_excel(path)
            elif suffix == '.json':
                df = pd.read_json(path)
            elif suffix == '.parquet':
                df = pd.read_parquet(path)
            else:
                return {"success": False, "result": None, "error": f"Unsupported file type: {suffix}"}

            self.state.set_dataframe(name, df)

            return {
                "success": True,
                "result": {
                    "dataframe_name": name,
                    "shape": df.shape,
                    "columns": list(df.columns),
                    "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
                },
                "error": None
            }
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}

    def _get_dataframe(self, name: str) -> ToolOutput:
        """Get DataFrame info."""
        df = self.state.get_dataframe(name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {name}"}

        return {
            "success": True,
            "result": {"exists": True, "shape": df.shape, "columns": list(df.columns)},
            "error": None
        }

    def _execute_code(self, code: str) -> ToolOutput:
        """Execute Python code with access to DataFrames."""
        stdout_capture = io.StringIO()

        local_vars = {
            "pd": pd,
            "np": np,
            "plt": plt,
            "sns": sns,
            "state": self.state,
            "output_dir": self.output_dir,
        }

        for name in self.state.list_dataframes():
            local_vars[name] = self.state.get_dataframe(name)

        self.state.record_code(code)

        try:
            import sys
            old_stdout = sys.stdout
            sys.stdout = stdout_capture

            exec(code, {"__builtins__": __builtins__}, local_vars)

            sys.stdout = old_stdout
            stdout_str = stdout_capture.getvalue()

            result = local_vars.get("result", None)

            for var_name, var_value in local_vars.items():
                if isinstance(var_value, pd.DataFrame) and var_name not in ["pd", "np", "plt", "sns", "state"]:
                    existing = self.state.get_dataframe(var_name)
                    if existing is None or not var_value.equals(existing):
                        self.state.set_dataframe(var_name, var_value)

            if isinstance(result, pd.DataFrame):
                self.state.record_output_shape({"rows": len(result), "cols": len(result.columns)})
            elif isinstance(result, (list, dict)):
                self.state.record_output_shape({"type": type(result).__name__, "len": len(result)})

            return {
                "success": True,
                "result": str(result) if result is not None else stdout_str,
                "error": None
            }
        except Exception as e:
            import sys
            sys.stdout = old_stdout
            return {"success": False, "result": None, "error": f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"}

    def _compute_statistics(self, dataframe_name: str, columns: Optional[list] = None) -> ToolOutput:
        """Compute descriptive statistics."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        if columns:
            df = df[columns]

        numeric_df = df.select_dtypes(include=[np.number])
        if numeric_df.empty:
            return {"success": False, "result": None, "error": "No numeric columns found"}

        stats = numeric_df.describe().to_dict()

        for col in numeric_df.columns:
            stats[col]["skewness"] = float(numeric_df[col].skew())
            stats[col]["kurtosis"] = float(numeric_df[col].kurtosis())
            stats[col]["null_count"] = int(df[col].isnull().sum())

        return {"success": True, "result": {"statistics": stats}, "error": None}

    def _detect_outliers(self, dataframe_name: str, column: str, method: str = "iqr") -> ToolOutput:
        """Detect outliers using IQR or Z-score."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        if column not in df.columns:
            return {"success": False, "result": None, "error": f"Column not found: {column}"}

        series = df[column].dropna()

        if method.lower() == "iqr":
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            outliers = (series < lower) | (series > upper)
        elif method.lower() == "zscore":
            z_scores = np.abs((series - series.mean()) / series.std())
            outliers = z_scores > 3
        else:
            return {"success": False, "result": None, "error": f"Unknown method: {method}. Use 'iqr' or 'zscore'."}

        outlier_indices = series[outliers].index.tolist()

        return {
            "success": True,
            "result": {
                "outlier_count": len(outlier_indices),
                "outlier_indices": outlier_indices[:100],
                "outlier_percentage": len(outlier_indices) / len(series) * 100
            },
            "error": None
        }

    def _compute_correlation(self, dataframe_name: str, columns: Optional[list] = None) -> ToolOutput:
        """Compute correlation matrix."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        if columns:
            df = df[columns]

        numeric_df = df.select_dtypes(include=[np.number])
        if numeric_df.empty:
            return {"success": False, "result": None, "error": "No numeric columns found"}

        corr = numeric_df.corr()
        self.state.set_dataframe(f"{dataframe_name}_correlation", corr)

        corr_dict = corr.round(4).to_dict()

        return {
            "success": True,
            "result": {
                "correlation_matrix": corr_dict,
                "saved_as": f"{dataframe_name}_correlation"
            },
            "error": None
        }

    def _group_aggregate(self, dataframe_name: str, group_by: list, aggregations: dict) -> ToolOutput:
        """Group by and aggregate."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        try:
            result = df.groupby(group_by).agg(aggregations).reset_index()
            result_name = f"{dataframe_name}_grouped"
            self.state.set_dataframe(result_name, result)

            return {
                "success": True,
                "result": {
                    "result_name": result_name,
                    "shape": result.shape,
                    "columns": list(result.columns)
                },
                "error": None
            }
        except Exception as e:
            return {"success": False, "result": None, "error": str(e)}

    def _save_chart(self, figure: plt.Figure, name: str, chart_type: str, description: str) -> ToolOutput:
        """Save matplotlib figure."""
        charts_dir = self.output_dir / "charts"
        charts_dir.mkdir(exist_ok=True)

        filename = f"{name}.png"
        filepath = charts_dir / filename

        figure.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(figure)

        self.state.add_chart(str(filepath), chart_type, description)

        return {"success": True, "result": {"path": str(filepath)}, "error": None}

    def _create_line_chart(self, dataframe_name: str, x: str, y: str, title: str,
                          hue: Optional[str] = None) -> ToolOutput:
        """Create line chart."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        fig, ax = plt.subplots(figsize=(10, 6))

        if hue:
            sns.lineplot(data=df, x=x, y=y, hue=hue, ax=ax)
        else:
            sns.lineplot(data=df, x=x, y=y, ax=ax)

        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        plt.xticks(rotation=45)
        plt.tight_layout()

        return self._save_chart(fig, f"line_{x}_{y}", "line", title)

    def _create_bar_chart(self, dataframe_name: str, x: str, y: str, title: str,
                         hue: Optional[str] = None) -> ToolOutput:
        """Create bar chart."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        fig, ax = plt.subplots(figsize=(10, 6))

        if hue:
            sns.barplot(data=df, x=x, y=y, hue=hue, ax=ax)
        else:
            sns.barplot(data=df, x=x, y=y, ax=ax)

        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        plt.xticks(rotation=45)
        plt.tight_layout()

        return self._save_chart(fig, f"bar_{x}_{y}", "bar", title)

    def _create_scatter_plot(self, dataframe_name: str, x: str, y: str, title: str,
                            hue: Optional[str] = None) -> ToolOutput:
        """Create scatter plot."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        fig, ax = plt.subplots(figsize=(10, 6))

        if hue:
            sns.scatterplot(data=df, x=x, y=y, hue=hue, ax=ax)
        else:
            sns.scatterplot(data=df, x=x, y=y, ax=ax)

        ax.set_title(title)
        ax.set_xlabel(x)
        ax.set_ylabel(y)
        plt.tight_layout()

        return self._save_chart(fig, f"scatter_{x}_{y}", "scatter", title)

    def _create_heatmap(self, dataframe_name: str, title: str, annot: bool = True) -> ToolOutput:
        """Create heatmap."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        fig, ax = plt.subplots(figsize=(12, 10))

        sns.heatmap(df, annot=annot, cmap='coolwarm', center=0, ax=ax, fmt='.2f')
        ax.set_title(title)
        plt.tight_layout()

        return self._save_chart(fig, f"heatmap_{dataframe_name}", "heatmap", title)

    def _create_boxplot(self, dataframe_name: str, column: str, title: str,
                       by: Optional[str] = None) -> ToolOutput:
        """Create box plot."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        fig, ax = plt.subplots(figsize=(10, 6))

        if by:
            sns.boxplot(data=df, x=by, y=column, ax=ax)
            plt.xticks(rotation=45)
        else:
            sns.boxplot(data=df, y=column, ax=ax)

        ax.set_title(title)
        plt.tight_layout()

        return self._save_chart(fig, f"boxplot_{column}", "boxplot", title)

    def _create_histogram(self, dataframe_name: str, column: str, title: str,
                         bins: int = 30) -> ToolOutput:
        """Create histogram."""
        df = self.state.get_dataframe(dataframe_name)
        if df is None:
            return {"success": False, "result": None, "error": f"DataFrame not found: {dataframe_name}"}

        fig, ax = plt.subplots(figsize=(10, 6))

        sns.histplot(data=df, x=column, bins=bins, ax=ax, kde=True)
        ax.set_title(title)
        plt.tight_layout()

        return self._save_chart(fig, f"histogram_{column}", "histogram", title)

    def _record_insight(self, insight: str) -> ToolOutput:
        """Record a data-driven insight."""
        has_numbers = any(c.isdigit() for c in insight)
        if not has_numbers:
            return {
                "success": False,
                "result": None,
                "error": "Insight must contain specific numbers from the data. Example: 'Revenue increased 23% from $1.2M to $1.5M'"
            }

        self.state.add_insight(insight)
        return {"success": True, "result": {"recorded": True}, "error": None}

    def _finish(self) -> ToolOutput:
        """Mark analysis as complete."""
        return {"success": True, "result": {"finished": True}, "error": None}
