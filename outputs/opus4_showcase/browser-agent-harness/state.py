"""State Store (S) — state persistence and checkpoint recovery.

Manages snapshots containing enough info to resume from any checkpoint.
Tracks task memory, plan state, extracted data, and browser state.
"""

import json
import time
import copy
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class SubGoalStatus(str, Enum):
    PENDING = "pending"
    CURRENT = "current"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class SubGoal:
    description: str
    status: SubGoalStatus = SubGoalStatus.PENDING
    result_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "status": self.status.value,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubGoal":
        return cls(
            description=data["description"],
            status=SubGoalStatus(data["status"]),
            result_summary=data.get("result_summary", ""),
        )


@dataclass
class Plan:
    sub_goals: list[SubGoal] = field(default_factory=list)

    def current_goal(self) -> SubGoal | None:
        for g in self.sub_goals:
            if g.status == SubGoalStatus.CURRENT:
                return g
        return None

    def advance(self, result_summary: str = "") -> SubGoal | None:
        """Mark current as done and advance to next pending."""
        current = self.current_goal()
        if current:
            current.status = SubGoalStatus.DONE
            current.result_summary = result_summary
        for g in self.sub_goals:
            if g.status == SubGoalStatus.PENDING:
                g.status = SubGoalStatus.CURRENT
                return g
        return None

    def skip_current(self, reason: str = "") -> SubGoal | None:
        """Skip current goal and move to next."""
        current = self.current_goal()
        if current:
            current.status = SubGoalStatus.SKIPPED
            current.result_summary = reason
        for g in self.sub_goals:
            if g.status == SubGoalStatus.PENDING:
                g.status = SubGoalStatus.CURRENT
                return g
        return None

    def is_complete(self) -> bool:
        return all(
            g.status in (SubGoalStatus.DONE, SubGoalStatus.SKIPPED)
            for g in self.sub_goals
        )

    def progress_str(self) -> str:
        done = sum(1 for g in self.sub_goals if g.status == SubGoalStatus.DONE)
        total = len(self.sub_goals)
        return f"{done}/{total} sub-goals completed"

    def to_dict(self) -> dict[str, Any]:
        return {"sub_goals": [g.to_dict() for g in self.sub_goals]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        return cls(
            sub_goals=[SubGoal.from_dict(g) for g in data.get("sub_goals", [])]
        )


@dataclass
class TabInfo:
    tab_id: str
    url: str
    title: str
    is_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TabInfo":
        return cls(**data)


@dataclass
class StepMemory:
    """Per-step structured self-evaluation."""

    step_number: int
    previous_action_success: bool
    memory_summary: str
    next_goal: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepMemory":
        return cls(**data)


@dataclass
class ActionRecord:
    """Record of an action taken and its repeated count."""

    action_type: str
    action_params: dict[str, Any]
    count: int = 1

    def matches(self, action_type: str, action_params: dict[str, Any]) -> bool:
        return self.action_type == action_type and self.action_params == action_params


@dataclass
class StagnationTracker:
    """Track repeated actions and page fingerprint stagnation."""

    recent_actions: list[ActionRecord] = field(default_factory=list)
    page_fingerprints: list[str] = field(default_factory=list)
    consecutive_failures: int = 0
    same_element_failures: dict[str, int] = field(default_factory=dict)

    def record_action(self, action_type: str, action_params: dict[str, Any]) -> int:
        """Record an action and return its repetition count."""
        if self.recent_actions and self.recent_actions[-1].matches(
            action_type, action_params
        ):
            self.recent_actions[-1].count += 1
            return self.recent_actions[-1].count
        self.recent_actions.append(
            ActionRecord(action_type=action_type, action_params=action_params, count=1)
        )
        if len(self.recent_actions) > 50:
            self.recent_actions = self.recent_actions[-50:]
        return 1

    def record_page_fingerprint(self, fingerprint: str) -> int:
        """Record page fingerprint and return consecutive same-fingerprint count."""
        self.page_fingerprints.append(fingerprint)
        if len(self.page_fingerprints) > 20:
            self.page_fingerprints = self.page_fingerprints[-20:]
        count = 0
        for fp in reversed(self.page_fingerprints):
            if fp == fingerprint:
                count += 1
            else:
                break
        return count

    def record_failure(self, element_id: str = "") -> int:
        """Record a failure and return consecutive failure count."""
        self.consecutive_failures += 1
        if element_id:
            self.same_element_failures[element_id] = (
                self.same_element_failures.get(element_id, 0) + 1
            )
            return self.same_element_failures[element_id]
        return self.consecutive_failures

    def reset_failures(self) -> None:
        self.consecutive_failures = 0

    def get_repetition_warning(self, count: int) -> str | None:
        if count >= 12:
            return "CRITICAL: Same action repeated 12+ times. You MUST change strategy completely."
        elif count >= 8:
            return "STRONG WARNING: Same action repeated 8+ times. Try a different approach."
        elif count >= 5:
            return "WARNING: Same action repeated 5+ times. Consider alternative approach."
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recent_actions": [
                {"action_type": a.action_type, "action_params": a.action_params, "count": a.count}
                for a in self.recent_actions
            ],
            "page_fingerprints": self.page_fingerprints,
            "consecutive_failures": self.consecutive_failures,
            "same_element_failures": self.same_element_failures,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StagnationTracker":
        tracker = cls()
        tracker.recent_actions = [
            ActionRecord(
                action_type=a["action_type"],
                action_params=a["action_params"],
                count=a["count"],
            )
            for a in data.get("recent_actions", [])
        ]
        tracker.page_fingerprints = data.get("page_fingerprints", [])
        tracker.consecutive_failures = data.get("consecutive_failures", 0)
        tracker.same_element_failures = data.get("same_element_failures", {})
        return tracker


@dataclass
class TaskState:
    """Complete task state — serializable for checkpointing."""

    task_prompt: str
    step_number: int = 0
    plan: Plan = field(default_factory=Plan)
    tabs: list[TabInfo] = field(default_factory=list)
    extracted_data: list[dict[str, Any]] = field(default_factory=list)
    step_memories: list[StepMemory] = field(default_factory=list)
    stagnation: StagnationTracker = field(default_factory=StagnationTracker)
    rolling_summary: str = ""
    current_url: str = ""
    status: str = "running"
    error_message: str = ""
    start_time: float = field(default_factory=time.time)
    last_checkpoint_step: int = 0

    def budget_fraction(self, max_steps: int) -> float:
        """Return fraction of budget consumed (0.0 to 1.0)."""
        if max_steps <= 0:
            return 1.0
        return self.step_number / max_steps

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_prompt": self.task_prompt,
            "step_number": self.step_number,
            "plan": self.plan.to_dict(),
            "tabs": [t.to_dict() for t in self.tabs],
            "extracted_data": self.extracted_data,
            "step_memories": [m.to_dict() for m in self.step_memories],
            "stagnation": self.stagnation.to_dict(),
            "rolling_summary": self.rolling_summary,
            "current_url": self.current_url,
            "status": self.status,
            "error_message": self.error_message,
            "start_time": self.start_time,
            "last_checkpoint_step": self.last_checkpoint_step,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        ts = cls(task_prompt=data["task_prompt"])
        ts.step_number = data.get("step_number", 0)
        ts.plan = Plan.from_dict(data.get("plan", {}))
        ts.tabs = [TabInfo.from_dict(t) for t in data.get("tabs", [])]
        ts.extracted_data = data.get("extracted_data", [])
        ts.step_memories = [
            StepMemory.from_dict(m) for m in data.get("step_memories", [])
        ]
        ts.stagnation = StagnationTracker.from_dict(data.get("stagnation", {}))
        ts.rolling_summary = data.get("rolling_summary", "")
        ts.current_url = data.get("current_url", "")
        ts.status = data.get("status", "running")
        ts.error_message = data.get("error_message", "")
        ts.start_time = data.get("start_time", time.time())
        ts.last_checkpoint_step = data.get("last_checkpoint_step", 0)
        return ts


class StateStore:
    """Manages state persistence and checkpoint recovery."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.checkpoint_dir = output_dir / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._state: TaskState | None = None

    @property
    def state(self) -> TaskState:
        if self._state is None:
            raise RuntimeError("State not initialized. Call init_state or load_checkpoint first.")
        return self._state

    def init_state(self, task_prompt: str) -> TaskState:
        """Initialize fresh state for a new task."""
        self._state = TaskState(task_prompt=task_prompt)
        return self._state

    def save_checkpoint(self) -> Path:
        """Save current state to a checkpoint file."""
        ts = self.state
        ts.last_checkpoint_step = ts.step_number
        checkpoint_path = self.checkpoint_dir / f"checkpoint_step_{ts.step_number:04d}.json"
        with open(checkpoint_path, "w") as f:
            json.dump(ts.to_dict(), f, indent=2)
        # Also save a "latest" symlink-like file
        latest_path = self.checkpoint_dir / "latest.json"
        with open(latest_path, "w") as f:
            json.dump(ts.to_dict(), f, indent=2)
        return checkpoint_path

    def load_checkpoint(self, checkpoint_path: Path) -> TaskState:
        """Load state from a checkpoint file."""
        with open(checkpoint_path, "r") as f:
            data = json.load(f)
        self._state = TaskState.from_dict(data)
        return self._state

    def update_tabs(self, tabs: list[TabInfo]) -> None:
        """Update tab information."""
        self.state.tabs = tabs

    def update_url(self, url: str) -> None:
        """Update current URL."""
        self.state.current_url = url

    def add_extracted_data(self, data: dict[str, Any]) -> None:
        """Add extracted data to accumulator."""
        self.state.extracted_data.append(data)

    def add_step_memory(self, memory: StepMemory) -> None:
        """Add step memory, keeping only recent entries."""
        self.state.step_memories.append(memory)
        if len(self.state.step_memories) > 20:
            self.state.step_memories = self.state.step_memories[-20:]

    def update_rolling_summary(self, summary: str) -> None:
        """Update rolling summary of completed actions."""
        self.state.rolling_summary = summary

    def increment_step(self) -> int:
        """Increment and return new step number."""
        self.state.step_number += 1
        return self.state.step_number

    def set_plan(self, sub_goals: list[str]) -> None:
        """Set the task plan with sub-goals."""
        goals = [SubGoal(description=desc) for desc in sub_goals]
        if goals:
            goals[0].status = SubGoalStatus.CURRENT
        self.state.plan = Plan(sub_goals=goals)

    def mark_complete(self, status: str = "success", error: str = "") -> None:
        """Mark task as complete."""
        self.state.status = status
        self.state.error_message = error
