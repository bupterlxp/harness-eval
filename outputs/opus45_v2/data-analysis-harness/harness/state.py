"""
State Store (S) - Persistent analysis state with snapshot and rollback support.
"""

import json
import copy
import hashlib
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
import pandas as pd


@dataclass
class StepSnapshot:
    """Snapshot of state at a specific step."""
    step_id: int
    timestamp: str
    dataframes: dict[str, dict]  # name -> {schema, stats, sample_hash}
    variables: dict[str, Any]
    code_executed: str
    output_shape: Optional[dict]
    charts_generated: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StepSnapshot":
        return cls(**data)


class DataFrameStore:
    """Manages DataFrames separately from JSON-serializable state."""

    def __init__(self):
        self._dataframes: dict[str, pd.DataFrame] = {}
        self._history: dict[int, dict[str, pd.DataFrame]] = {}

    def set(self, name: str, df: pd.DataFrame) -> None:
        self._dataframes[name] = df.copy()

    def get(self, name: str) -> Optional[pd.DataFrame]:
        return self._dataframes.get(name)

    def get_all(self) -> dict[str, pd.DataFrame]:
        return dict(self._dataframes)

    def remove(self, name: str) -> None:
        self._dataframes.pop(name, None)

    def list_names(self) -> list[str]:
        return list(self._dataframes.keys())

    def snapshot(self, step_id: int) -> None:
        self._history[step_id] = {k: v.copy() for k, v in self._dataframes.items()}

    def restore(self, step_id: int) -> bool:
        if step_id in self._history:
            self._dataframes = {k: v.copy() for k, v in self._history[step_id].items()}
            for sid in list(self._history.keys()):
                if sid > step_id:
                    del self._history[sid]
            return True
        return False

    def clear_history_after(self, step_id: int) -> None:
        for sid in list(self._history.keys()):
            if sid > step_id:
                del self._history[sid]


def compute_df_hash(df: pd.DataFrame) -> str:
    """Compute a hash for DataFrame sample for integrity check."""
    sample = df.head(5).to_json()
    return hashlib.md5(sample.encode()).hexdigest()[:8]


def get_df_schema(df: pd.DataFrame) -> dict:
    """Extract DataFrame schema (column names and types)."""
    return {col: str(dtype) for col, dtype in df.dtypes.items()}


def get_df_stats(df: pd.DataFrame) -> dict:
    """Extract basic statistics for DataFrame."""
    stats = {
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "null_counts": df.isnull().sum().to_dict(),
        "memory_mb": df.memory_usage(deep=True).sum() / 1024 / 1024
    }

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if numeric_cols:
        desc = df[numeric_cols].describe().to_dict()
        stats["numeric_summary"] = {
            col: {k: round(v, 4) if isinstance(v, float) else v
                  for k, v in col_stats.items()}
            for col, col_stats in desc.items()
        }

    return stats


class StateStore:
    """
    Persistent state store with snapshot and rollback capabilities.
    Maintains both JSON-serializable metadata and DataFrame storage.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.df_store = DataFrameStore()
        self.current_step: int = 0
        self.variables: dict[str, Any] = {}
        self.snapshots: list[StepSnapshot] = []
        self.charts: list[dict] = []
        self.insights: list[str] = []
        self._last_code: str = ""
        self._last_output_shape: Optional[dict] = None

    def set_dataframe(self, name: str, df: pd.DataFrame) -> None:
        """Store a DataFrame."""
        self.df_store.set(name, df)

    def get_dataframe(self, name: str) -> Optional[pd.DataFrame]:
        """Retrieve a DataFrame."""
        return self.df_store.get(name)

    def list_dataframes(self) -> list[str]:
        """List all stored DataFrame names."""
        return self.df_store.list_names()

    def get_all_dataframes(self) -> dict[str, pd.DataFrame]:
        """Get all DataFrames."""
        return self.df_store.get_all()

    def set_variable(self, name: str, value: Any) -> None:
        """Store a variable (must be JSON-serializable)."""
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Retrieve a variable."""
        return self.variables.get(name, default)

    def record_code(self, code: str) -> None:
        """Record code executed in current step."""
        self._last_code = code

    def record_output_shape(self, shape: dict) -> None:
        """Record output shape from current step."""
        self._last_output_shape = shape

    def add_chart(self, path: str, chart_type: str, description: str) -> None:
        """Record a generated chart."""
        self.charts.append({
            "path": path,
            "chart_type": chart_type,
            "description": description
        })

    def add_insight(self, insight: str) -> None:
        """Add an insight with data backing."""
        self.insights.append(insight)

    def snapshot(self) -> StepSnapshot:
        """Take a snapshot of current state."""
        df_meta = {}
        for name in self.df_store.list_names():
            df = self.df_store.get(name)
            if df is not None:
                df_meta[name] = {
                    "schema": get_df_schema(df),
                    "stats": get_df_stats(df),
                    "sample_hash": compute_df_hash(df)
                }

        charts_this_step = [c["path"] for c in self.charts if c not in
                           (self.snapshots[-1].charts_generated if self.snapshots else [])]

        snap = StepSnapshot(
            step_id=self.current_step,
            timestamp=datetime.now().isoformat(),
            dataframes=df_meta,
            variables=copy.deepcopy(self.variables),
            code_executed=self._last_code,
            output_shape=self._last_output_shape,
            charts_generated=charts_this_step
        )

        self.df_store.snapshot(self.current_step)
        self.snapshots.append(snap)
        self.current_step += 1
        self._last_code = ""
        self._last_output_shape = None

        return snap

    def rollback(self, to_step: int) -> bool:
        """Rollback state to a specific step."""
        if to_step < 0 or to_step >= len(self.snapshots):
            return False

        if not self.df_store.restore(to_step):
            return False

        target_snap = self.snapshots[to_step]
        self.variables = copy.deepcopy(target_snap.variables)
        self.snapshots = self.snapshots[:to_step + 1]
        self.current_step = to_step + 1

        kept_charts = set()
        for snap in self.snapshots:
            kept_charts.update(snap.charts_generated)
        self.charts = [c for c in self.charts if c["path"] in kept_charts]

        return True

    def get_snapshot(self, step_id: int) -> Optional[StepSnapshot]:
        """Get snapshot for a specific step."""
        if 0 <= step_id < len(self.snapshots):
            return self.snapshots[step_id]
        return None

    def save_state(self, filepath: Optional[Path] = None) -> Path:
        """Save current state to JSON file."""
        filepath = filepath or self.output_dir / "state.json"
        state_data = {
            "current_step": self.current_step,
            "variables": self.variables,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "charts": self.charts,
            "insights": self.insights
        }
        with open(filepath, "w") as f:
            json.dump(state_data, f, indent=2, default=str)
        return filepath

    def load_state(self, filepath: Path) -> bool:
        """Load state from JSON file (note: DataFrames must be reloaded separately)."""
        if not filepath.exists():
            return False
        with open(filepath) as f:
            data = json.load(f)
        self.current_step = data["current_step"]
        self.variables = data["variables"]
        self.snapshots = [StepSnapshot.from_dict(s) for s in data["snapshots"]]
        self.charts = data["charts"]
        self.insights = data.get("insights", [])
        return True
