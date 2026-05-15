"""
Evaluation trajectory recorder.
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from .schemas import TrajectoryStep, TestResult


class TrajectoryRecorder:
    """Records and saves the execution trajectory."""

    def __init__(self, output_file: str = "trajectory.jsonl"):
        self.output_file = output_file
        self.steps: List[TrajectoryStep] = []
        self.current_step = 0

    def add_step(self, state: str, action: str, code_diff: Optional[str] = None,
                 test_results: Optional[List[TestResult]] = None, duration: float = 0.0) -> None:
        """Add a step to the trajectory."""
        step = TrajectoryStep(
            step_number=self.current_step + 1,
            state=state,
            action=action,
            code_diff=code_diff,
            test_results=test_results or [],
            duration=duration
        )
        self.steps.append(step)
        self.current_step += 1

    def save_to_file(self, output_file: Optional[str] = None) -> str:
        """Save trajectory to JSONL file."""
        file_path = output_file or self.output_file

        with open(file_path, 'w') as f:
            for step in self.steps:
                json.dump(step.dict(), f, default=str)
                f.write('\n')

        return file_path

    def load_from_file(self, input_file: str) -> None:
        """Load trajectory from JSONL file."""
        self.steps = []
        self.current_step = 0

        with open(input_file, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                step = TrajectoryStep(**data)
                self.steps.append(step)
                self.current_step += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the trajectory."""
        if not self.steps:
            return {"total_steps": 0, "total_duration": 0.0}

        total_duration = sum(s.duration for s in self.steps)
        states = set(s.state for s in self.steps)
        actions = [s.action for s in self.steps]

        return {
            "total_steps": self.current_step,
            "total_duration": total_duration,
            "unique_states": list(states),
            "last_state": self.steps[-1].state if self.steps else None,
            "action_count": len(actions),
            "steps_by_state": {state: sum(1 for s in self.steps if s.state == state) for state in states}
        }

    def print_summary(self) -> None:
        """Print a human-readable summary of the trajectory."""
        summary = self.get_summary()
        print("\n=== Trajectory Summary ===")
        print(f"Total steps: {summary['total_steps']}")
        print(f"Total duration: {summary['total_duration']:.2f}s")
        print(f"Unique states visited: {len(summary['unique_states'])}")
        if summary['last_state']:
            print(f"Final state: {summary['last_state']}")
        print("Steps by state:")
        for state, count in summary['steps_by_state'].items():
            print(f"  {state}: {count}")


def load_trajectory(file_path: str) -> TrajectoryRecorder:
    """Load a trajectory from a JSONL file."""
    recorder = TrajectoryRecorder()
    recorder.load_from_file(file_path)
    return recorder