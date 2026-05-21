"""State Store — state persistence and checkpoint recovery.

Manages three-layer memory system (Working, Episodic, Semantic)
and provides checkpoint/resume capabilities.
"""

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class CharacterState:
    """Tracks what a character knows and their current state."""
    name: str
    knowledge: list[str] = field(default_factory=list)
    relationships: dict[str, str] = field(default_factory=dict)
    emotional_state: str = ""
    location: str = ""
    goals: list[str] = field(default_factory=list)
    last_seen_chapter: int = 0


@dataclass
class WorldRule:
    """A hard constraint about the world."""
    rule_id: str
    description: str
    category: str  # "physics", "magic", "social", "temporal"
    active: bool = True


@dataclass
class TimelineEvent:
    """An event on the story timeline."""
    event_id: str
    description: str
    timestamp_story: str  # in-story time
    chapter: int
    characters_involved: list[str] = field(default_factory=list)
    thread: str = "main"


@dataclass
class WorkingMemory:
    """Current chapter/scene context — high priority, small capacity."""
    current_chapter: int = 0
    current_scene: int = 0
    scene_context: str = ""
    active_characters: list[str] = field(default_factory=list)
    immediate_goals: list[str] = field(default_factory=list)
    pov_character: str = ""
    tone: str = ""
    pending_hooks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkingMemory":
        return cls(**data)


@dataclass
class EpisodicMemory:
    """Recent events — medium priority, medium capacity."""
    recent_scenes: list[dict[str, Any]] = field(default_factory=list)
    max_episodes: int = 20

    def add_episode(self, scene_summary: str, chapter: int, scene: int,
                    characters: list[str], key_events: list[str]) -> None:
        episode = {
            "summary": scene_summary,
            "chapter": chapter,
            "scene": scene,
            "characters": characters,
            "key_events": key_events,
            "timestamp": time.time(),
        }
        self.recent_scenes.append(episode)
        if len(self.recent_scenes) > self.max_episodes:
            self.recent_scenes = self.recent_scenes[-self.max_episodes:]

    def get_recent(self, n: int = 5) -> list[dict[str, Any]]:
        return self.recent_scenes[-n:]

    def to_dict(self) -> dict[str, Any]:
        return {"recent_scenes": self.recent_scenes, "max_episodes": self.max_episodes}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpisodicMemory":
        mem = cls(max_episodes=data.get("max_episodes", 20))
        mem.recent_scenes = data.get("recent_scenes", [])
        return mem


@dataclass
class SemanticMemory:
    """Long-term knowledge — lower priority, large capacity."""
    characters: dict[str, CharacterState] = field(default_factory=dict)
    world_rules: list[WorldRule] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    plot_threads: dict[str, list[str]] = field(default_factory=dict)
    open_loops: list[str] = field(default_factory=list)
    resolved_loops: list[str] = field(default_factory=list)
    world_description: str = ""
    themes: list[str] = field(default_factory=list)

    def add_character(self, name: str) -> CharacterState:
        if name not in self.characters:
            self.characters[name] = CharacterState(name=name)
        return self.characters[name]

    def add_world_rule(self, rule_id: str, description: str, category: str) -> None:
        rule = WorldRule(rule_id=rule_id, description=description, category=category)
        self.world_rules.append(rule)

    def add_timeline_event(self, event_id: str, description: str,
                           timestamp_story: str, chapter: int,
                           characters: list[str], thread: str = "main") -> None:
        event = TimelineEvent(
            event_id=event_id, description=description,
            timestamp_story=timestamp_story, chapter=chapter,
            characters_involved=characters, thread=thread,
        )
        self.timeline.append(event)

    def get_character_knowledge(self, character_name: str) -> list[str]:
        char = self.characters.get(character_name)
        return char.knowledge if char else []

    def check_timeline_consistency(self, chapter: int, thread: str) -> list[TimelineEvent]:
        """Get events for a thread up to a chapter for consistency checks."""
        return [
            e for e in self.timeline
            if e.thread == thread and e.chapter <= chapter
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "characters": {k: asdict(v) for k, v in self.characters.items()},
            "world_rules": [asdict(r) for r in self.world_rules],
            "timeline": [asdict(e) for e in self.timeline],
            "plot_threads": self.plot_threads,
            "open_loops": self.open_loops,
            "resolved_loops": self.resolved_loops,
            "world_description": self.world_description,
            "themes": self.themes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticMemory":
        mem = cls()
        for name, cdata in data.get("characters", {}).items():
            mem.characters[name] = CharacterState(**cdata)
        for rdata in data.get("world_rules", []):
            mem.world_rules.append(WorldRule(**rdata))
        for edata in data.get("timeline", []):
            mem.timeline.append(TimelineEvent(**edata))
        mem.plot_threads = data.get("plot_threads", {})
        mem.open_loops = data.get("open_loops", [])
        mem.resolved_loops = data.get("resolved_loops", [])
        mem.world_description = data.get("world_description", "")
        mem.themes = data.get("themes", [])
        return mem


@dataclass
class WritingState:
    """Complete state for the writing agent."""
    # FSM state
    current_phase: str = "INIT"
    iteration: int = 0
    revision_count: int = 0

    # Task metadata
    task_prompt: str = ""
    mode: str = ""  # "longform" or "shortform"
    genre: str = ""
    style_notes: str = ""

    # Planning artifacts
    master_outline: str = ""
    volume_outlines: list[str] = field(default_factory=list)
    chapter_outlines: list[str] = field(default_factory=list)

    # Draft artifacts
    drafts: list[str] = field(default_factory=list)
    current_draft: str = ""
    final_output: str = ""

    # Style control
    voice_fingerprint: str = ""
    forbidden_patterns: list[str] = field(default_factory=list)
    pattern_alternatives: dict[str, str] = field(default_factory=dict)

    # Critique results
    critique_scores: dict[str, float] = field(default_factory=dict)
    revision_briefs: list[str] = field(default_factory=list)
    score_history: list[dict[str, float]] = field(default_factory=list)

    # Memory layers
    working_memory: WorkingMemory = field(default_factory=WorkingMemory)
    episodic_memory: EpisodicMemory = field(default_factory=EpisodicMemory)
    semantic_memory: SemanticMemory = field(default_factory=SemanticMemory)

    # Shortform-specific
    scenario_analysis: str = ""
    emotional_map: str = ""
    mental_models: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_phase": self.current_phase,
            "iteration": self.iteration,
            "revision_count": self.revision_count,
            "task_prompt": self.task_prompt,
            "mode": self.mode,
            "genre": self.genre,
            "style_notes": self.style_notes,
            "master_outline": self.master_outline,
            "volume_outlines": self.volume_outlines,
            "chapter_outlines": self.chapter_outlines,
            "drafts": self.drafts,
            "current_draft": self.current_draft,
            "final_output": self.final_output,
            "voice_fingerprint": self.voice_fingerprint,
            "forbidden_patterns": self.forbidden_patterns,
            "pattern_alternatives": self.pattern_alternatives,
            "critique_scores": self.critique_scores,
            "revision_briefs": self.revision_briefs,
            "score_history": self.score_history,
            "working_memory": self.working_memory.to_dict(),
            "episodic_memory": self.episodic_memory.to_dict(),
            "semantic_memory": self.semantic_memory.to_dict(),
            "scenario_analysis": self.scenario_analysis,
            "emotional_map": self.emotional_map,
            "mental_models": self.mental_models,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WritingState":
        ws = cls()
        ws.current_phase = data.get("current_phase", "INIT")
        ws.iteration = data.get("iteration", 0)
        ws.revision_count = data.get("revision_count", 0)
        ws.task_prompt = data.get("task_prompt", "")
        ws.mode = data.get("mode", "")
        ws.genre = data.get("genre", "")
        ws.style_notes = data.get("style_notes", "")
        ws.master_outline = data.get("master_outline", "")
        ws.volume_outlines = data.get("volume_outlines", [])
        ws.chapter_outlines = data.get("chapter_outlines", [])
        ws.drafts = data.get("drafts", [])
        ws.current_draft = data.get("current_draft", "")
        ws.final_output = data.get("final_output", "")
        ws.voice_fingerprint = data.get("voice_fingerprint", "")
        ws.forbidden_patterns = data.get("forbidden_patterns", [])
        ws.pattern_alternatives = data.get("pattern_alternatives", {})
        ws.critique_scores = data.get("critique_scores", {})
        ws.revision_briefs = data.get("revision_briefs", [])
        ws.score_history = data.get("score_history", [])
        ws.working_memory = WorkingMemory.from_dict(data.get("working_memory", {}))
        ws.episodic_memory = EpisodicMemory.from_dict(data.get("episodic_memory", {}))
        ws.semantic_memory = SemanticMemory.from_dict(data.get("semantic_memory", {}))
        ws.scenario_analysis = data.get("scenario_analysis", "")
        ws.emotional_map = data.get("emotional_map", "")
        ws.mental_models = data.get("mental_models", {})
        return ws


class StateStore:
    """Manages state persistence and checkpoint recovery."""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.state = WritingState()
        self._checkpoint_counter = 0

    def get_state(self) -> WritingState:
        return self.state

    def set_state(self, new_state: WritingState) -> None:
        self.state = new_state

    def save_checkpoint(self, label: str = "") -> Path:
        """Save current state to a checkpoint file."""
        self._checkpoint_counter += 1
        ts = int(time.time())
        label_part = f"_{label}" if label else ""
        filename = f"checkpoint_{self._checkpoint_counter:04d}_{ts}{label_part}.json"
        path = self.checkpoint_dir / filename

        snapshot = {
            "version": 1,
            "timestamp": ts,
            "counter": self._checkpoint_counter,
            "label": label,
            "state": self.state.to_dict(),
            "checksum": self._compute_checksum(self.state.to_dict()),
        }
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return path

    def load_checkpoint(self, path: Path) -> WritingState:
        """Load state from a checkpoint file."""
        data = json.loads(path.read_text())

        # Verify checksum
        stored_checksum = data.get("checksum", "")
        computed_checksum = self._compute_checksum(data["state"])
        if stored_checksum and stored_checksum != computed_checksum:
            raise ValueError(f"Checkpoint checksum mismatch: {path}")

        self.state = WritingState.from_dict(data["state"])
        self._checkpoint_counter = data.get("counter", 0)
        return self.state

    def get_latest_checkpoint(self) -> Optional[Path]:
        """Find the most recent checkpoint file."""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        return checkpoints[-1] if checkpoints else None

    def list_checkpoints(self) -> list[Path]:
        """List all checkpoint files in order."""
        return sorted(self.checkpoint_dir.glob("checkpoint_*.json"))

    def _compute_checksum(self, data: dict[str, Any]) -> str:
        """Compute a checksum for state integrity verification."""
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
