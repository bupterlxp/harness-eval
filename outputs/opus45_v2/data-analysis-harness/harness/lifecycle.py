"""
Lifecycle Hooks (L) - Boundary checks and validation at execution boundaries.

Provides hooks for pre-execution, post-execution, and domain-specific validations.
"""

from typing import Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum
import pandas as pd
import numpy as np

from harness.state import StateStore


class HookPhase(Enum):
    """Phases where hooks can be triggered."""
    PRE_LOAD = "pre_load"
    POST_LOAD = "post_load"
    PRE_ANALYSIS = "pre_analysis"
    POST_ANALYSIS = "post_analysis"
    PRE_CHART = "pre_chart"
    POST_CHART = "post_chart"
    PRE_STEP = "pre_step"
    POST_STEP = "post_step"


@dataclass
class HookResult:
    """Result of a hook execution."""
    passed: bool
    message: str
    warnings: list[str]
    data: Optional[dict] = None


@dataclass
class HookDefinition:
    """Definition of a lifecycle hook."""
    name: str
    phase: HookPhase
    func: Callable[..., HookResult]
    description: str
    required: bool = True


class LifecycleHooks:
    """
    Manages lifecycle hooks for boundary checks and validation.

    Hook phases:
    - PRE_LOAD: Before loading data
    - POST_LOAD: After loading data (validate schema, check for empty)
    - PRE_ANALYSIS: Before running analysis
    - POST_ANALYSIS: After analysis (validate results)
    - PRE_CHART: Before generating chart
    - POST_CHART: After generating chart
    - PRE_STEP / POST_STEP: General step boundaries
    """

    def __init__(self, state_store: StateStore):
        self.state = state_store
        self._hooks: dict[HookPhase, list[HookDefinition]] = {phase: [] for phase in HookPhase}
        self._register_builtin_hooks()

    def register(self, hook: HookDefinition) -> None:
        """Register a hook."""
        self._hooks[hook.phase].append(hook)

    def unregister(self, name: str, phase: HookPhase) -> None:
        """Unregister a hook by name."""
        self._hooks[phase] = [h for h in self._hooks[phase] if h.name != name]

    def run_hooks(self, phase: HookPhase, **context) -> list[HookResult]:
        """Run all hooks for a phase."""
        results = []
        for hook in self._hooks[phase]:
            try:
                result = hook.func(self.state, **context)
                results.append(result)
            except Exception as e:
                results.append(HookResult(
                    passed=not hook.required,
                    message=f"Hook {hook.name} failed: {str(e)}",
                    warnings=[str(e)]
                ))
        return results

    def check_all_passed(self, results: list[HookResult]) -> bool:
        """Check if all hook results passed."""
        return all(r.passed for r in results)

    def get_warnings(self, results: list[HookResult]) -> list[str]:
        """Extract all warnings from hook results."""
        warnings = []
        for r in results:
            warnings.extend(r.warnings)
        return warnings

    def _register_builtin_hooks(self) -> None:
        """Register built-in validation hooks."""

        self.register(HookDefinition(
            name="check_data_not_empty",
            phase=HookPhase.POST_LOAD,
            func=self._check_data_not_empty,
            description="Verify loaded data is not empty",
            required=True
        ))

        self.register(HookDefinition(
            name="check_schema_valid",
            phase=HookPhase.POST_LOAD,
            func=self._check_schema_valid,
            description="Validate data schema",
            required=True
        ))

        self.register(HookDefinition(
            name="detect_data_quality_issues",
            phase=HookPhase.POST_LOAD,
            func=self._detect_data_quality_issues,
            description="Detect potential data quality issues",
            required=False
        ))

        self.register(HookDefinition(
            name="check_output_reasonable",
            phase=HookPhase.POST_ANALYSIS,
            func=self._check_output_reasonable,
            description="Verify analysis output is reasonable",
            required=True
        ))

        self.register(HookDefinition(
            name="validate_numeric_results",
            phase=HookPhase.POST_ANALYSIS,
            func=self._validate_numeric_results,
            description="Validate numeric results are not NaN/Inf",
            required=True
        ))

        self.register(HookDefinition(
            name="check_chart_data_sufficient",
            phase=HookPhase.PRE_CHART,
            func=self._check_chart_data_sufficient,
            description="Verify sufficient data for chart generation",
            required=True
        ))

        self.register(HookDefinition(
            name="check_chart_file_created",
            phase=HookPhase.POST_CHART,
            func=self._check_chart_file_created,
            description="Verify chart file was created",
            required=True
        ))

        self.register(HookDefinition(
            name="check_max_steps_not_exceeded",
            phase=HookPhase.PRE_STEP,
            func=self._check_max_steps_not_exceeded,
            description="Check that max steps limit is not exceeded",
            required=True
        ))

    def _check_data_not_empty(self, state: StateStore, dataframe_name: str = None, **kwargs) -> HookResult:
        """Check that loaded data is not empty."""
        if dataframe_name:
            df = state.get_dataframe(dataframe_name)
            if df is None:
                return HookResult(False, f"DataFrame '{dataframe_name}' not found", [])
            if df.empty:
                return HookResult(False, f"DataFrame '{dataframe_name}' is empty", [])
            return HookResult(True, f"DataFrame '{dataframe_name}' has {len(df)} rows", [])

        all_dfs = state.get_all_dataframes()
        if not all_dfs:
            return HookResult(False, "No data loaded", [])

        empty_dfs = [name for name, df in all_dfs.items() if df.empty]
        if empty_dfs:
            return HookResult(False, f"Empty DataFrames: {empty_dfs}", [])

        return HookResult(True, f"All {len(all_dfs)} DataFrames have data", [])

    def _check_schema_valid(self, state: StateStore, dataframe_name: str = None, **kwargs) -> HookResult:
        """Validate DataFrame schema."""
        warnings = []

        if dataframe_name:
            df = state.get_dataframe(dataframe_name)
            if df is None:
                return HookResult(False, f"DataFrame '{dataframe_name}' not found", [])
            dfs = {dataframe_name: df}
        else:
            dfs = state.get_all_dataframes()

        for name, df in dfs.items():
            all_null_cols = [col for col in df.columns if df[col].isnull().all()]
            if all_null_cols:
                warnings.append(f"{name}: columns with all null values: {all_null_cols}")

            object_cols = df.select_dtypes(include=['object']).columns.tolist()
            for col in object_cols:
                try:
                    pd.to_numeric(df[col], errors='raise')
                    warnings.append(f"{name}.{col}: appears numeric but stored as object")
                except (ValueError, TypeError):
                    pass

        return HookResult(True, "Schema validation complete", warnings)

    def _detect_data_quality_issues(self, state: StateStore, dataframe_name: str = None, **kwargs) -> HookResult:
        """Detect potential data quality issues."""
        warnings = []

        if dataframe_name:
            dfs = {dataframe_name: state.get_dataframe(dataframe_name)}
        else:
            dfs = state.get_all_dataframes()

        for name, df in dfs.items():
            if df is None:
                continue

            null_pcts = (df.isnull().sum() / len(df) * 100).to_dict()
            high_null_cols = {col: f"{pct:.1f}%" for col, pct in null_pcts.items() if pct > 20}
            if high_null_cols:
                warnings.append(f"{name}: high null percentage columns: {high_null_cols}")

            duplicates = df.duplicated().sum()
            if duplicates > 0:
                dup_pct = duplicates / len(df) * 100
                warnings.append(f"{name}: {duplicates} duplicate rows ({dup_pct:.1f}%)")

            for col in df.select_dtypes(include=[np.number]).columns:
                q1, q3 = df[col].quantile([0.25, 0.75])
                iqr = q3 - q1
                outliers = ((df[col] < q1 - 3 * iqr) | (df[col] > q3 + 3 * iqr)).sum()
                if outliers > 0:
                    pct = outliers / len(df) * 100
                    if pct > 5:
                        warnings.append(f"{name}.{col}: {outliers} potential outliers ({pct:.1f}%)")

        return HookResult(True, "Data quality check complete", warnings)

    def _check_output_reasonable(self, state: StateStore, result: Any = None, **kwargs) -> HookResult:
        """Check that analysis output is reasonable."""
        warnings = []

        if result is None:
            return HookResult(True, "No result to validate", [])

        if isinstance(result, pd.DataFrame):
            if result.empty:
                return HookResult(False, "Result DataFrame is empty", [])

            if len(result) > 1000000:
                warnings.append(f"Large result: {len(result)} rows")

            null_pct = result.isnull().sum().sum() / result.size * 100
            if null_pct > 50:
                warnings.append(f"Result has {null_pct:.1f}% null values")

        elif isinstance(result, (int, float)):
            if np.isnan(result) or np.isinf(result):
                return HookResult(False, f"Result is {result}", [])

        elif isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
                    warnings.append(f"Result['{key}'] is {value}")

        return HookResult(True, "Output validation passed", warnings)

    def _validate_numeric_results(self, state: StateStore, result: Any = None, **kwargs) -> HookResult:
        """Validate that numeric results don't contain NaN or Inf."""
        if result is None:
            return HookResult(True, "No numeric result to validate", [])

        def check_value(val, path=""):
            issues = []
            if isinstance(val, float):
                if np.isnan(val):
                    issues.append(f"{path}: NaN")
                elif np.isinf(val):
                    issues.append(f"{path}: Inf")
            elif isinstance(val, dict):
                for k, v in val.items():
                    issues.extend(check_value(v, f"{path}.{k}" if path else k))
            elif isinstance(val, list):
                for i, v in enumerate(val[:100]):
                    issues.extend(check_value(v, f"{path}[{i}]"))
            elif isinstance(val, pd.DataFrame):
                numeric_cols = val.select_dtypes(include=[np.number]).columns
                for col in numeric_cols:
                    if val[col].isnull().any():
                        issues.append(f"{path}.{col}: contains NaN")
                    if np.isinf(val[col]).any():
                        issues.append(f"{path}.{col}: contains Inf")
            return issues

        issues = check_value(result)
        if issues:
            return HookResult(False, f"Numeric validation failed: {issues[:5]}", issues)

        return HookResult(True, "Numeric validation passed", [])

    def _check_chart_data_sufficient(self, state: StateStore, dataframe_name: str = None,
                                      min_rows: int = 1, **kwargs) -> HookResult:
        """Check that there's sufficient data for chart generation."""
        if not dataframe_name:
            return HookResult(True, "No specific DataFrame specified", [])

        df = state.get_dataframe(dataframe_name)
        if df is None:
            return HookResult(False, f"DataFrame '{dataframe_name}' not found", [])

        if len(df) < min_rows:
            return HookResult(False, f"Insufficient data: {len(df)} rows (need at least {min_rows})", [])

        warnings = []
        if len(df) > 10000:
            warnings.append(f"Large dataset ({len(df)} rows) - chart may be slow/cluttered")

        return HookResult(True, f"Sufficient data for chart ({len(df)} rows)", warnings)

    def _check_chart_file_created(self, state: StateStore, chart_path: str = None, **kwargs) -> HookResult:
        """Verify chart file was created."""
        if not chart_path:
            return HookResult(True, "No chart path to verify", [])

        from pathlib import Path
        path = Path(chart_path)

        if not path.exists():
            return HookResult(False, f"Chart file not created: {chart_path}", [])

        if path.stat().st_size == 0:
            return HookResult(False, f"Chart file is empty: {chart_path}", [])

        return HookResult(True, f"Chart file created: {chart_path}", [])

    def _check_max_steps_not_exceeded(self, state: StateStore, max_steps: int = 20, **kwargs) -> HookResult:
        """Check that max steps limit is not exceeded."""
        current_step = state.current_step

        if current_step >= max_steps:
            return HookResult(False, f"Max steps exceeded: {current_step} >= {max_steps}", [])

        warnings = []
        if current_step >= max_steps - 3:
            warnings.append(f"Approaching max steps limit: {current_step}/{max_steps}")

        return HookResult(True, f"Step {current_step}/{max_steps}", warnings)


def validate_dataframe_transform(before: pd.DataFrame, after: pd.DataFrame,
                                  operation: str = "transform") -> HookResult:
    """Validate a DataFrame transformation."""
    warnings = []

    if after.empty and not before.empty:
        return HookResult(False, f"{operation} resulted in empty DataFrame", [])

    if len(after) > len(before) * 10:
        warnings.append(f"{operation}: row count increased 10x ({len(before)} -> {len(after)})")

    if len(after) < len(before) * 0.01:
        warnings.append(f"{operation}: lost 99%+ of rows ({len(before)} -> {len(after)})")

    new_cols = set(after.columns) - set(before.columns)
    removed_cols = set(before.columns) - set(after.columns)
    if removed_cols:
        warnings.append(f"{operation}: removed columns: {removed_cols}")

    return HookResult(True, f"{operation} validation passed", warnings)


def validate_calculation(result: float, expected_range: tuple[float, float] = None,
                         name: str = "calculation") -> HookResult:
    """Validate a calculation result."""
    if np.isnan(result):
        return HookResult(False, f"{name} resulted in NaN", [])

    if np.isinf(result):
        return HookResult(False, f"{name} resulted in Inf", [])

    warnings = []
    if expected_range:
        low, high = expected_range
        if result < low or result > high:
            warnings.append(f"{name} = {result} outside expected range [{low}, {high}]")

    return HookResult(True, f"{name} = {result}", warnings)
