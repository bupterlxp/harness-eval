"""
C - Context Manager

Manages three types of context:
1. DataContext: Schema + statistical summary (NOT full DataFrame)
2. AnalysisHistory: Completed steps and conclusions
3. IntentContext: User goals and constraints

Key principle: Never put full DataFrame into LLM prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from harness.schemas import (
    AnalysisState,
    AnalysisStep,
    ChartRecord,
    ColumnProfile,
    DataProfile,
    Insight,
)


def create_data_profile(df: pd.DataFrame) -> DataProfile:
    """
    Create a DataProfile from a DataFrame.

    This extracts schema and statistics WITHOUT storing the full data.
    """
    columns = []

    for col in df.columns:
        series = df[col]
        dtype_str = str(series.dtype)
        non_null = series.notna().sum()
        null_count = series.isna().sum()
        null_pct = (null_count / len(df)) * 100 if len(df) > 0 else 0.0

        try:
            unique_count = series.nunique()
        except Exception:
            unique_count = 0

        sample_values = series.dropna().head(3).tolist()

        col_profile = ColumnProfile(
            name=col,
            dtype=dtype_str,
            non_null_count=int(non_null),
            null_count=int(null_count),
            null_percentage=null_pct,
            unique_count=int(unique_count),
            sample_values=sample_values,
        )

        if pd.api.types.is_numeric_dtype(series):
            col_profile.min_value = series.min() if non_null > 0 else None
            col_profile.max_value = series.max() if non_null > 0 else None
            col_profile.mean_value = float(series.mean()) if non_null > 0 else None
            col_profile.std_value = float(series.std()) if non_null > 0 else None

        columns.append(col_profile)

    memory_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)

    return DataProfile(
        row_count=len(df),
        column_count=len(df.columns),
        columns=columns,
        memory_usage_mb=memory_mb,
    )


@dataclass
class DataContext:
    """
    Context about the current DataFrame state.

    Stores schema and statistics, NOT the actual data.
    """
    profile: DataProfile | None = None
    cleaning_applied: list[str] = field(default_factory=list)
    derived_columns: list[str] = field(default_factory=list)
    filters_applied: list[str] = field(default_factory=list)

    def update_from_dataframe(self, df: pd.DataFrame) -> None:
        """Update context from a DataFrame."""
        self.profile = create_data_profile(df)

    def to_prompt_context(self) -> str:
        """Generate context string for LLM prompt."""
        if not self.profile:
            return "No data loaded yet."

        lines = [self.profile.to_summary_string()]

        if self.cleaning_applied:
            lines.append(f"\nCleaning applied: {', '.join(self.cleaning_applied)}")
        if self.derived_columns:
            lines.append(f"Derived columns: {', '.join(self.derived_columns)}")
        if self.filters_applied:
            lines.append(f"Filters: {', '.join(self.filters_applied)}")

        return "\n".join(lines)


@dataclass
class AnalysisHistory:
    """
    History of completed analysis steps and their conclusions.
    """
    steps: list[AnalysisStep] = field(default_factory=list)
    charts: list[ChartRecord] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    key_findings: dict[AnalysisState, list[str]] = field(default_factory=dict)

    def add_step(self, step: AnalysisStep) -> None:
        """Add a completed step."""
        self.steps.append(step)

    def add_chart(self, chart: ChartRecord) -> None:
        """Add a generated chart."""
        self.charts.append(chart)

    def add_insight(self, insight: Insight) -> None:
        """Add a discovered insight."""
        self.insights.append(insight)

    def add_finding(self, state: AnalysisState, finding: str) -> None:
        """Add a key finding for a state."""
        if state not in self.key_findings:
            self.key_findings[state] = []
        self.key_findings[state].append(finding)

    def get_completed_states(self) -> list[AnalysisState]:
        """Get list of states that have been completed."""
        return list({step.state for step in self.steps if step.success})

    def get_findings_summary(self) -> str:
        """Get summary of findings for LLM context."""
        lines = ["## Analysis Findings"]
        for state, findings in self.key_findings.items():
            if findings:
                lines.append(f"\n### {state.value}")
                for f in findings:
                    lines.append(f"  - {f}")
        return "\n".join(lines)

    def to_prompt_context(self, max_items: int = 10) -> str:
        """Generate context string for LLM prompt."""
        lines = ["## Analysis History"]

        recent_steps = self.steps[-max_items:]
        for step in recent_steps:
            status = "✓" if step.success else "✗"
            lines.append(f"  {status} Step {step.step_number}: {step.description}")
            if step.findings:
                for finding in step.findings[:3]:
                    lines.append(f"      → {finding}")

        if self.insights:
            lines.append("\n## Key Insights")
            for insight in self.insights[-5:]:
                lines.append(f"  - [{insight.category}] {insight.title}")

        return "\n".join(lines)


@dataclass
class IntentContext:
    """
    Context about user's analysis goals and constraints.
    """
    analysis_goal: str = ""
    data_file: str = ""
    required_analyses: list[str] = field(default_factory=list)
    output_format: str = "script + charts + report"
    constraints: list[str] = field(default_factory=list)
    custom_formulas: dict[str, str] = field(default_factory=dict)

    def to_prompt_context(self) -> str:
        """Generate context string for LLM prompt."""
        lines = ["## Analysis Intent"]
        lines.append(f"Goal: {self.analysis_goal}")
        lines.append(f"Data: {self.data_file}")

        if self.required_analyses:
            lines.append(f"Required: {', '.join(self.required_analyses)}")
        if self.custom_formulas:
            lines.append("Formulas:")
            for name, formula in self.custom_formulas.items():
                lines.append(f"  {name} = {formula}")
        if self.constraints:
            lines.append(f"Constraints: {', '.join(self.constraints)}")

        return "\n".join(lines)


class ContextManager:
    """
    Unified context manager for the analysis harness.

    Manages DataContext, AnalysisHistory, and IntentContext.
    Provides compressed context for LLM prompts.
    """

    def __init__(self):
        self.data_context = DataContext()
        self.analysis_history = AnalysisHistory()
        self.intent_context = IntentContext()
        self._max_context_chars = 4000

    def update_data_context(self, df: pd.DataFrame) -> None:
        """Update data context from a DataFrame."""
        self.data_context.update_from_dataframe(df)

    def record_cleaning(self, description: str) -> None:
        """Record a cleaning operation."""
        self.data_context.cleaning_applied.append(description)

    def record_derived_column(self, column: str) -> None:
        """Record a derived column."""
        self.data_context.derived_columns.append(column)

    def record_filter(self, description: str) -> None:
        """Record a filter operation."""
        self.data_context.filters_applied.append(description)

    def add_step(self, step: AnalysisStep) -> None:
        """Add a completed step to history."""
        self.analysis_history.add_step(step)

    def add_chart(self, chart: ChartRecord) -> None:
        """Add a chart to history."""
        self.analysis_history.add_chart(chart)

    def add_insight(self, insight: Insight) -> None:
        """Add an insight to history."""
        self.analysis_history.add_insight(insight)

    def add_finding(self, state: AnalysisState, finding: str) -> None:
        """Add a finding for a state."""
        self.analysis_history.add_finding(state, finding)

    def set_intent(
        self,
        goal: str,
        data_file: str,
        required_analyses: list[str] | None = None,
        output_format: str = "script + charts + report",
        constraints: list[str] | None = None,
        formulas: dict[str, str] | None = None,
    ) -> None:
        """Set the analysis intent."""
        self.intent_context = IntentContext(
            analysis_goal=goal,
            data_file=data_file,
            required_analyses=required_analyses or [],
            output_format=output_format,
            constraints=constraints or [],
            custom_formulas=formulas or {},
        )

    def get_full_context(self) -> str:
        """
        Get full context for LLM prompt.

        Combines all three context types with compression.
        """
        parts = [
            self.intent_context.to_prompt_context(),
            self.data_context.to_prompt_context(),
            self.analysis_history.to_prompt_context(),
        ]
        full_context = "\n\n".join(parts)

        if len(full_context) > self._max_context_chars:
            full_context = self._compress_context(full_context)

        return full_context

    def _compress_context(self, context: str) -> str:
        """Compress context to fit within limit."""
        lines = context.split("\n")
        if len(lines) <= 50:
            return context

        intent_lines = []
        data_lines = []
        history_lines = []
        current_section = intent_lines

        for line in lines:
            if "## Analysis Intent" in line:
                current_section = intent_lines
            elif "## Data" in line or "DataFrame" in line:
                current_section = data_lines
            elif "## Analysis History" in line or "## Key" in line:
                current_section = history_lines
            current_section.append(line)

        compressed = []
        compressed.extend(intent_lines[:15])
        compressed.extend(data_lines[:20])
        compressed.extend(history_lines[-15:])

        return "\n".join(compressed)

    def get_data_summary(self) -> str:
        """Get just the data context."""
        return self.data_context.to_prompt_context()

    def get_progress_summary(self) -> str:
        """Get progress summary for user display."""
        completed = self.analysis_history.get_completed_states()
        all_states = AnalysisState.get_order()

        lines = ["Analysis Progress:"]
        for state in all_states:
            if state in completed:
                lines.append(f"  ✓ {state.value}")
            elif state == AnalysisState.COMPLETE:
                lines.append(f"  ○ {state.value}")
            else:
                lines.append(f"  ○ {state.value}")

        lines.append(f"\nCharts generated: {len(self.analysis_history.charts)}")
        lines.append(f"Insights found: {len(self.analysis_history.insights)}")

        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all contexts."""
        self.data_context = DataContext()
        self.analysis_history = AnalysisHistory()
        self.intent_context = IntentContext()
