"""State Store module for persisting creative writing state.

Provides scene-level snapshot and rollback capabilities, ensuring that
rewriting one scene does not affect other completed scenes.
"""

import json
import copy
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class WritingPhase(Enum):
    """Phases of the creative writing process."""
    INIT = "init"
    PLANNING = "planning"
    GENERATING = "generating"
    CHECKING = "checking"
    REVISING = "revising"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SceneState:
    """State of a single scene."""
    id: int
    summary: str
    content: str = ""
    word_count: int = 0
    revision_count: int = 0
    status: str = "pending"
    consistency_issues: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SceneState":
        return cls(**data)


@dataclass
class OutlineState:
    """State of the story outline."""
    beats: list[str] = field(default_factory=list)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    character_arcs: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OutlineState":
        return cls(**data)


@dataclass
class TaskSpec:
    """Specification for a writing task."""
    genre: str = ""
    premise: str = ""
    target_words: int = 1000
    pov: str = "third-person-limited"
    style_directives: list[str] = field(default_factory=list)
    structural_constraints: list[str] = field(default_factory=list)
    max_revisions: int = 3
    output_dir: str = "./output/"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSpec":
        return cls(**data)


@dataclass
class WritingState:
    """Complete state of a writing session."""
    task_spec: TaskSpec = field(default_factory=TaskSpec)
    phase: WritingPhase = WritingPhase.INIT
    outline: OutlineState = field(default_factory=OutlineState)
    scenes: dict[int, SceneState] = field(default_factory=dict)
    current_scene_id: int = 0
    total_word_count: int = 0
    global_revision_count: int = 0
    consistency_issues: list[str] = field(default_factory=list)
    style_anchor: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_spec": self.task_spec.to_dict(),
            "phase": self.phase.value,
            "outline": self.outline.to_dict(),
            "scenes": {str(k): v.to_dict() for k, v in self.scenes.items()},
            "current_scene_id": self.current_scene_id,
            "total_word_count": self.total_word_count,
            "global_revision_count": self.global_revision_count,
            "consistency_issues": self.consistency_issues,
            "style_anchor": self.style_anchor,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingState":
        return cls(
            task_spec=TaskSpec.from_dict(data.get("task_spec", {})),
            phase=WritingPhase(data.get("phase", "init")),
            outline=OutlineState.from_dict(data.get("outline", {})),
            scenes={int(k): SceneState.from_dict(v) for k, v in data.get("scenes", {}).items()},
            current_scene_id=data.get("current_scene_id", 0),
            total_word_count=data.get("total_word_count", 0),
            global_revision_count=data.get("global_revision_count", 0),
            consistency_issues=data.get("consistency_issues", []),
            style_anchor=data.get("style_anchor", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
        )


class StateStore:
    """Persistent state storage with snapshot and rollback support."""

    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.snapshots_dir = self.output_dir / ".snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._state: WritingState = WritingState()
        self._snapshot_index: dict[int, str] = {}

    @property
    def state(self) -> WritingState:
        return self._state

    def initialize(self, task_spec: TaskSpec) -> None:
        """Initialize state with a task specification."""
        self._state = WritingState(task_spec=task_spec)
        self._state.phase = WritingPhase.INIT

    def set_phase(self, phase: WritingPhase) -> None:
        """Transition to a new phase."""
        self._state.phase = phase
        self._state.timestamp = datetime.now().isoformat()

    def set_outline(self, outline: OutlineState) -> None:
        """Set the story outline."""
        self._state.outline = outline
        for i, scene_info in enumerate(outline.scenes):
            if i not in self._state.scenes:
                self._state.scenes[i] = SceneState(
                    id=i,
                    summary=scene_info.get("summary", ""),
                )

    def set_style_anchor(self, style_anchor: dict[str, Any]) -> None:
        """Set the style anchor for voice consistency."""
        self._state.style_anchor = style_anchor

    def update_scene(self, scene_id: int, content: str, word_count: int) -> None:
        """Update a scene's content."""
        if scene_id not in self._state.scenes:
            self._state.scenes[scene_id] = SceneState(id=scene_id, summary="")

        scene = self._state.scenes[scene_id]
        scene.content = content
        scene.word_count = word_count
        scene.status = "drafted"
        scene.timestamp = datetime.now().isoformat()

        self._recalculate_word_count()

    def mark_scene_complete(self, scene_id: int) -> None:
        """Mark a scene as complete after consistency checks pass."""
        if scene_id in self._state.scenes:
            self._state.scenes[scene_id].status = "complete"

    def add_scene_revision(self, scene_id: int) -> None:
        """Increment revision count for a scene."""
        if scene_id in self._state.scenes:
            self._state.scenes[scene_id].revision_count += 1
            self._state.global_revision_count += 1

    def set_scene_issues(self, scene_id: int, issues: list[str]) -> None:
        """Set consistency issues for a scene."""
        if scene_id in self._state.scenes:
            self._state.scenes[scene_id].consistency_issues = issues

    def add_global_issue(self, issue: str) -> None:
        """Add a global consistency issue."""
        self._state.consistency_issues.append(issue)

    def get_scene(self, scene_id: int) -> SceneState | None:
        """Get a scene by ID."""
        return self._state.scenes.get(scene_id)

    def get_completed_scenes_content(self) -> str:
        """Get concatenated content of all completed/drafted scenes."""
        contents = []
        for scene_id in sorted(self._state.scenes.keys()):
            scene = self._state.scenes[scene_id]
            if scene.content:
                contents.append(scene.content)
        return "\n\n---\n\n".join(contents)

    def get_prior_context(self, scene_id: int, max_scenes: int = 2) -> str:
        """Get content of preceding scenes for context injection."""
        prior_ids = [i for i in range(max(0, scene_id - max_scenes), scene_id)]
        contents = []
        for sid in prior_ids:
            scene = self._state.scenes.get(sid)
            if scene and scene.content:
                contents.append(scene.content)
        return "\n\n".join(contents)

    def snapshot(self, scene_id: int) -> str:
        """Create a snapshot at the current scene boundary."""
        snapshot_name = f"scene_{scene_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        snapshot_path = self.snapshots_dir / snapshot_name

        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)

        self._snapshot_index[scene_id] = str(snapshot_path)
        return str(snapshot_path)

    def rollback(self, scene_id: int) -> bool:
        """Rollback to state before the specified scene was written.

        This restores to the snapshot taken after the previous scene,
        effectively undoing the current scene without affecting prior scenes.
        """
        target_scene = scene_id - 1
        if target_scene < 0:
            self._reset_to_pre_generation()
            return True

        if target_scene in self._snapshot_index:
            snapshot_path = Path(self._snapshot_index[target_scene])
            if snapshot_path.exists():
                with open(snapshot_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._state = WritingState.from_dict(data)
                return True

        self._partial_rollback(scene_id)
        return True

    def _partial_rollback(self, scene_id: int) -> None:
        """Rollback just the specified scene without full state restore."""
        if scene_id in self._state.scenes:
            scene = self._state.scenes[scene_id]
            scene.content = ""
            scene.word_count = 0
            scene.status = "pending"
            scene.consistency_issues = []
            self._recalculate_word_count()

    def _reset_to_pre_generation(self) -> None:
        """Reset to state before any generation (keep outline)."""
        for scene in self._state.scenes.values():
            scene.content = ""
            scene.word_count = 0
            scene.status = "pending"
            scene.revision_count = 0
            scene.consistency_issues = []
        self._state.total_word_count = 0
        self._state.phase = WritingPhase.PLANNING

    def _recalculate_word_count(self) -> None:
        """Recalculate total word count from all scenes."""
        self._state.total_word_count = sum(
            scene.word_count for scene in self._state.scenes.values()
        )

    def save(self) -> None:
        """Save current state to disk."""
        state_path = self.output_dir / "writing_state.json"
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self) -> bool:
        """Load state from disk if exists."""
        state_path = self.output_dir / "writing_state.json"
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._state = WritingState.from_dict(data)
            return True
        return False

    def get_manuscript_text(self) -> str:
        """Get the full manuscript text in scene order."""
        contents = []
        for scene_id in sorted(self._state.scenes.keys()):
            scene = self._state.scenes[scene_id]
            if scene.content:
                contents.append(scene.content)
        return "\n\n".join(contents)
