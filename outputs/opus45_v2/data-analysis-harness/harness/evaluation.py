"""
Evaluation (V) - Structured trajectory logging in JSONL format.

Records each step with: input shape, executed code, output shape, generated charts.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, asdict
import pandas as pd


@dataclass
class TrajectoryStep:
    """Single step in the analysis trajectory."""
    step_id: int
    timestamp: str
    action: str
    action_input: dict
    input_shapes: dict[str, tuple]
    code_executed: Optional[str]
    output_shape: Optional[dict]
    charts_generated: list[str]
    insights_added: list[str]
    tool_result: dict
    duration_ms: float
    success: bool
    error: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)


class TrajectoryLogger:
    """
    Logs analysis trajectory in JSONL format.

    Each line records:
    - Step ID and timestamp
    - Action taken and inputs
    - Input DataFrame shapes
    - Code executed (if any)
    - Output shapes
    - Charts generated
    - Insights added
    - Success/failure status
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.trajectory_path = self.output_dir / "trajectory.jsonl"
        self.steps: list[TrajectoryStep] = []
        self._step_counter = 0

        if self.trajectory_path.exists():
            self.trajectory_path.unlink()

    def _get_dataframe_shapes(self, dataframes: dict[str, pd.DataFrame]) -> dict[str, tuple]:
        """Extract shapes from DataFrames."""
        return {name: tuple(df.shape) for name, df in dataframes.items()}

    def log_step(
        self,
        action: str,
        action_input: dict,
        input_dataframes: dict[str, pd.DataFrame],
        code_executed: Optional[str],
        output_shape: Optional[dict],
        charts_generated: list[str],
        insights_added: list[str],
        tool_result: dict,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None
    ) -> TrajectoryStep:
        """Log a single step in the trajectory."""
        step = TrajectoryStep(
            step_id=self._step_counter,
            timestamp=datetime.now().isoformat(),
            action=action,
            action_input=self._sanitize_for_json(action_input),
            input_shapes=self._get_dataframe_shapes(input_dataframes),
            code_executed=code_executed,
            output_shape=output_shape,
            charts_generated=charts_generated,
            insights_added=insights_added,
            tool_result=self._sanitize_for_json(tool_result),
            duration_ms=duration_ms,
            success=success,
            error=error
        )

        self.steps.append(step)
        self._step_counter += 1

        with open(self.trajectory_path, "a") as f:
            f.write(json.dumps(step.to_dict(), default=str) + "\n")

        return step

    def _sanitize_for_json(self, obj: Any) -> Any:
        """Sanitize object for JSON serialization."""
        if isinstance(obj, pd.DataFrame):
            return {"type": "DataFrame", "shape": list(obj.shape)}
        elif isinstance(obj, pd.Series):
            return {"type": "Series", "shape": [len(obj)]}
        elif isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._sanitize_for_json(v) for v in obj]
        elif hasattr(obj, '__dict__'):
            return str(obj)
        else:
            try:
                json.dumps(obj)
                return obj
            except (TypeError, ValueError):
                return str(obj)

    def get_step(self, step_id: int) -> Optional[TrajectoryStep]:
        """Get a specific step by ID."""
        if 0 <= step_id < len(self.steps):
            return self.steps[step_id]
        return None

    def get_all_steps(self) -> list[TrajectoryStep]:
        """Get all logged steps."""
        return list(self.steps)

    def get_summary(self) -> dict:
        """Get summary statistics of the trajectory."""
        if not self.steps:
            return {
                "total_steps": 0,
                "successful_steps": 0,
                "failed_steps": 0,
                "total_duration_ms": 0,
                "actions_used": {},
                "charts_generated": 0,
                "insights_recorded": 0
            }

        successful = sum(1 for s in self.steps if s.success)
        failed = len(self.steps) - successful
        total_duration = sum(s.duration_ms for s in self.steps)

        actions = {}
        for s in self.steps:
            actions[s.action] = actions.get(s.action, 0) + 1

        charts = sum(len(s.charts_generated) for s in self.steps)
        insights = sum(len(s.insights_added) for s in self.steps)

        return {
            "total_steps": len(self.steps),
            "successful_steps": successful,
            "failed_steps": failed,
            "total_duration_ms": total_duration,
            "average_step_duration_ms": total_duration / len(self.steps),
            "actions_used": actions,
            "charts_generated": charts,
            "insights_recorded": insights
        }

    def export_trajectory(self, filepath: Optional[Path] = None) -> Path:
        """Export complete trajectory to a file."""
        filepath = filepath or self.trajectory_path
        with open(filepath, "w") as f:
            for step in self.steps:
                f.write(json.dumps(step.to_dict(), default=str) + "\n")
        return filepath

    def load_trajectory(self, filepath: Path) -> list[TrajectoryStep]:
        """Load trajectory from JSONL file."""
        self.steps = []
        with open(filepath, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    step = TrajectoryStep(**data)
                    self.steps.append(step)
        self._step_counter = len(self.steps)
        return self.steps


class EvaluationMetrics:
    """Computes evaluation metrics from trajectory."""

    def __init__(self, trajectory: TrajectoryLogger):
        self.trajectory = trajectory

    def compute_metrics(self) -> dict:
        """Compute all evaluation metrics."""
        steps = self.trajectory.get_all_steps()

        if not steps:
            return {
                "completion": False,
                "efficiency": 0,
                "success_rate": 0,
                "insight_quality": 0
            }

        summary = self.trajectory.get_summary()

        finished = any(s.action == "finish" and s.success for s in steps)

        efficiency = 1.0 if summary["total_steps"] <= 10 else max(0, 1 - (summary["total_steps"] - 10) / 20)

        success_rate = summary["successful_steps"] / summary["total_steps"] if summary["total_steps"] > 0 else 0

        insights_count = summary["insights_recorded"]
        insight_quality = min(1.0, insights_count / 5)

        chart_count = summary["charts_generated"]
        visualization_score = min(1.0, chart_count / 3)

        return {
            "completion": finished,
            "efficiency": round(efficiency, 3),
            "success_rate": round(success_rate, 3),
            "insight_quality": round(insight_quality, 3),
            "visualization_score": round(visualization_score, 3),
            "total_steps": summary["total_steps"],
            "total_duration_ms": summary["total_duration_ms"]
        }

    def check_data_backed_insights(self, insights: list[str]) -> dict:
        """Check if insights are backed by data (contain numbers)."""
        results = []
        for insight in insights:
            has_numbers = any(c.isdigit() for c in insight)
            has_percentage = "%" in insight
            has_currency = any(c in insight for c in ["$", "€", "¥", "£"])

            results.append({
                "insight": insight[:100],
                "has_numbers": has_numbers,
                "has_percentage": has_percentage,
                "has_currency": has_currency,
                "is_data_backed": has_numbers or has_percentage or has_currency
            })

        data_backed_count = sum(1 for r in results if r["is_data_backed"])

        return {
            "total_insights": len(insights),
            "data_backed_insights": data_backed_count,
            "data_backed_ratio": data_backed_count / len(insights) if insights else 0,
            "details": results
        }


def create_evaluation_report(trajectory: TrajectoryLogger, output_path: Path) -> Path:
    """Create an evaluation report from trajectory."""
    metrics = EvaluationMetrics(trajectory)
    computed = metrics.compute_metrics()
    summary = trajectory.get_summary()

    report = {
        "generated_at": datetime.now().isoformat(),
        "trajectory_path": str(trajectory.trajectory_path),
        "summary": summary,
        "metrics": computed,
        "steps": [s.to_dict() for s in trajectory.get_all_steps()]
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return output_path
