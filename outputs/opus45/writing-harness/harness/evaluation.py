"""
evaluation.py - V: Evaluation Interface

Implements V3-level trajectory recording with intermediate reasoning,
context snapshots, and goal progress tracking in structured JSONL format.
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

from harness.schemas import (
    TrajectoryEntry, ExecutionState, EventType,
    ComparisonReport, ComparisonDimension
)


class TrajectoryRecorder:
    """
    V component: Records execution trajectory for evaluation.

    V3 level includes:
    - State transitions with timestamps
    - Tool calls with inputs and outputs
    - Intermediate reasoning
    - Context snapshots at key points
    - Goal progress tracking
    """

    def __init__(self, session_id: str, output_dir: str | Path | None = None):
        self.session_id = session_id
        self._step_counter = 0
        self._entries: list[TrajectoryEntry] = []
        self._goal_definitions: dict[str, str] = {}
        self._goal_progress: dict[str, float] = {}

        if output_dir is None:
            output_dir = Path.home() / ".harness" / "trajectories"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.output_path = self.output_dir / f"{session_id}.jsonl"

    def define_goal(self, goal_id: str, description: str) -> None:
        """Define a goal for progress tracking"""
        self._goal_definitions[goal_id] = description
        self._goal_progress[goal_id] = 0.0

    def update_goal_progress(self, goal_id: str, progress: float) -> None:
        """Update progress on a goal (0.0 to 1.0)"""
        self._goal_progress[goal_id] = min(1.0, max(0.0, progress))

    def record(
        self,
        state_before: ExecutionState,
        state_after: ExecutionState,
        event: EventType,
        tool_called: str | None = None,
        tool_input: dict[str, Any] | None = None,
        tool_output_summary: str = "",
        reasoning: str = "",
        context_snapshot: dict[str, Any] | None = None,
        error: str | None = None
    ) -> TrajectoryEntry:
        """Record a trajectory entry"""
        self._step_counter += 1

        entry = TrajectoryEntry(
            timestamp=datetime.now(),
            session_id=self.session_id,
            step_number=self._step_counter,
            state_before=state_before,
            state_after=state_after,
            event=event,
            tool_called=tool_called,
            tool_input=tool_input or {},
            tool_output_summary=tool_output_summary,
            reasoning=reasoning,
            context_snapshot=context_snapshot or {},
            goal_progress=self._goal_progress.copy(),
            error=error
        )

        self._entries.append(entry)
        self._write_entry(entry)

        return entry

    def _write_entry(self, entry: TrajectoryEntry) -> None:
        """Append entry to JSONL file"""
        with open(self.output_path, "a") as f:
            f.write(entry.model_dump_json() + "\n")

    def get_entries(self) -> list[TrajectoryEntry]:
        """Get all recorded entries"""
        return self._entries.copy()

    def get_entry(self, step: int) -> TrajectoryEntry | None:
        """Get entry by step number"""
        for entry in self._entries:
            if entry.step_number == step:
                return entry
        return None

    def get_last_entry(self) -> TrajectoryEntry | None:
        """Get the most recent entry"""
        return self._entries[-1] if self._entries else None

    def get_state_history(self) -> list[tuple[int, ExecutionState, ExecutionState]]:
        """Get history of state transitions"""
        return [
            (e.step_number, e.state_before, e.state_after)
            for e in self._entries
        ]

    def get_tool_calls(self) -> list[dict[str, Any]]:
        """Get all tool calls from trajectory"""
        return [
            {
                "step": e.step_number,
                "tool": e.tool_called,
                "input": e.tool_input,
                "output_summary": e.tool_output_summary,
                "error": e.error
            }
            for e in self._entries
            if e.tool_called
        ]

    def get_errors(self) -> list[dict[str, Any]]:
        """Get all errors from trajectory"""
        return [
            {
                "step": e.step_number,
                "state": e.state_after.value,
                "error": e.error
            }
            for e in self._entries
            if e.error
        ]

    def get_goal_progress_history(self) -> dict[str, list[tuple[int, float]]]:
        """Get progress history for each goal"""
        history: dict[str, list[tuple[int, float]]] = {
            goal_id: [] for goal_id in self._goal_definitions
        }

        for entry in self._entries:
            for goal_id, progress in entry.goal_progress.items():
                if goal_id in history:
                    history[goal_id].append((entry.step_number, progress))

        return history

    def export_summary(self) -> dict[str, Any]:
        """Export a summary of the trajectory"""
        return {
            "session_id": self.session_id,
            "total_steps": self._step_counter,
            "start_time": self._entries[0].timestamp.isoformat() if self._entries else None,
            "end_time": self._entries[-1].timestamp.isoformat() if self._entries else None,
            "final_state": self._entries[-1].state_after.value if self._entries else None,
            "tool_calls": len([e for e in self._entries if e.tool_called]),
            "errors": len([e for e in self._entries if e.error]),
            "goals": {
                goal_id: {
                    "description": desc,
                    "final_progress": self._goal_progress.get(goal_id, 0.0)
                }
                for goal_id, desc in self._goal_definitions.items()
            },
            "output_path": str(self.output_path)
        }

    @classmethod
    def load(cls, path: str | Path) -> "TrajectoryRecorder":
        """Load trajectory from JSONL file"""
        path = Path(path)
        entries = []

        with open(path) as f:
            for line in f:
                if line.strip():
                    entries.append(TrajectoryEntry.model_validate_json(line))

        if not entries:
            raise ValueError(f"No entries found in {path}")

        session_id = entries[0].session_id
        recorder = cls(session_id, path.parent)
        recorder._entries = entries
        recorder._step_counter = entries[-1].step_number

        for entry in entries:
            for goal_id, progress in entry.goal_progress.items():
                recorder._goal_progress[goal_id] = progress

        return recorder


class TrajectoryComparator:
    """Compares actual trajectory against expected trajectory"""

    def __init__(self, expected_steps: list[str]):
        self.expected_steps = expected_steps

    def compare(self, recorder: TrajectoryRecorder) -> ComparisonReport:
        """Compare recorded trajectory against expected"""
        comparisons = []

        actual_states = [e.state_after.value for e in recorder.get_entries()]
        actual_tools = [e.tool_called for e in recorder.get_entries() if e.tool_called]

        for i, expected in enumerate(self.expected_steps):
            expected_lower = expected.lower()

            found = False
            actual_match = ""
            for state in actual_states:
                if expected_lower in state.lower():
                    found = True
                    actual_match = state
                    break
            for tool in actual_tools:
                if expected_lower in tool.lower():
                    found = True
                    actual_match = tool
                    break

            comparisons.append(ComparisonDimension(
                dimension="trajectory",
                aspect=f"step_{i + 1}",
                sample_value=expected,
                actual_value=actual_match or "not found",
                aligned=found,
                gap_description="" if found else f"Expected step '{expected}' not found in trajectory",
                component_attribution="E" if not found else ""
            ))

        aligned_count = sum(1 for c in comparisons if c.aligned)
        score = aligned_count / len(comparisons) if comparisons else 0.0

        return ComparisonReport(
            trajectory_comparisons=comparisons,
            overall_alignment_score=score,
            summary=f"Trajectory alignment: {aligned_count}/{len(comparisons)} steps matched"
        )


def create_trajectory_recorder(session_id: str | None = None) -> TrajectoryRecorder:
    """Factory function to create a trajectory recorder"""
    if session_id is None:
        session_id = str(uuid.uuid4())
    return TrajectoryRecorder(session_id)
