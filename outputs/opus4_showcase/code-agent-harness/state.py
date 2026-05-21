"""State Store — state persistence and checkpoint recovery."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class AgentPhase(str, Enum):
    """High-level phase of the agent execution."""

    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"
    STUCK = "stuck"
    ERROR = "error"


class ResultStatus(str, Enum):
    """Final result status of the agent run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class StepRecord:
    """A single step in the agent's execution."""

    step_number: int
    thought: str
    action: str
    action_input: dict[str, Any]
    observation: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepRecord:
        return cls(**data)


@dataclass
class AgentState:
    """Complete agent state that can be persisted and restored."""

    phase: AgentPhase = AgentPhase.IDLE
    current_step: int = 0
    max_steps: int = 50
    prompt: str = ""
    workspace: str = ""
    history: list[StepRecord] = field(default_factory=list)
    repeated_actions: list[dict[str, Any]] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    context_summary: str = ""
    error_message: str = ""
    result_status: ResultStatus | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "phase": self.phase.value,
            "current_step": self.current_step,
            "max_steps": self.max_steps,
            "prompt": self.prompt,
            "workspace": self.workspace,
            "history": [s.to_dict() for s in self.history],
            "repeated_actions": self.repeated_actions,
            "files_modified": self.files_modified,
            "context_summary": self.context_summary,
            "error_message": self.error_message,
            "result_status": self.result_status.value if self.result_status else None,
            "metadata": self.metadata,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentState:
        state = cls()
        state.phase = AgentPhase(data["phase"])
        state.current_step = data["current_step"]
        state.max_steps = data["max_steps"]
        state.prompt = data["prompt"]
        state.workspace = data["workspace"]
        state.history = [StepRecord.from_dict(s) for s in data.get("history", [])]
        state.repeated_actions = data.get("repeated_actions", [])
        state.files_modified = data.get("files_modified", [])
        state.context_summary = data.get("context_summary", "")
        state.error_message = data.get("error_message", "")
        rs = data.get("result_status")
        state.result_status = ResultStatus(rs) if rs else None
        state.metadata = data.get("metadata", {})
        return state


class StateStore:
    """Manages state persistence and checkpoint recovery."""

    def __init__(self, checkpoint_dir: Path | str) -> None:
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._state = AgentState()

    @property
    def state(self) -> AgentState:
        return self._state

    @state.setter
    def state(self, value: AgentState) -> None:
        self._state = value

    def save_checkpoint(self, label: str | None = None) -> Path:
        """Save current state as a checkpoint file. Returns the checkpoint path."""
        if label is None:
            label = f"step_{self._state.current_step}"
        filename = f"checkpoint_{label}_{int(time.time())}.json"
        path = self.checkpoint_dir / filename
        with open(path, "w") as f:
            json.dump(self._state.to_dict(), f, indent=2)
        return path

    def load_checkpoint(self, path: Path | str) -> AgentState:
        """Load state from a checkpoint file."""
        path = Path(path)
        with open(path, "r") as f:
            data = json.load(f)
        self._state = AgentState.from_dict(data)
        return self._state

    def get_latest_checkpoint(self) -> Path | None:
        """Find the most recent checkpoint file."""
        checkpoints = sorted(
            self.checkpoint_dir.glob("checkpoint_*.json"),
            key=lambda p: p.stat().st_mtime,
        )
        return checkpoints[-1] if checkpoints else None

    def record_step(self, step: StepRecord) -> None:
        """Add a step to the state history."""
        self._state.history.append(step)
        self._state.current_step = step.step_number

    def detect_doom_loop(self, threshold_same_action: int = 3, threshold_same_error: int = 4) -> str | None:
        """
        Detect doom loops in recent history.
        Returns a string describing the issue if a doom loop is found, else None.
        """
        if len(self._state.history) < threshold_same_action:
            return None

        recent = self._state.history[-threshold_same_action:]

        # Check for repeated same tool + params
        action_keys = [(s.action, json.dumps(s.action_input, sort_keys=True)) for s in recent]
        if len(set(action_keys)) == 1:
            return f"doom_loop_same_action: repeated '{recent[0].action}' with same params {threshold_same_action} times"

        # Check for repeated same action + error pattern
        if len(self._state.history) >= threshold_same_error:
            recent_errors = self._state.history[-threshold_same_error:]
            error_keys = [
                (s.action, s.observation[:200]) for s in recent_errors
                if "error" in s.observation.lower() or "Error" in s.observation
            ]
            if len(error_keys) == threshold_same_error and len(set(error_keys)) == 1:
                return f"doom_loop_same_error: action '{recent_errors[0].action}' producing same error {threshold_same_error} times"

        return None

    def mark_file_modified(self, filepath: str) -> None:
        """Track a file that has been modified."""
        if filepath not in self._state.files_modified:
            self._state.files_modified.append(filepath)
