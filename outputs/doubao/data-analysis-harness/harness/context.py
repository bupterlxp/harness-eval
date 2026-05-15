import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from .schemas import DataProfile


class DataContext:
    """Manages data context with schema and statistics"""

    def __init__(self, df: Optional[pd.DataFrame] = None):
        self.current_df: Optional[pd.DataFrame] = df
        self.data_profile: Optional[DataProfile] = None
        if df is not None:
            self.update_profile(df)

    def update_profile(self, df: pd.DataFrame) -> None:
        """Update data profile from DataFrame"""
        self.current_df = df
        shape = df.shape
        columns = list(df.columns)
        dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
        missing_values = df.isnull().sum().to_dict()
        missing_rate = {col: (missing_values[col] / len(df)) * 100 for col in missing_values}

        # Calculate summary stats for numeric columns
        numeric_cols = df.select_dtypes(include=['int64', 'float64']).columns
        summary_stats: Dict[str, Dict[str, float]] = {}
        if len(numeric_cols) > 0:
            stats = df[numeric_cols].describe().to_dict()
            for col, stat in stats.items():
                summary_stats[col] = {
                    "count": stat["count"],
                    "mean": stat["mean"],
                    "std": stat["std"],
                    "min": stat["min"],
                    "25%": stat["25%"],
                    "50%": stat["50%"],
                    "75%": stat["75%"],
                    "max": stat["max"]
                }

        self.data_profile = DataProfile(
            shape=shape,
            columns=columns,
            dtypes=dtypes,
            missing_values=missing_values,
            missing_rate=missing_rate,
            summary_stats=summary_stats
        )

    def get_summary_string(self) -> str:
        """Get human-readable summary of data context"""
        if not self.data_profile:
            return "No data loaded"

        summary = [
            f"Data shape: {self.data_profile.shape[0]} rows, {self.data_profile.shape[1]} columns",
            f"Columns: {', '.join(self.data_profile.columns)}"
        ]

        if self.data_profile.missing_values:
            summary.append("\nMissing values:")
            for col, count in self.data_profile.missing_values.items():
                if count > 0:
                    summary.append(f"  {col}: {count} ({self.data_profile.missing_rate[col]:.2f}%)")

        if self.data_profile.summary_stats:
            summary.append("\nNumeric columns summary:")
            for col, stats in self.data_profile.summary_stats.items():
                summary.append(f"  {col}: mean={stats['mean']:.2f}, min={stats['min']:.2f}, max={stats['max']:.2f}")

        return "\n".join(summary)

    def get_schema_string(self) -> str:
        """Get human-readable schema description"""
        if not self.data_profile:
            return "No data loaded"

        schema = [
            f"Schema for {len(self.data_profile.columns)} columns:",
        ]

        for col, dtype in self.data_profile.dtypes.items():
            summary = f"  {col}: {dtype}"
            if col in self.data_profile.missing_values:
                summary += f" (missing: {self.data_profile.missing_values[col]}/{len(self.current_df)} = {self.data_profile.missing_rate[col]:.2f}%)"
            schema.append(summary)

        return "\n".join(schema)


class AnalysisHistory:
    """Tracks analysis steps and results"""

    def __init__(self):
        self.steps: List[Dict[str, Any]] = []
        self.current_step = 0

    def add_step(self, name: str, description: str, input_shape: Tuple[int, int],
                 output_shape: Tuple[int, int], code_snippet: Optional[str] = None,
                 validation_result: Optional[Dict[str, Any]] = None,
                 chart_path: Optional[str] = None) -> None:
        """Add a step to history"""
        self.steps.append({
            "step_number": len(self.steps) + 1,
            "name": name,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "input_shape": input_shape,
            "output_shape": output_shape,
            "code_snippet": code_snippet,
            "validation_result": validation_result,
            "chart_path": chart_path
        })
        self.current_step = len(self.steps)

    def get_step(self, step_number: int) -> Optional[Dict[str, Any]]:
        """Get a specific step by number"""
        if 1 <= step_number <= len(self.steps):
            return self.steps[step_number - 1]
        return None

    def list_steps(self) -> List[Dict[str, Any]]:
        """List all steps"""
        return self.steps

    def get_history_string(self) -> str:
        """Get human-readable history"""
        if not self.steps:
            return "No analysis steps completed"

        history = ["Analysis history:"]
        for step in self.steps:
            history.append(f"\nStep {step['step_number']}: {step['name']}")
            history.append(f"  Description: {step['description']}")
            history.append(f"  Timestamp: {step['timestamp']}")
            history.append(f"  Input: {step['input_shape']}, Output: {step['output_shape']}")
            if step['chart_path']:
                history.append(f"  Chart: {step['chart_path']}")

        return "\n".join(history)


class IntentContext:
    """Tracks user intent and analysis requirements"""

    def __init__(self, analysis_goal: str, data_file: str, requirements: List[str]):
        self.analysis_goal = analysis_goal
        self.data_file = data_file
        self.requirements = requirements
        self.created_at = datetime.now()
        self.completed_modules: List[str] = []
        self.current_focus: Optional[str] = None

    def update_progress(self, module: str, completed: bool = True) -> None:
        """Update progress on analysis modules"""
        if completed and module not in self.completed_modules:
            self.completed_modules.append(module)
        elif not completed and module in self.completed_modules:
            self.completed_modules.remove(module)

    def set_focus(self, focus_area: str) -> None:
        """Set current focus area"""
        self.current_focus = focus_area

    def get_requirements_string(self) -> str:
        """Get human-readable requirements"""
        req_str = [f"Analysis goal: {self.analysis_goal}",
                   f"Data file: {self.data_file}",
                   "\nRequirements:"]

        for i, req in enumerate(self.requirements, 1):
            req_str.append(f"  {i}. {req}")

        return "\n".join(req_str)

    def get_progress_string(self) -> str:
        """Get human-readable progress"""
        total_modules = len(self.requirements)
        completed = len(self.completed_modules)
        progress = [f"Progress: {completed}/{total_modules} modules completed"]

        if self.completed_modules:
            progress.append("\nCompleted modules:")
            for module in self.completed_modules:
                progress.append(f"  - {module}")

        if self.current_focus:
            progress.append(f"\nCurrent focus: {self.current_focus}")

        return "\n".join(progress)


class AnalysisContext:
    """Combined context manager for full analysis state"""

    def __init__(self, analysis_goal: str, data_file: str, requirements: List[str]):
        self.data_context = DataContext()
        self.analysis_history = AnalysisHistory()
        self.intent_context = IntentContext(analysis_goal, data_file, requirements)
        self.created_at = datetime.now()
        self.last_updated = datetime.now()

    def update_data(self, df: pd.DataFrame) -> None:
        """Update data context"""
        self.data_context.update_profile(df)
        self.update_timestamp()

    def add_analysis_step(self, name: str, description: str, input_shape: Tuple[int, int],
                          output_shape: Tuple[int, int], code_snippet: Optional[str] = None,
                          validation_result: Optional[Dict[str, Any]] = None,
                          chart_path: Optional[str] = None) -> None:
        """Add step to analysis history"""
        self.analysis_history.add_step(
            name=name,
            description=description,
            input_shape=input_shape,
            output_shape=output_shape,
            code_snippet=code_snippet,
            validation_result=validation_result,
            chart_path=chart_path
        )
        self.update_timestamp()

    def set_focus(self, focus_area: str) -> None:
        """Set current focus area"""
        self.intent_context.set_focus(focus_area)
        self.update_timestamp()

    def update_progress(self, module: str, completed: bool = True) -> None:
        """Update analysis module progress"""
        self.intent_context.update_progress(module, completed)
        self.update_timestamp()

    def update_timestamp(self) -> None:
        """Update last_updated timestamp"""
        self.last_updated = datetime.now()

    def get_full_context_string(self) -> str:
        """Get complete context as human-readable string"""
        context = ["="*80,
                   "ANALYSIS CONTEXT",
                   "="*80,
                   self.intent_context.get_requirements_string(),
                   "\n" + "="*40,
                   self.data_context.get_summary_string(),
                   "\n" + "="*40,
                   self.analysis_history.get_history_string(),
                   "\n" + "="*40,
                   self.intent_context.get_progress_string(),
                   "="*80]

        return "\n".join(filter(None, context))
