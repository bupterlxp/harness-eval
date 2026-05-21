"""State Store (S) - Task state persistence with checkpoint/resume support.

Maintains step dependencies and state, supports resuming from last successful step.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepState:
    """State for a single operation step."""
    step_id: int
    description: str
    status: StepStatus = StepStatus.PENDING
    action_type: str | None = None
    target_element: str | None = None
    action_params: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    recovery_action: str | None = None
    retry_count: int = 0
    screenshot_path: str | None = None
    url_before: str | None = None
    url_after: str | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepState":
        data = data.copy()
        data["status"] = StepStatus(data["status"])
        return cls(**data)


@dataclass
class TaskState:
    """Overall task state tracking."""
    task_id: str
    target_url: str
    task_description: str
    status: str = "in_progress"
    current_step: int = 0
    max_steps: int = 50
    steps: list[StepState] = field(default_factory=list)
    extracted_data: dict[str, Any] = field(default_factory=dict)
    screenshots: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [s.to_dict() if isinstance(s, StepState) else s for s in self.steps]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        data = data.copy()
        data["steps"] = [StepState.from_dict(s) for s in data.get("steps", [])]
        return cls(**data)


class StateStore:
    """Manages task state persistence with checkpoint/resume support."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.output_dir / "task_state.json"
        self._task_state: TaskState | None = None

    def initialize_task(
        self,
        task_id: str,
        target_url: str,
        task_description: str,
        max_steps: int = 50
    ) -> TaskState:
        """Initialize a new task state."""
        self._task_state = TaskState(
            task_id=task_id,
            target_url=target_url,
            task_description=task_description,
            max_steps=max_steps
        )
        self._save()
        return self._task_state

    def load_or_create(
        self,
        task_id: str,
        target_url: str,
        task_description: str,
        max_steps: int = 50
    ) -> tuple[TaskState, bool]:
        """Load existing state or create new one. Returns (state, resumed)."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                self._task_state = TaskState.from_dict(data)
                if self._task_state.status == "in_progress":
                    return self._task_state, True
            except (json.JSONDecodeError, KeyError):
                pass

        return self.initialize_task(task_id, target_url, task_description, max_steps), False

    @property
    def task_state(self) -> TaskState:
        if self._task_state is None:
            raise RuntimeError("Task state not initialized")
        return self._task_state

    def get_last_successful_step(self) -> int:
        """Get the index of the last successfully completed step."""
        last_successful = -1
        for i, step in enumerate(self.task_state.steps):
            if step.status == StepStatus.COMPLETED:
                last_successful = i
        return last_successful

    def get_resume_point(self) -> int:
        """Get the step index to resume from after failure."""
        last_successful = self.get_last_successful_step()
        return last_successful + 1

    def add_step(self, step: StepState) -> None:
        """Add a new step to the task."""
        self.task_state.steps.append(step)
        self.task_state.current_step = len(self.task_state.steps) - 1
        self._update_timestamp()
        self._save()

    def update_step(self, step_id: int, **updates) -> None:
        """Update a step's state."""
        for step in self.task_state.steps:
            if step.step_id == step_id:
                for key, value in updates.items():
                    if hasattr(step, key):
                        setattr(step, key, value)
                break
        self._update_timestamp()
        self._save()

    def mark_step_completed(self, step_id: int, result: dict[str, Any] | None = None) -> None:
        """Mark a step as completed."""
        self.update_step(
            step_id,
            status=StepStatus.COMPLETED,
            result=result,
            timestamp_end=datetime.utcnow().isoformat()
        )

    def mark_step_failed(self, step_id: int, error: str, recovery: str) -> None:
        """Mark a step as failed with error info."""
        self.update_step(
            step_id,
            status=StepStatus.FAILED,
            error=error,
            recovery_action=recovery,
            timestamp_end=datetime.utcnow().isoformat()
        )
        self.task_state.errors.append({
            "step": step_id,
            "error": error,
            "recovery": recovery
        })
        self._save()

    def mark_step_skipped(self, step_id: int, reason: str) -> None:
        """Mark a step as skipped."""
        self.update_step(
            step_id,
            status=StepStatus.SKIPPED,
            error=reason,
            recovery_action="skipped",
            timestamp_end=datetime.utcnow().isoformat()
        )

    def increment_retry(self, step_id: int) -> int:
        """Increment retry count and return new count."""
        for step in self.task_state.steps:
            if step.step_id == step_id:
                step.retry_count += 1
                self._save()
                return step.retry_count
        return 0

    def add_screenshot(self, path: str) -> None:
        """Record a screenshot path."""
        self.task_state.screenshots.append(path)
        self._save()

    def add_download(self, path: str) -> None:
        """Record a download file path."""
        self.task_state.downloads.append(path)
        self._save()

    def update_extracted_data(self, data: dict[str, Any]) -> None:
        """Merge new extracted data into task state."""
        self.task_state.extracted_data.update(data)
        self._save()

    def set_task_status(self, status: str) -> None:
        """Set overall task status."""
        self.task_state.status = status
        self._update_timestamp()
        self._save()

    def _update_timestamp(self) -> None:
        self.task_state.updated_at = datetime.utcnow().isoformat()

    def _save(self) -> None:
        """Persist state to file."""
        with open(self.state_file, "w") as f:
            json.dump(self.task_state.to_dict(), f, indent=2)

    def get_result(self) -> dict[str, Any]:
        """Generate the final result object."""
        return {
            "status": self.task_state.status,
            "extracted_data": self.task_state.extracted_data,
            "screenshots": self.task_state.screenshots,
            "downloads": self.task_state.downloads,
            "errors": self.task_state.errors,
            "trajectory": str(self.output_dir / "trajectory.jsonl"),
        }

    def save_result(self) -> str:
        """Save final result to result.json and return path."""
        result_path = self.output_dir / "result.json"
        with open(result_path, "w") as f:
            json.dump(self.get_result(), f, indent=2)
        return str(result_path)
