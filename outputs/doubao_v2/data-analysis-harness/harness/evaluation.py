"""
Evaluation component - tracks and logs execution trajectory
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional


class Evaluator:
    """Tracks and logs execution trajectory with structured metadata"""

    def __init__(self, output_dir: Optional[str] = None):
        self.trajectory: List[Dict[str, Any]] = []
        self.output_dir = output_dir
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

    def log_step(
        self,
        step: int,
        tool_name: str,
        params: Dict[str, Any],
        input_shape: Optional[tuple] = None,
        output_shape: Optional[tuple] = None,
        data_changes: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> None:
        """Log a single step in the execution trajectory"""
        step_entry = {
            "step": step,
            "tool": tool_name,
            "timestamp": datetime.now().isoformat(),
            "params": params,
            "input_shape": input_shape,
            "output_shape": output_shape,
            "error": error
        }

        if data_changes:
            step_entry["data_changes"] = data_changes

        self.trajectory.append(step_entry)

    def get_trajectory_summary(self) -> Dict[str, Any]:
        """Get a summary of the entire trajectory"""
        if not self.trajectory:
            return {"total_steps": 0, "tools_used": [], "total_runtime": 0}

        total_runtime = 0
        tools_used = {}
        first_timestamp = datetime.fromisoformat(self.trajectory[0]["timestamp"])
        last_timestamp = datetime.fromisoformat(self.trajectory[-1]["timestamp"])

        for entry in self.trajectory:
            tool = entry["tool"]
            tools_used[tool] = tools_used.get(tool, 0) + 1

        return {
            "total_steps": len(self.trajectory),
            "tools_used": tools_used,
            "total_runtime": (last_timestamp - first_timestamp).total_seconds(),
            "start_time": first_timestamp.isoformat(),
            "end_time": last_timestamp.isoformat()
        }

    def save_trajectory(self, file_path: Optional[str] = None) -> str:
        """Save trajectory to a JSONL file"""
        if not file_path and self.output_dir:
            file_path = os.path.join(self.output_dir, "trajectory.jsonl")
        elif not file_path:
            file_path = "trajectory.jsonl"

        with open(file_path, 'w') as f:
            for entry in self.trajectory:
                json.dump(entry, f)
                f.write('\n')

        return file_path

    def load_trajectory(self, file_path: str) -> None:
        """Load trajectory from a JSONL file"""
        self.trajectory = []
        with open(file_path, 'r') as f:
            for line in f:
                self.trajectory.append(json.loads(line))

    def log_execution_metrics(self, metrics: Dict[str, Any]) -> None:
        """Log additional execution metrics"""
        if not self.trajectory:
            self.trajectory.append({"metrics": metrics})
        else:
            self.trajectory[-1]["metrics"] = metrics

    def validate_step_completeness(self) -> List[str]:
        """Validate that all steps were completed properly"""
        issues = []

        for i, entry in enumerate(self.trajectory):
            if entry.get("error"):
                issues.append(f"Step {i+1} ({entry['tool']}) failed: {entry['error']}")

            if "input_shape" not in entry:
                issues.append(f"Step {i+1} ({entry['tool']}) missing input_shape")

            if "output_shape" not in entry:
                issues.append(f"Step {i+1} ({entry['tool']}) missing output_shape")

        return issues

    def generate_report(self) -> str:
        """Generate a human-readable report of the execution trajectory"""
        summary = self.get_trajectory_summary()
        report = []

        report.append("# Execution Trajectory Report")
        report.append(f"Total steps: {summary['total_steps']}")
        report.append(f"Total runtime: {summary['total_runtime']:.2f} seconds")
        report.append("")

        if summary['tools_used']:
            report.append("## Tools Used")
            for tool, count in summary['tools_used'].items():
                report.append(f"- {tool}: {count} times")
            report.append("")

        report.append("## Step Details")
        for i, entry in enumerate(self.trajectory, 1):
            report.append(f"### Step {i}: {entry['tool']}")
            report.append(f"Timestamp: {entry['timestamp']}")

            if entry.get('input_shape'):
                report.append(f"Input shape: {entry['input_shape']}")

            if entry.get('output_shape'):
                report.append(f"Output shape: {entry['output_shape']}")

            if entry.get('error'):
                report.append(f"❌ Failed: {entry['error']}")
            else:
                report.append(f"✅ Completed")

            report.append("")

        return "\n".join(report)