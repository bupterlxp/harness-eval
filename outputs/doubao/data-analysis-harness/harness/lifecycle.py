from typing import Callable, Optional, Any
from functools import wraps
from .schemas import ExecutionState, ValidationResult
from .context import AnalysisContext


def pre_execute_hook(func: Callable) -> Callable:
    """Decorator for pre-execution validation"""
    @wraps(func)
    def wrapper(state: ExecutionState, *args, **kwargs) -> tuple[Any, ValidationResult]:
        validation_result = ValidationResult(checks_performed=1)

        # Check if dataframe exists and is not empty
        if "df_name" in kwargs:
            df_name = kwargs["df_name"]
        elif args:
            df_name = args[0] if isinstance(args[0], str) else "main"
        else:
            df_name = "main"

        if df_name not in state.dataframes:
            validation_result.errors.append(f"Dataframe '{df_name}' not found in state")
            validation_result.is_valid = False
            return None, validation_result

        df = state.dataframes[df_name]
        if len(df) == 0:
            validation_result.errors.append(f"Dataframe '{df_name}' is empty")
            validation_result.is_valid = False
            return None, validation_result

        # Check for minimum rows
        if len(df) < 5:
            validation_result.warnings.append(f"Dataframe '{df_name}' has very few rows ({len(df)})")

        return func(state, *args, **kwargs)
    return wrapper


def post_execute_hook(func: Callable) -> Callable:
    """Decorator for post-execution validation"""
    @wraps(func)
    def wrapper(state: ExecutionState, *args, **kwargs) -> tuple[Any, ValidationResult]:
        result, validation_result = func(state, *args, **kwargs)

        # Validate the output
        if hasattr(result, 'shape'):
            rows, cols = result.shape
            if rows == 0:
                validation_result.errors.append("Output dataframe is empty")
                validation_result.is_valid = False
            if cols == 0:
                validation_result.errors.append("Output dataframe has no columns")
                validation_result.is_valid = False

        # Update validation result checks performed
        validation_result.checks_performed += 1

        return result, validation_result
    return wrapper


class LifecycleHooks:
    """Collection of lifecycle hooks for analysis execution"""

    def __init__(self):
        self.pre_execute_hooks: list[Callable[[ExecutionState], ValidationResult]] = []
        self.post_execute_hooks: list[Callable[[Any, ValidationResult], ValidationResult]] = []
        self.on_error_hooks: list[Callable[[Exception, str], None]] = []
        self.pre_plot_hooks: list[Callable[[pd.DataFrame, str], ValidationResult]] = []
        self.post_plot_hooks: list[Callable[[str, pd.DataFrame], None]] = []
        self.pre_report_hooks: list[Callable[[AnalysisContext], ValidationResult]] = []
        self.post_report_hooks: list[Callable[[str, AnalysisContext], None]] = []

    def add_pre_execute_hook(self, hook: Callable[[ExecutionState], ValidationResult]) -> None:
        """Add a pre-execution hook"""
        self.pre_execute_hooks.append(hook)

    def add_post_execute_hook(self, hook: Callable[[Any, ValidationResult], ValidationResult]) -> None:
        """Add a post-execution hook"""
        self.post_execute_hooks.append(hook)

    def add_on_error_hook(self, hook: Callable[[Exception, str], None]) -> None:
        """Add an error hook"""
        self.on_error_hooks.append(hook)

    def add_pre_plot_hook(self, hook: Callable[[pd.DataFrame, str], ValidationResult]) -> None:
        """Add a pre-plot hook"""
        self.pre_plot_hooks.append(hook)

    def add_post_plot_hook(self, hook: Callable[[str, pd.DataFrame], None]) -> None:
        """Add a post-plot hook"""
        self.post_plot_hooks.append(hook)

    def add_pre_report_hook(self, hook: Callable[[AnalysisContext], ValidationResult]) -> None:
        """Add a pre-report hook"""
        self.pre_report_hooks.append(hook)

    def add_post_report_hook(self, hook: Callable[[str, AnalysisContext], None]) -> None:
        """Add a post-report hook"""
        self.post_report_hooks.append(hook)

    def run_pre_execute(self, state: ExecutionState) -> ValidationResult:
        """Run all pre-execution hooks"""
        overall_result = ValidationResult(is_valid=True, checks_performed=len(self.pre_execute_hooks))

        for hook in self.pre_execute_hooks:
            try:
                result = hook(state)
                overall_result.errors.extend(result.errors)
                overall_result.warnings.extend(result.warnings)
                overall_result.is_valid = overall_result.is_valid and result.is_valid
            except Exception as e:
                overall_result.errors.append(f"Pre-execute hook failed: {str(e)}")
                overall_result.is_valid = False

        return overall_result

    def run_post_execute(self, result: Any, initial_validation: ValidationResult) -> ValidationResult:
        """Run all post-execution hooks"""
        overall_result = initial_validation

        for hook in self.post_execute_hooks:
            try:
                result = hook(result, initial_validation)
                if hasattr(result, 'errors'):
                    overall_result.errors.extend(result.errors)
                    overall_result.warnings.extend(result.warnings)
                    overall_result.is_valid = overall_result.is_valid and result.is_valid
            except Exception as e:
                overall_result.errors.append(f"Post-execute hook failed: {str(e)}")
                overall_result.is_valid = False

        return overall_result

    def run_on_error(self, error: Exception, context: str = "") -> None:
        """Run all error handling hooks"""
        for hook in self.on_error_hooks:
            try:
                hook(error, context)
            except Exception as e:
                print(f"Error hook failed: {str(e)}")

    def run_pre_plot(self, df: pd.DataFrame, plot_type: str = "unknown") -> ValidationResult:
        """Run all pre-plot hooks"""
        result = ValidationResult(is_valid=True, checks_performed=len(self.pre_plot_hooks))

        for hook in self.pre_plot_hooks:
            try:
                hook_result = hook(df, plot_type)
                result.errors.extend(hook_result.errors)
                result.warnings.extend(hook_result.warnings)
                result.is_valid = result.is_valid and hook_result.is_valid
            except Exception as e:
                result.errors.append(f"Pre-plot hook failed: {str(e)}")
                result.is_valid = False

        return result

    def run_post_plot(self, chart_path: str, df: pd.DataFrame) -> None:
        """Run all post-plot hooks"""
        for hook in self.post_plot_hooks:
            try:
                hook(chart_path, df)
            except Exception as e:
                print(f"Post-plot hook failed: {str(e)}")

    def run_pre_report(self, context: AnalysisContext) -> ValidationResult:
        """Run all pre-report hooks"""
        result = ValidationResult(is_valid=True, checks_performed=len(self.pre_report_hooks))

        for hook in self.pre_report_hooks:
            try:
                hook_result = hook(context)
                result.errors.extend(hook_result.errors)
                result.warnings.extend(hook_result.warnings)
                result.is_valid = result.is_valid and hook_result.is_valid
            except Exception as e:
                result.errors.append(f"Pre-report hook failed: {str(e)}")
                result.is_valid = False

        return result

    def run_post_report(self, report_path: str, context: AnalysisContext) -> None:
        """Run all post-report hooks"""
        for hook in self.post_report_hooks:
            try:
                hook(report_path, context)
            except Exception as e:
                print(f"Post-report hook failed: {str(e)}")


# Default hook implementations
def default_data_check(df: pd.DataFrame, context: str = "") -> ValidationResult:
    """Default data validation hook"""
    result = ValidationResult(is_valid=True)

    # Check for missing values
    missing = df.isnull().sum().sum()
    if missing > 0:
        result.warnings.append(f"Dataset contains {missing} missing values")

    # Check for negative values in numeric columns
    numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns
    for col in numeric_cols:
        if (df[col] < 0).any():
            result.warnings.append(f"Column '{col}' contains negative values")

    # Check for extreme outliers
    for col in numeric_cols:
        q1 = df[col].quantile(0.25)
        q3 = df[col].quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 3 * iqr
        upper_bound = q3 + 3 * iqr
        outliers = df[(df[col] < lower_bound) | (df[col] > upper_bound)]
        if len(outliers) > 0:
            result.warnings.append(f"Column '{col}' has {len(outliers)} extreme outliers")

    result.checks_performed = 4
    return result


# Initialize default lifecycle hooks
def get_default_lifecycle_hooks() -> LifecycleHooks:
    """Create lifecycle hooks with default validations"""
    hooks = LifecycleHooks()

    # Add default pre-execute hooks
    @hooks.add_pre_execute_hook
    def default_pre_execute(state: ExecutionState) -> ValidationResult:
        return default_data_check(state.dataframes.get("main", pd.DataFrame()))

    # Add default pre-plot hooks
    @hooks.add_pre_plot_hook
    def default_pre_plot(df: pd.DataFrame, plot_type: str) -> ValidationResult:
        result = ValidationResult(is_valid=True)

        if len(df) > 10000:
            result.warnings.append(f"Large dataset ({len(df)} rows) - plotting may be slow")

        if len(df) < 2:
            result.errors.append("Need at least 2 data points to plot")
            result.is_valid = False

        result.checks_performed = 2
        return result

    # Add default error hook
    def default_on_error(error: Exception, context: str = ""):
        print(f"Error occurred: {str(error)}")
        print(f"Context: {context}")

    hooks.add_on_error_hook(default_on_error)

    return hooks