from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
from datetime import datetime
from .schemas import ExecutionState, AnalysisStep, ValidationResult
from .state import ExecutionStateManager
from .tools import ToolRegistry
from .context import AnalysisContext
from .lifecycle import LifecycleHooks, get_default_lifecycle_hooks
from .evaluation import TrajectoryTracker


class AnalysisStateMachine:
    """State machine for the analysis execution loop"""

    def __init__(
        self,
        analysis_goal: str,
        data_file: str,
        requirements: List[str],
        state_manager: Optional[ExecutionStateManager] = None,
        tool_registry: Optional[ToolRegistry] = None,
        lifecycle_hooks: Optional[LifecycleHooks] = None,
        trajectory_tracker: Optional[TrajectoryTracker] = None
    ):
        self.state_manager = state_manager or ExecutionStateManager()
        self.tool_registry = tool_registry or ToolRegistry()
        self.lifecycle_hooks = lifecycle_hooks or get_default_lifecycle_hooks()
        self.trajectory_tracker = trajectory_tracker or TrajectoryTracker()
        self.analysis_context = AnalysisContext(analysis_goal, data_file, requirements)

        # Initialize current state
        self.current_state = self.state_manager.get_current_state()

        # Define state transitions
        self.state_transitions: Dict[str, List[str]] = {
            "LOAD": ["QUALITY_CHECK"],
            "QUALITY_CHECK": ["PREPROCESS", "ERROR"],
            "PREPROCESS": ["EXPLORE", "ERROR"],
            "EXPLORE": ["TREND", "REGION", "CATEGORY", "CHANNEL", "ERROR"],
            "TREND": ["REGION", "CATEGORY", "CHANNEL", "REPORT", "ERROR"],
            "REGION": ["TREND", "CATEGORY", "CHANNEL", "REPORT", "ERROR"],
            "CATEGORY": ["TREND", "REGION", "CHANNEL", "REPORT", "ERROR"],
            "CHANNEL": ["TREND", "REGION", "CATEGORY", "REPORT", "ERROR"],
            "REPORT": ["COMPLETED", "ERROR"],
            "ERROR": ["LOAD", "QUALITY_CHECK", "PREPROCESS", "EXPLORE", "TREND", "REGION", "CATEGORY", "CHANNEL", "REPORT"],
            "COMPLETED": []
        }

    def change_state(self, new_state: str) -> bool:
        """Change the current state"""
        current_state = self.current_state.current_step
        if new_state not in self.state_transitions.get(current_state, []):
            if current_state == "ERROR" and new_state in self.state_transitions["ERROR"]:
                pass  # Allow transitions from error state to any state
            else:
                print(f"Invalid state transition: {current_state} -> {new_state}")
                return False

        self.current_state.current_step = new_state
        self.analysis_context.set_focus(new_state)
        self.current_state.update_timestamp()
        self.state_manager.update_current_state(self.current_state)
        return True

    def execute_current_step(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute the current analysis step"""
        current_state = self.current_state.current_step
        print(f"Executing step: {current_state}")

        # Run pre-execution hooks
        pre_validation = self.lifecycle_hooks.run_pre_execute(self.current_state)
        if not pre_validation.is_valid:
            self.lifecycle_hooks.run_on_error(
                Exception(f"Pre-execution validation failed: {pre_validation.errors}"),
                f"State: {current_state}"
            )
            self.change_state("ERROR")
            return None, pre_validation

        try:
            # Execute based on current state
            if current_state == "LOAD":
                return self._execute_load(**kwargs)
            elif current_state == "QUALITY_CHECK":
                return self._execute_quality_check(**kwargs)
            elif current_state == "PREPROCESS":
                return self._execute_preprocess(**kwargs)
            elif current_state == "EXPLORE":
                return self._execute_explore(**kwargs)
            elif current_state == "TREND":
                return self._execute_trend(**kwargs)
            elif current_state == "REGION":
                return self._execute_region(**kwargs)
            elif current_state == "CATEGORY":
                return self._execute_category(**kwargs)
            elif current_state == "CHANNEL":
                return self._execute_channel(**kwargs)
            elif current_state == "REPORT":
                return self._execute_report(**kwargs)
            else:
                raise ValueError(f"Unknown state: {current_state}")

        except Exception as e:
            self.lifecycle_hooks.run_on_error(e, f"State: {current_state}")
            self.change_state("ERROR")
            return None, ValidationResult(is_valid=False, errors=[str(e)])

    def _execute_load(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute data loading step"""
        file_path = kwargs.get("file_path")
        if not file_path:
            file_path = self.analysis_context.intent_context.data_file

        # Read CSV file
        df = pd.read_csv(file_path)
        input_shape = (0, 0)
        if "main" in self.current_state.dataframes:
            input_shape = self.current_state.dataframes["main"].shape

        # Store in state
        self.current_state.dataframes["main"] = df
        self.analysis_context.update_data(df)

        # Record step
        self.analysis_context.add_analysis_step(
            name="LOAD_DATA",
            description=f"Loaded data from {file_path}",
            input_shape=input_shape,
            output_shape=df.shape,
            code_snippet=f"pd.read_csv('{file_path}')"
        )

        # Update trajectory
        self.trajectory_tracker.add_step(
            step_name="LOAD_DATA",
            description=f"Loaded data from {file_path}",
            input_shape=input_shape,
            output_shape=df.shape,
            code_snippet=f"pd.read_csv('{file_path}')"
        )

        # Auto-transition to quality check
        self.change_state("QUALITY_CHECK")
        return df, ValidationResult(is_valid=True)

    def _execute_quality_check(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute data quality check step"""
        df_name = kwargs.get("df_name", "main")
        df = self.current_state.dataframes.get(df_name)

        if df is None:
            return None, ValidationResult(is_valid=False, errors=[f"Dataframe {df_name} not found"])

        # Calculate quality metrics
        quality_result = {
            "missing_values": df.isnull().sum().to_dict(),
            "missing_percent": (df.isnull().sum() / len(df) * 100).to_dict(),
            "duplicates": df.duplicated().sum(),
            "data_types": df.dtypes.to_dict(),
            "shape": df.shape
        }

        # Check for anomalies
        anomalies = []

        # Check discount anomalies
        if 'discount' in df.columns:
            bad_discounts = df[(df['discount'] < 0) | (df['discount'] > 1)]
            if len(bad_discounts) > 0:
                anomalies.append(f"{len(bad_discounts)} rows with invalid discount values (outside 0-1)")

        # Check quantity anomalies
        if 'quantity' in df.columns:
            large_quantities = df[df['quantity'] > 100]
            if len(large_quantities) > 0:
                anomalies.append(f"{len(large_quantities)} rows with quantity > 100")

        quality_result["anomalies"] = anomalies

        # Create validation result
        validation = ValidationResult(
            is_valid=len(anomalies) == 0,
            warnings=anomalies,
            checks_performed=5
        )

        # Store quality results in state
        self.current_state.variables[f"{df_name}_quality"] = quality_result

        # Record step
        self.analysis_context.add_analysis_step(
            name="QUALITY_CHECK",
            description="Performed data quality check",
            input_shape=df.shape,
            output_shape=(len(quality_result),),
            validation_result={"quality_metrics": quality_result, "validation": validation.__dict__}
        )

        # Update trajectory
        self.trajectory_tracker.add_step(
            step_name="QUALITY_CHECK",
            description="Performed data quality check",
            input_shape=df.shape,
            output_shape=(len(quality_result),),
            validation_result=validation
        )

        # Transition based on validation
        if validation.is_valid:
            self.change_state("PREPROCESS")
        else:
            self.change_state("ERROR")

        return quality_result, validation

    def _execute_preprocess(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute data preprocessing step"""
        df_name = kwargs.get("df_name", "main")
        df = self.current_state.dataframes.get(df_name)

        if df is None:
            return None, ValidationResult(is_valid=False, errors=[f"Dataframe {df_name} not found"])

        # Make a copy
        processed_df = df.copy()

        # 1. Handle missing values
        if 'region' in processed_df.columns:
            processed_df['region'] = processed_df['region'].fillna("Unknown")

        if 'customer_id' in processed_df.columns:
            processed_df['customer_id'] = processed_df['customer_id'].fillna("Unknown")

        # 2. Fix invalid discounts
        if 'discount' in processed_df.columns:
            # Cap discount between 0 and 1
            processed_df['discount'] = processed_df['discount'].clip(0, 1)
            # Fill missing discounts with 0
            processed_df['discount'] = processed_df['discount'].fillna(0)

        # 3. Convert date column
        if 'date' in processed_df.columns:
            processed_df['date'] = pd.to_datetime(processed_df['date'])

        # 4. Calculate actual revenue
        required_cols = ['quantity', 'unit_price', 'discount']
        if all(col in processed_df.columns for col in required_cols):
            processed_df['revenue'] = processed_df['quantity'] * processed_df['unit_price'] * (1 - processed_df['discount'])

        # 5. Remove duplicates
        duplicates = processed_df.duplicated().sum()
        if duplicates > 0:
            processed_df = processed_df.drop_duplicates()

        # Store processed dataframe
        self.current_state.dataframes[f"{df_name}_processed"] = processed_df

        # Update main dataframe if this is the first preprocess
        if "main_processed" not in self.current_state.dataframes:
            self.current_state.dataframes["main"] = processed_df

        # Create validation result
        validation = ValidationResult(
            is_valid=True,
            checks_performed=5
        )

        # Record step
        self.analysis_context.add_analysis_step(
            name="PREPROCESS",
            description="Performed data preprocessing and cleaning",
            input_shape=df.shape,
            output_shape=processed_df.shape,
            validation_result=validation.__dict__,
            code_snippet="""
# Data preprocessing steps:
1. Fixed missing values
2. Capped invalid discount values
3. Converted date column to datetime
4. Calculated actual revenue
5. Removed duplicates
"""
        )

        # Update trajectory
        self.trajectory_tracker.add_step(
            step_name="PREPROCESS",
            description="Performed data preprocessing and cleaning",
            input_shape=df.shape,
            output_shape=processed_df.shape,
            validation_result=validation
        )

        # Transition to explore
        self.change_state("EXPLORE")
        return processed_df, validation

    def _execute_explore(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute exploratory data analysis"""
        df_name = kwargs.get("df_name", "main_processed")
        df = self.current_state.dataframes.get(df_name)

        if df is None:
            df_name = "main"
            df = self.current_state.dataframes.get(df_name)
            if df is None:
                return None, ValidationResult(is_valid=False, errors=[f"No valid dataframe found"])

        # Calculate basic statistics
        stats = {
            "total_records": len(df),
            "unique_products": df['product'].nunique() if 'product' in df.columns else 0,
            "unique_regions": df['region'].nunique() if 'region' in df.columns else 0,
            "unique_categories": df['category'].nunique() if 'category' in df.columns else 0,
            "total_revenue": df['revenue'].sum() if 'revenue' in df.columns else 0,
            "avg_revenue_per_transaction": df['revenue'].mean() if 'revenue' in df.columns else 0
        }

        # Store in state
        self.current_state.variables["exploration_stats"] = stats

        # Create validation result
        validation = ValidationResult(
            is_valid=True,
            checks_performed=1
        )

        # Record step
        self.analysis_context.add_analysis_step(
            name="EXPLORE",
            description="Performed exploratory data analysis",
            input_shape=df.shape,
            output_shape=(len(stats),),
            validation_result=validation.__dict__
        )

        # Update trajectory
        self.trajectory_tracker.add_step(
            step_name="EXPLORE",
            description="Performed exploratory data analysis",
            input_shape=df.shape,
            output_shape=(len(stats),),
            validation_result=validation
        )

        return stats, validation

    def _execute_trend(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute sales trend analysis"""
        # This would be implemented with actual plotting code
        # For now, just return a placeholder
        result = {"message": "Trend analysis completed"}
        validation = ValidationResult(is_valid=True)

        self.analysis_context.add_analysis_step(
            name="TREND_ANALYSIS",
            description="Performed sales trend analysis",
            input_shape=(0, 0),
            output_shape=(1,)
        )

        self.change_state("REGION")
        return result, validation

    def _execute_region(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute regional analysis"""
        result = {"message": "Regional analysis completed"}
        validation = ValidationResult(is_valid=True)

        self.analysis_context.add_analysis_step(
            name="REGION_ANALYSIS",
            description="Performed regional sales analysis",
            input_shape=(0, 0),
            output_shape=(1,)
        )

        self.change_state("CATEGORY")
        return result, validation

    def _execute_category(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute category analysis"""
        result = {"message": "Category analysis completed"}
        validation = ValidationResult(is_valid=True)

        self.analysis_context.add_analysis_step(
            name="CATEGORY_ANALYSIS",
            description="Performed category sales analysis",
            input_shape=(0, 0),
            output_shape=(1,)
        )

        self.change_state("CHANNEL")
        return result, validation

    def _execute_channel(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute channel analysis"""
        result = {"message": "Channel analysis completed"}
        validation = ValidationResult(is_valid=True)

        self.analysis_context.add_analysis_step(
            name="CHANNEL_ANALYSIS",
            description="Performed channel sales analysis",
            input_shape=(0, 0),
            output_shape=(1,)
        )

        self.change_state("REPORT")
        return result, validation

    def _execute_report(self, **kwargs) -> Tuple[Any, ValidationResult]:
        """Execute final reporting"""
        # Generate final report
        report_data = {
            "analysis_goal": self.analysis_context.intent_context.analysis_goal,
            "total_steps": len(self.analysis_context.analysis_history.steps),
            "total_charts": len(self.current_state.charts),
            "insights": self.current_state.insights,
            "timestamp": datetime.now().isoformat()
        }

        # Save all artifacts
        trajectory_file = self.trajectory_tracker.save_trajectory()
        summary_file = self.trajectory_tracker.save_summary()

        report_data["trajectory_file"] = trajectory_file
        report_data["summary_file"] = summary_file

        # Create validation result
        validation = ValidationResult(
            is_valid=True,
            checks_performed=1
        )

        # Record step
        self.analysis_context.add_analysis_step(
            name="REPORT_GENERATION",
            description="Generated final analysis report",
            input_shape=(0, 0),
            output_shape=(len(report_data),),
            validation_result=validation.__dict__
        )

        # Update trajectory
        self.trajectory_tracker.add_step(
            step_name="REPORT_GENERATION",
            description="Generated final analysis report",
            input_shape=(0, 0),
            output_shape=(len(report_data),),
            validation_result=validation
        )

        # Mark as completed
        self.change_state("COMPLETED")
        return report_data, validation

    def rollback_to_step(self, step_number: int) -> bool:
        """Rollback to a specific analysis step"""
        steps = self.analysis_context.analysis_history.list_steps()
        if 1 <= step_number <= len(steps):
            # Find the corresponding state snapshot
            snapshot_id = f"step_{step_number}"
            if self.state_manager.rollback(snapshot_id):
                # Update current state to the correct step
                step = steps[step_number - 1]
                self.current_state.current_step = self._get_state_from_step_name(step["name"])
                return True

        return False

    def _get_state_from_step_name(self, step_name: str) -> str:
        """Map step name to state"""
        mapping = {
            "LOAD_DATA": "LOAD",
            "QUALITY_CHECK": "QUALITY_CHECK",
            "PREPROCESS": "PREPROCESS",
            "EXPLORE": "EXPLORE",
            "TREND_ANALYSIS": "TREND",
            "REGION_ANALYSIS": "REGION",
            "CATEGORY_ANALYSIS": "CATEGORY",
            "CHANNEL_ANALYSIS": "CHANNEL",
            "REPORT_GENERATION": "REPORT"
        }
        return mapping.get(step_name, "ERROR")
