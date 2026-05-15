"""
L - Lifecycle Hooks

Pre/post hooks for analysis execution:
- pre_execute: Check input DataFrame non-empty
- post_execute: Validate output reasonableness
- on_error: Save state and provide context
- pre_plot: Check data volume before visualization
- post_report: Verify numeric consistency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

import pandas as pd

from harness.schemas import AnalysisState, ValidationResult


class HookType(str, Enum):
    """Types of lifecycle hooks."""
    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"
    ON_ERROR = "on_error"
    PRE_PLOT = "pre_plot"
    POST_PLOT = "post_plot"
    PRE_REPORT = "pre_report"
    POST_REPORT = "post_report"


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""
    state: AnalysisState
    step_number: int
    variables: dict[str, Any]
    error: Exception | None = None
    extra: dict[str, Any] = field(default_factory=dict)


HookFunction = Callable[[HookContext], ValidationResult | None]


class LifecycleHooks:
    """
    Manages lifecycle hooks for the analysis harness.

    Hooks can be registered for different lifecycle events
    and are executed in order of registration.
    """

    def __init__(self):
        self._hooks: dict[HookType, list[tuple[str, HookFunction]]] = {
            hook_type: [] for hook_type in HookType
        }
        self._register_default_hooks()

    def _register_default_hooks(self) -> None:
        """Register default validation hooks."""
        self.register(HookType.PRE_EXECUTE, "check_dataframe_not_empty",
                      self._check_dataframe_not_empty)
        self.register(HookType.POST_EXECUTE, "validate_output_shape",
                      self._validate_output_shape)
        self.register(HookType.PRE_PLOT, "check_data_volume",
                      self._check_data_volume)
        self.register(HookType.POST_REPORT, "verify_numeric_consistency",
                      self._verify_numeric_consistency)

    def register(self, hook_type: HookType, name: str, func: HookFunction) -> None:
        """Register a hook function."""
        self._hooks[hook_type].append((name, func))

    def unregister(self, hook_type: HookType, name: str) -> bool:
        """Unregister a hook by name."""
        hooks = self._hooks[hook_type]
        for i, (hook_name, _) in enumerate(hooks):
            if hook_name == name:
                hooks.pop(i)
                return True
        return False

    def execute(self, hook_type: HookType, context: HookContext) -> list[ValidationResult]:
        """Execute all hooks of a type and return results."""
        results = []
        for name, func in self._hooks[hook_type]:
            try:
                result = func(context)
                if result:
                    results.append(result)
            except Exception as e:
                results.append(ValidationResult(
                    check_name=name,
                    passed=False,
                    expected="No exception",
                    actual=str(e),
                    message=f"Hook {name} raised exception: {e}",
                    severity="error",
                    step_number=context.step_number,
                ))
        return results

    def execute_pre_execute(self, state: AnalysisState, step_number: int,
                            variables: dict[str, Any]) -> list[ValidationResult]:
        """Execute pre-execute hooks."""
        context = HookContext(state=state, step_number=step_number, variables=variables)
        return self.execute(HookType.PRE_EXECUTE, context)

    def execute_post_execute(self, state: AnalysisState, step_number: int,
                             variables: dict[str, Any],
                             output_vars: list[str]) -> list[ValidationResult]:
        """Execute post-execute hooks."""
        context = HookContext(
            state=state,
            step_number=step_number,
            variables=variables,
            extra={"output_vars": output_vars}
        )
        return self.execute(HookType.POST_EXECUTE, context)

    def execute_on_error(self, state: AnalysisState, step_number: int,
                         variables: dict[str, Any],
                         error: Exception) -> list[ValidationResult]:
        """Execute on-error hooks."""
        context = HookContext(
            state=state,
            step_number=step_number,
            variables=variables,
            error=error
        )
        return self.execute(HookType.ON_ERROR, context)

    def execute_pre_plot(self, state: AnalysisState, step_number: int,
                         df: pd.DataFrame, chart_type: str) -> list[ValidationResult]:
        """Execute pre-plot hooks."""
        context = HookContext(
            state=state,
            step_number=step_number,
            variables={"df": df},
            extra={"chart_type": chart_type}
        )
        return self.execute(HookType.PRE_PLOT, context)

    def execute_post_report(self, state: AnalysisState, step_number: int,
                            variables: dict[str, Any],
                            report_data: dict[str, Any]) -> list[ValidationResult]:
        """Execute post-report hooks."""
        context = HookContext(
            state=state,
            step_number=step_number,
            variables=variables,
            extra={"report_data": report_data}
        )
        return self.execute(HookType.POST_REPORT, context)

    def _check_dataframe_not_empty(self, context: HookContext) -> ValidationResult | None:
        """Check that input DataFrames are not empty."""
        for name, value in context.variables.items():
            if isinstance(value, pd.DataFrame):
                if len(value) == 0:
                    return ValidationResult(
                        check_name="dataframe_not_empty",
                        passed=False,
                        expected=">0 rows",
                        actual="0 rows",
                        message=f"DataFrame '{name}' is empty",
                        severity="error",
                        step_number=context.step_number,
                    )
        return None

    def _validate_output_shape(self, context: HookContext) -> ValidationResult | None:
        """Validate that output variables exist and have reasonable shape."""
        output_vars = context.extra.get("output_vars", [])

        for var_name in output_vars:
            if var_name not in context.variables:
                return ValidationResult(
                    check_name="output_exists",
                    passed=False,
                    expected=f"Variable '{var_name}' exists",
                    actual="Variable not found",
                    message=f"Expected output variable '{var_name}' not produced",
                    severity="error",
                    step_number=context.step_number,
                )

            value = context.variables[var_name]
            if isinstance(value, pd.DataFrame) and len(value) == 0:
                return ValidationResult(
                    check_name="output_not_empty",
                    passed=False,
                    expected=">0 rows",
                    actual="0 rows",
                    message=f"Output DataFrame '{var_name}' is empty",
                    severity="warning",
                    step_number=context.step_number,
                )

        return None

    def _check_data_volume(self, context: HookContext) -> ValidationResult | None:
        """Check data volume before plotting."""
        df = context.variables.get("df")
        if df is None or not isinstance(df, pd.DataFrame):
            return None

        chart_type = context.extra.get("chart_type", "")
        max_points = {
            "scatter": 10000,
            "line": 5000,
            "bar": 500,
            "heatmap": 10000,
        }

        limit = max_points.get(chart_type, 10000)
        data_points = len(df)

        if data_points > limit:
            return ValidationResult(
                check_name="data_volume_check",
                passed=False,
                expected=f"<={limit} data points for {chart_type}",
                actual=f"{data_points} data points",
                message=f"Too many data points ({data_points}) for {chart_type} chart. "
                        f"Consider aggregating or sampling.",
                severity="warning",
                step_number=context.step_number,
            )

        return None

    def _verify_numeric_consistency(self, context: HookContext) -> ValidationResult | None:
        """Verify numeric consistency in report data."""
        report_data = context.extra.get("report_data", {})

        if not report_data:
            return None

        issues = []
        for key, value in report_data.items():
            if isinstance(value, (int, float)):
                if pd.isna(value):
                    issues.append(f"'{key}' is NaN")
                elif isinstance(value, float) and (value == float("inf") or value == float("-inf")):
                    issues.append(f"'{key}' is infinite")

        if issues:
            return ValidationResult(
                check_name="numeric_consistency",
                passed=False,
                expected="All numeric values finite and valid",
                actual="; ".join(issues),
                message=f"Numeric issues found: {'; '.join(issues)}",
                severity="warning",
                step_number=context.step_number,
            )

        return None

    def get_registered_hooks(self) -> dict[str, list[str]]:
        """Get names of all registered hooks."""
        return {
            hook_type.value: [name for name, _ in hooks]
            for hook_type, hooks in self._hooks.items()
        }


def check_discount_validity(context: HookContext) -> ValidationResult | None:
    """Custom hook: Check discount values are in valid range."""
    df = None
    for name, value in context.variables.items():
        if isinstance(value, pd.DataFrame) and "discount" in value.columns:
            df = value
            break

    if df is None:
        return None

    invalid_discounts = df[df["discount"] > 1.0]
    if len(invalid_discounts) > 0:
        return ValidationResult(
            check_name="discount_validity",
            passed=False,
            expected="discount <= 1.0",
            actual=f"{len(invalid_discounts)} rows with discount > 1.0",
            message=f"Found {len(invalid_discounts)} rows with invalid discount values (>100%)",
            severity="warning",
            step_number=context.step_number,
        )

    return None


def check_quantity_outliers(context: HookContext) -> ValidationResult | None:
    """Custom hook: Check for quantity outliers."""
    df = None
    for name, value in context.variables.items():
        if isinstance(value, pd.DataFrame) and "quantity" in value.columns:
            df = value
            break

    if df is None:
        return None

    q99 = df["quantity"].quantile(0.99)
    outliers = df[df["quantity"] > q99 * 3]

    if len(outliers) > 0:
        return ValidationResult(
            check_name="quantity_outliers",
            passed=False,
            expected=f"quantity <= {q99 * 3:.0f}",
            actual=f"{len(outliers)} rows with extreme quantities",
            message=f"Found {len(outliers)} rows with extreme quantity values",
            severity="warning",
            step_number=context.step_number,
        )

    return None
