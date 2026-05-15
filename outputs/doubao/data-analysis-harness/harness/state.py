import pandas as pd
import os
import json
from datetime import datetime
from typing import Dict, Optional, Any, List, Tuple
from copy import deepcopy
from .schemas import ExecutionState, AnalysisStep, ChartRecord, Insight, ValidationResult


class ExecutionStateManager:
    """Manages the execution state with snapshot/rollback capabilities"""

    def __init__(self, state_file: Optional[str] = None):
        self.state_file = state_file or f"analysis_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.states: Dict[str, ExecutionState] = {}
        self.current_state_id: str = "initial"

    def create_snapshot(self, state_id: Optional[str] = None) -> str:
        """Create a snapshot of current state"""
        if state_id is None:
            state_id = f"step_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Deep copy the current state
        current_state = self.states.get(self.current_state_id, ExecutionState())
        snapshot = ExecutionState(
            current_step=current_state.current_step,
            dataframes=deepcopy(current_state.dataframes),
            variables=deepcopy(current_state.variables),
            analysis_history=deepcopy(current_state.analysis_history),
            charts=deepcopy(current_state.charts),
            insights=deepcopy(current_state.insights),
            validation_results=deepcopy(current_state.validation_results),
            start_time=current_state.start_time,
            last_updated=current_state.last_updated
        )

        self.states[state_id] = snapshot
        return state_id

    def rollback(self, state_id: str) -> bool:
        """Rollback to a previous snapshot"""
        if state_id not in self.states:
            return False

        self.current_state_id = state_id
        return True

    def get_current_state(self) -> ExecutionState:
        """Get the current execution state"""
        if self.current_state_id not in self.states:
            self.states[self.current_state_id] = ExecutionState()
        return self.states[self.current_state_id]

    def update_current_state(self, state: ExecutionState) -> None:
        """Update the current execution state"""
        state.update_timestamp()
        self.states[self.current_state_id] = state

    def list_snapshots(self) -> List[str]:
        """List all available snapshot IDs"""
        return list(self.states.keys())

    def save_state(self, filepath: Optional[str] = None) -> str:
        """Save current state to JSON file"""
        save_path = filepath or self.state_file

        current_state = self.get_current_state()

        # Convert to serializable format
        state_dict = {
            "current_step": current_state.current_step,
            "variables": current_state.variables,
            "analysis_history": [{
                "name": step.name,
                "description": step.description,
                "input_shape": step.input_shape,
                "output_shape": step.output_shape,
                "timestamp": step.timestamp.isoformat(),
                "code_snippet": step.code_snippet,
                "validation_result": step.validation_result,
                "chart_path": step.chart_path
            } for step in current_state.analysis_history],
            "charts": [{
                "name": chart.name,
                "path": chart.path,
                "title": chart.title,
                "created_at": chart.created_at.isoformat(),
                "data_summary": chart.data_summary
            } for chart in current_state.charts],
            "insights": [{
                "title": insight.title,
                "description": insight.description,
                "supporting_data": insight.supporting_data,
                "confidence": insight.confidence
            } for insight in current_state.insights],
            "validation_results": [{
                "is_valid": res.is_valid,
                "errors": res.errors,
                "warnings": res.warnings,
                "checks_performed": res.checks_performed
            } for res in current_state.validation_results],
            "start_time": current_state.start_time.isoformat(),
            "last_updated": current_state.last_updated.isoformat()
        }

        # Save dataframes separately as pickle
        if current_state.dataframes:
            df_dir = f"{save_path}_dfs"
            os.makedirs(df_dir, exist_ok=True)

            for name, df in current_state.dataframes.items():
                df_path = os.path.join(df_dir, f"{name}.pkl")
                df.to_pickle(df_path)

            state_dict["dataframes_dir"] = df_dir

        with open(save_path, 'w') as f:
            json.dump(state_dict, f, indent=2)

        return save_path

    @classmethod
    def load_state(cls, filepath: str) -> 'ExecutionStateManager':
        """Load state from JSON file"""
        manager = cls(filepath)

        with open(filepath, 'r') as f:
            state_dict = json.load(f)

        # Reconstruct ExecutionState
        dataframes = {}
        if "dataframes_dir" in state_dict:
            df_dir = state_dict["dataframes_dir"]
            if os.path.exists(df_dir):
                for filename in os.listdir(df_dir):
                    if filename.endswith(".pkl"):
                        name = filename[:-4]
                        df_path = os.path.join(df_dir, filename)
                        dataframes[name] = pd.read_pickle(df_path)

        analysis_history = []
        for step_dict in state_dict.get("analysis_history", []):
            analysis_history.append(AnalysisStep(
                name=step_dict["name"],
                description=step_dict["description"],
                input_shape=tuple(step_dict["input_shape"]),
                output_shape=tuple(step_dict["output_shape"]),
                timestamp=datetime.fromisoformat(step_dict["timestamp"]),
                code_snippet=step_dict.get("code_snippet"),
                validation_result=step_dict.get("validation_result"),
                chart_path=step_dict.get("chart_path")
            ))

        charts = []
        for chart_dict in state_dict.get("charts", []):
            charts.append(ChartRecord(
                name=chart_dict["name"],
                path=chart_dict["path"],
                title=chart_dict["title"],
                created_at=datetime.fromisoformat(chart_dict["created_at"]),
                data_summary=chart_dict["data_summary"]
            ))

        insights = []
        for insight_dict in state_dict.get("insights", []):
            insights.append(Insight(
                title=insight_dict["title"],
                description=insight_dict["description"],
                supporting_data=insight_dict["supporting_data"],
                confidence=insight_dict.get("confidence", 1.0)
            ))

        validation_results = []
        for res_dict in state_dict.get("validation_results", []):
            validation_results.append(ValidationResult(
                is_valid=res_dict["is_valid"],
                errors=res_dict.get("errors", []),
                warnings=res_dict.get("warnings", []),
                checks_performed=res_dict.get("checks_performed", 0)
            ))

        initial_state = ExecutionState(
            current_step=state_dict.get("current_step", "LOAD"),
            dataframes=dataframes,
            variables=state_dict.get("variables", {}),
            analysis_history=analysis_history,
            charts=charts,
            insights=insights,
            validation_results=validation_results,
            start_time=datetime.fromisoformat(state_dict.get("start_time", datetime.now().isoformat())),
            last_updated=datetime.fromisoformat(state_dict.get("last_updated", datetime.now().isoformat()))
        )

        manager.states["initial"] = initial_state
        manager.current_state_id = "initial"

        return manager