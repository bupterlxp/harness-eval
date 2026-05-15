"""
Schemas for Data Analysis Harness

Defines core data structures for:
- DataProfile: Schema + statistical summary of a DataFrame
- AnalysisStep: A single analysis step with inputs/outputs
- ChartRecord: Metadata for generated charts
- Insight: A data-driven finding
- ValidationResult: Result of a validation check
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AnalysisState(str, Enum):
    """States in the analysis execution loop."""
    INIT = "init"
    LOAD = "load"
    QUALITY_CHECK = "quality_check"
    PREPROCESS = "preprocess"
    EXPLORE = "explore"
    TREND = "trend"
    REGION = "region"
    CATEGORY = "category"
    CHANNEL = "channel"
    VALIDATE = "validate"
    REPORT = "report"
    COMPLETE = "complete"

    @classmethod
    def get_order(cls) -> list[AnalysisState]:
        """Return states in execution order."""
        return [
            cls.INIT,
            cls.LOAD,
            cls.QUALITY_CHECK,
            cls.PREPROCESS,
            cls.EXPLORE,
            cls.TREND,
            cls.REGION,
            cls.CATEGORY,
            cls.CHANNEL,
            cls.VALIDATE,
            cls.REPORT,
            cls.COMPLETE,
        ]

    def next_state(self) -> AnalysisState | None:
        """Get the next state in sequence."""
        order = self.get_order()
        idx = order.index(self)
        if idx < len(order) - 1:
            return order[idx + 1]
        return None

    def previous_state(self) -> AnalysisState | None:
        """Get the previous state in sequence."""
        order = self.get_order()
        idx = order.index(self)
        if idx > 0:
            return order[idx - 1]
        return None


@dataclass
class ColumnProfile:
    """Profile for a single column."""
    name: str
    dtype: str
    non_null_count: int
    null_count: int
    null_percentage: float
    unique_count: int
    sample_values: list[Any] = field(default_factory=list)
    min_value: Any = None
    max_value: Any = None
    mean_value: float | None = None
    std_value: float | None = None


@dataclass
class DataProfile:
    """
    Schema + statistical summary of a DataFrame.

    This is used in context management to represent DataFrame state
    WITHOUT including the full data (which would explode context).
    """
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    memory_usage_mb: float
    created_at: datetime = field(default_factory=datetime.now)

    def to_summary_string(self) -> str:
        """Generate a compact summary string for LLM context."""
        lines = [
            f"DataFrame: {self.row_count} rows × {self.column_count} columns",
            f"Memory: {self.memory_usage_mb:.2f} MB",
            "Columns:"
        ]
        for col in self.columns:
            null_info = f" ({col.null_percentage:.1f}% null)" if col.null_count > 0 else ""
            lines.append(f"  - {col.name}: {col.dtype}{null_info}")
        return "\n".join(lines)


@dataclass
class AnalysisStep:
    """
    A single analysis step with inputs and outputs.

    Used to track the execution history and enable rollback.
    """
    state: AnalysisState
    step_number: int
    description: str
    input_vars: list[str]
    output_vars: list[str]
    validation_conditions: list[str]
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    success: bool = False
    error_message: str | None = None
    findings: list[str] = field(default_factory=list)

    def mark_complete(self, success: bool = True, error: str | None = None) -> None:
        """Mark step as complete."""
        self.completed_at = datetime.now()
        self.success = success
        self.error_message = error


@dataclass
class ChartRecord:
    """
    Metadata for a generated chart.

    The chart itself is saved to file; this tracks metadata.
    """
    chart_id: str
    chart_type: str  # line, bar, pie, heatmap, box, scatter
    title: str
    file_path: str
    step_number: int
    state: AnalysisState
    x_label: str | None = None
    y_label: str | None = None
    data_summary: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Insight:
    """
    A data-driven finding with supporting evidence.

    Insights must have quantitative support, not vague descriptions.
    """
    insight_id: str
    category: str  # trend, comparison, anomaly, recommendation
    title: str
    description: str
    supporting_data: dict[str, Any]  # Specific numbers that support this insight
    confidence: float  # 0.0 to 1.0
    step_number: int
    state: AnalysisState
    actionable: bool = False
    created_at: datetime = field(default_factory=datetime.now)

    def validate(self) -> bool:
        """Ensure insight has quantitative support."""
        return bool(self.supporting_data) and len(self.supporting_data) > 0


@dataclass
class ValidationResult:
    """
    Result of a validation check.

    Used in lifecycle hooks and data quality checks.
    """
    check_name: str
    passed: bool
    expected: Any
    actual: Any
    message: str
    severity: str = "error"  # error, warning, info
    step_number: int | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class AnomalyRecord:
    """Record of a detected data anomaly."""
    anomaly_id: str
    column: str
    row_indices: list[int]
    anomaly_type: str  # missing, outlier, invalid
    description: str
    severity: str = "warning"
    handling_strategy: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class StepRequirement:
    """Requirements for entering a specific analysis state."""
    state: AnalysisState
    required_input_vars: list[str]
    produced_output_vars: list[str]
    validation_conditions: list[str]
    description: str


STEP_REQUIREMENTS: dict[AnalysisState, StepRequirement] = {
    AnalysisState.INIT: StepRequirement(
        state=AnalysisState.INIT,
        required_input_vars=[],
        produced_output_vars=["config"],
        validation_conditions=["config is not None"],
        description="Initialize analysis configuration"
    ),
    AnalysisState.LOAD: StepRequirement(
        state=AnalysisState.LOAD,
        required_input_vars=["config"],
        produced_output_vars=["df_raw"],
        validation_conditions=["df_raw is not None", "len(df_raw) > 0"],
        description="Load raw data from CSV"
    ),
    AnalysisState.QUALITY_CHECK: StepRequirement(
        state=AnalysisState.QUALITY_CHECK,
        required_input_vars=["df_raw"],
        produced_output_vars=["quality_report", "anomalies"],
        validation_conditions=["quality_report is not None"],
        description="Check data quality and detect anomalies"
    ),
    AnalysisState.PREPROCESS: StepRequirement(
        state=AnalysisState.PREPROCESS,
        required_input_vars=["df_raw", "anomalies"],
        produced_output_vars=["df_clean", "cleaning_log"],
        validation_conditions=["df_clean is not None", "len(df_clean) > 0"],
        description="Clean data and compute derived columns"
    ),
    AnalysisState.EXPLORE: StepRequirement(
        state=AnalysisState.EXPLORE,
        required_input_vars=["df_clean"],
        produced_output_vars=["exploration_stats"],
        validation_conditions=["exploration_stats is not None"],
        description="Compute basic statistics and distributions"
    ),
    AnalysisState.TREND: StepRequirement(
        state=AnalysisState.TREND,
        required_input_vars=["df_clean"],
        produced_output_vars=["trend_analysis", "trend_charts"],
        validation_conditions=["trend_analysis is not None"],
        description="Analyze sales trends over time"
    ),
    AnalysisState.REGION: StepRequirement(
        state=AnalysisState.REGION,
        required_input_vars=["df_clean"],
        produced_output_vars=["region_analysis", "region_charts"],
        validation_conditions=["region_analysis is not None"],
        description="Compare sales across regions"
    ),
    AnalysisState.CATEGORY: StepRequirement(
        state=AnalysisState.CATEGORY,
        required_input_vars=["df_clean"],
        produced_output_vars=["category_analysis", "category_charts"],
        validation_conditions=["category_analysis is not None"],
        description="Analyze sales by product category"
    ),
    AnalysisState.CHANNEL: StepRequirement(
        state=AnalysisState.CHANNEL,
        required_input_vars=["df_clean"],
        produced_output_vars=["channel_analysis", "channel_charts"],
        validation_conditions=["channel_analysis is not None"],
        description="Compare online vs offline channels"
    ),
    AnalysisState.VALIDATE: StepRequirement(
        state=AnalysisState.VALIDATE,
        required_input_vars=["df_clean", "trend_analysis", "region_analysis",
                            "category_analysis", "channel_analysis"],
        produced_output_vars=["validation_results"],
        validation_conditions=["all(r.passed for r in validation_results)"],
        description="Validate all calculations and findings"
    ),
    AnalysisState.REPORT: StepRequirement(
        state=AnalysisState.REPORT,
        required_input_vars=["validation_results", "trend_analysis",
                            "region_analysis", "category_analysis", "channel_analysis"],
        produced_output_vars=["final_report", "insights"],
        validation_conditions=["len(insights) >= 3"],
        description="Generate final report with insights and recommendations"
    ),
    AnalysisState.COMPLETE: StepRequirement(
        state=AnalysisState.COMPLETE,
        required_input_vars=["final_report"],
        produced_output_vars=[],
        validation_conditions=[],
        description="Analysis complete"
    ),
}
