"""
Evaluation component - records structured execution trajectory and results
"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EvaluationStep:
    """Represents a single step in the execution trajectory"""
    timestamp: float
    state: str
    action: str
    details: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    duration: float = 0.0


class Evaluator:
    """
    Records and manages structured execution trajectory
    Supports JSONL output format as specified in requirements
    """

    def __init__(self, output_file: Optional[str] = None):
        self.steps: List[EvaluationStep] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.output_file = output_file
        self._initialize_timing()

    def _initialize_timing(self):
        """Initialize timing for execution tracking"""
        self.start_time = time.time()

    def log_step(
        self,
        state: str,
        action: str,
        details: Dict[str, Any],
        result: Optional[Dict[str, Any]] = None
    ):
        """Log a single execution step"""
        last_step = self.steps[-1] if self.steps else None
        duration = 0.0

        if last_step:
            duration = time.time() - last_step.timestamp

        step = EvaluationStep(
            timestamp=time.time(),
            state=state,
            action=action,
            details=details,
            result=result,
            duration=duration
        )

        self.steps.append(step)

    def log_task_start(self, task_spec: Dict[str, Any]):
        """Log task start event"""
        self.log_step(
            "INITIALIZED",
            "task_start",
            {
                "task_type": task_spec.get("task_type"),
                "description": task_spec.get("description"),
                "repo_path": task_spec.get("repo_path"),
                "constraints": task_spec.get("constraints", [])
            }
        )

    def log_task_end(self):
        """Log task end event"""
        self.end_time = time.time()
        total_duration = self.end_time - self.start_time if self.start_time else 0

        self.log_step(
            "COMPLETED",
            "task_end",
            {
                "total_duration": total_duration,
                "total_steps": len(self.steps)
            }
        )

    def get_execution_summary(self) -> Dict[str, Any]:
        """Generate summary of execution"""
        if not self.steps:
            return {}

        end_step = self.steps[-1]
        total_duration = end_step.timestamp - self.start_time if self.start_time else 0

        # Count states
        state_counts: Dict[str, int] = {}
        for step in self.steps:
            state_counts[step.state] = state_counts.get(step.state, 0) + 1

        # Calculate action breakdown
        action_counts: Dict[str, int] = {}
        for step in self.steps:
            action_counts[step.action] = action_counts.get(step.action, 0) + 1

        summary = {
            "start_time": datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
            "end_time": datetime.fromtimestamp(end_step.timestamp).isoformat(),
            "total_duration": total_duration,
            "total_steps": len(self.steps),
            "state_counts": state_counts,
            "action_counts": action_counts,
            "final_state": end_step.state,
            "final_action": end_step.action
        }

        return summary

    def write_jsonl(self, file_path: Optional[str] = None):
        """Write trajectory to JSONL file"""
        output_path = file_path or self.output_file
        if not output_path:
            # Generate default filename
            timestamp = int(time.time())
            output_path = f"trajectory_{timestamp}.jsonl"

        with open(output_path, "w") as f:
            for step in self.steps:
                step_dict = {
                    "timestamp": step.timestamp,
                    "state": step.state,
                    "action": step.action,
                    "details": step.details,
                    "result": step.result,
                    "duration": step.duration
                }
                f.write(json.dumps(step_dict) + "\n")

        return output_path

    def write_summary(self, file_path: str):
        """Write summary report to JSON file"""
        summary = self.get_execution_summary()
        with open(file_path, "w") as f:
            json.dump(summary, f, indent=2)

        return file_path

    def get_step_count_by_state(self, state: str) -> int:
        """Count number of steps in a specific state"""
        return sum(1 for step in self.steps if step.state == state)

    def get_step_count_by_action(self, action: str) -> int:
        """Count number of steps with a specific action"""
        return sum(1 for step in self.steps if step.action == action)

    def clear(self):
        """Clear all recorded steps"""
        self.steps = []
        self._initialize_timing()

    def get_trajectory(self) -> List[Dict[str, Any]]:
        """Get full trajectory as list of dictionaries"""
        return [{
            "timestamp": step.timestamp,
            "state": step.state,
            "action": step.action,
            "details": step.details,
            "result": step.result,
            "duration": step.duration
        } for step in self.steps]

    def __str__(self) -> str:
        """String representation of evaluator state"""
        summary = self.get_execution_summary()
        return f"Evaluator(steps={len(self.steps)}, summary={summary})"