"""State Store — state persistence and checkpoint recovery.

Implements snapshot-based state management so the execution engine can be
paused and resumed from any checkpoint. Each snapshot contains enough
information to fully reconstruct the agent's state.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ExecutionSnapshot:
    """Complete state snapshot for checkpoint recovery."""

    # Execution state
    current_state: str  # FSM state name
    step_count: int
    prompt: str

    # Conversation history (messages sent to LLM)
    messages: list[dict[str, Any]]

    # Plan state
    plan: list[dict[str, Any]]  # sub-tasks with status
    current_task_index: int

    # Artifacts registry
    artifacts: list[dict[str, Any]]

    # Namespace variable names (we cannot serialize all objects, but track what exists)
    namespace_vars: list[str]

    # Progress summary
    progress_summary: str

    # Findings accumulated
    findings: list[str]

    # Timestamp
    timestamp: float = field(default_factory=time.time)

    # Step observations (compressed)
    step_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionSnapshot":
        return cls(**data)


class StateStore:
    """Manages state persistence and checkpoint recovery.

    Checkpoints are stored as JSON files in the checkpoint directory,
    indexed by step number and timestamp.
    """

    def __init__(self, checkpoint_dir: Path) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._checkpoints: list[Path] = []

    def save_checkpoint(self, snapshot: ExecutionSnapshot) -> Path:
        """Save a checkpoint snapshot to disk.

        Returns the path to the saved checkpoint file.
        """
        filename = f"checkpoint_step{snapshot.step_count}_{int(snapshot.timestamp)}.json"
        path = self.checkpoint_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, indent=2, ensure_ascii=False)
        self._checkpoints.append(path)
        self._prune_old_checkpoints(keep=5)
        return path

    def load_checkpoint(self, path: str | Path) -> ExecutionSnapshot:
        """Load a checkpoint from disk."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ExecutionSnapshot.from_dict(data)

    def get_latest_checkpoint(self) -> ExecutionSnapshot | None:
        """Get the most recent checkpoint, if any."""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        if not checkpoints:
            return None
        return self.load_checkpoint(checkpoints[-1])

    def list_checkpoints(self) -> list[Path]:
        """List all available checkpoint files."""
        return sorted(self.checkpoint_dir.glob("checkpoint_*.json"))

    def _prune_old_checkpoints(self, keep: int = 5) -> None:
        """Keep only the N most recent checkpoints."""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        if len(checkpoints) > keep:
            for old in checkpoints[:-keep]:
                old.unlink(missing_ok=True)
