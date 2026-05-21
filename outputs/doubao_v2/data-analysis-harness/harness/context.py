"""
Context Manager component - manages LLM context efficiently without stuffing full DataFrames
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List


class ContextManager:
    """Manages context efficiently using schema and statistical summaries"""

    def __init__(self, max_context_size: int = 100000):
        self.max_context_size = max_context_size
        self.cache: Dict[str, Any] = {}

    def clear_cache(self) -> None:
        """Clear the context cache"""
        self.cache.clear()

    def _get_dataframe_schema(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Extract schema information from a DataFrame"""
        schema = {
            "columns": [],
            "dtypes": {},
            "shape": df.shape,
            "memory_usage": df.memory_usage(deep=True).sum()
        }

        for col in df.columns:
            schema["columns"].append(col)
            schema["dtypes"][col] = str(df[col].dtype)

        return schema

    def _get_dataframe_summary(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Extract statistical summary from a DataFrame"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        categorical_cols = df.select_dtypes(include=['object', 'category']).columns

        summary = {
            "numeric_columns": {},
            "categorical_columns": {},
            "missing_values": int(df.isnull().sum().sum()),
            "total_rows": len(df),
            "total_columns": len(df.columns)
        }

        # Summary for numeric columns
        for col in numeric_cols:
            col_series = df[col].dropna()
            if len(col_series) == 0:
                continue

            summary["numeric_columns"][col] = {
                "mean": float(col_series.mean()),
                "median": float(col_series.median()),
                "std": float(col_series.std()),
                "min": float(col_series.min()),
                "max": float(col_series.max()),
                "25%": float(col_series.quantile(0.25)),
                "75%": float(col_series.quantile(0.75)),
                "unique_values": int(df[col].nunique())
            }

        # Summary for categorical columns
        for col in categorical_cols:
            summary["categorical_columns"][col] = {
                "unique_values": int(df[col].nunique()),
                "top_values": df[col].value_counts().head(5).to_dict()
            }

        return summary

    def update_context(self, current_context: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update context with new information efficiently"""
        context = current_context.copy()

        # Merge updates
        for key, value in updates.items():
            if isinstance(value, dict) and key in context:
                context[key] = {**context[key], **value}
            else:
                context[key] = value

        # Trim context if it gets too large
        self._trim_context(context)

        return context

    def _trim_context(self, context: Dict[str, Any]) -> None:
        """Trim context to stay within size limits"""
        # This is a simplified version - in production would need more sophisticated handling
        if len(str(context)) > self.max_context_size:
            # Remove less important information
            if "data_summary" in context:
                del context["data_summary"]
            if "data_schema" in context:
                del context["data_schema"]

    def get_context_summary(self, context: Dict[str, Any]) -> str:
        """Get a human-readable summary of the current context"""
        parts = []

        if "data_schema" in context:
            schema = context["data_schema"]
            parts.append(f"Data Schema: {schema['shape'][0]} rows, {schema['shape'][1]} columns")
            parts.append(f"Columns: {', '.join(list(schema['columns'])[:10])}{'...' if len(schema['columns']) > 10 else ''}")

        if "data_summary" in context:
            summary = context["data_summary"]
            parts.append(f"\nData Summary:")
            parts.append(f"  Total rows: {summary['total_rows']}")
            parts.append(f"  Total columns: {summary['total_columns']}")
            parts.append(f"  Missing values: {summary['missing_values']}")
            parts.append(f"  Numeric columns: {len(summary['numeric_columns'])}")
            parts.append(f"  Categorical columns: {len(summary['categorical_columns'])}")

        if "insights" in context:
            parts.append(f"\nCurrent insights: {len(context['insights'])} total")

        if "charts_generated" in context:
            parts.append(f"\nCharts generated: {context['charts_generated']}")

        return "\n".join(parts)

    def prepare_context_for_llm(self, data: Dict[str, Any]) -> str:
        """Prepare context for LLM without stuffing full DataFrames"""
        context_parts = []

        # Add data schema and summary instead of full data
        if "df" in data:
            df = data["df"]
            schema = self._get_dataframe_schema(df)
            summary = self._get_dataframe_summary(df)

            context_parts.append("# Data Schema")
            context_parts.append(json.dumps(schema, indent=2))

            context_parts.append("\n# Statistical Summary")
            context_parts.append(json.dumps(summary, indent=2))

        # Add other context
        if "analysis_goal" in data:
            context_parts.append(f"\n# Analysis Goal\n{data['analysis_goal']}")

        if "last_action" in data:
            context_parts.append(f"\n# Last Action\n{data['last_action']}")

        # Combine and trim
        full_context = "\n".join(context_parts)
        if len(full_context) > self.max_context_size:
            # Truncate and add warning
            truncated = full_context[:self.max_context_size] + "\n...[context truncated]"
            return truncated

        return full_context