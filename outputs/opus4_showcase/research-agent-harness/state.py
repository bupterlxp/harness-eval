"""State Store - state persistence and checkpoint recovery.

Provides snapshotting of the full agent state at each step, enabling
checkpoint-based resume after crashes or interruptions.
"""

from __future__ import annotations

import json
import time
import copy
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class AgentPhase(str, Enum):
    """FSM states for the execution loop."""
    INIT = "init"
    DECOMPOSE = "decompose"
    SEARCH = "search"
    FETCH = "fetch"
    ANALYZE = "analyze"
    SYNTHESIZE = "synthesize"
    GENERATE = "generate"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class EvidenceCard:
    """A structured evidence unit extracted from a source."""
    uid: str
    title: str
    content: str
    source_url: str
    summary: str
    tags: list[str]
    quality_score: float  # 0.0 - 1.0
    chunk_index: int = 0
    contradicts: list[str] = field(default_factory=list)  # UIDs of contradicting cards


@dataclass
class SubTask:
    """A node in the task decomposition DAG."""
    task_id: str
    query: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | failed
    result: str | None = None
    depth: int = 0


@dataclass
class AgentState:
    """Complete snapshot of agent state - sufficient to resume from checkpoint."""
    phase: AgentPhase = AgentPhase.INIT
    question: str = ""
    mode: str = "auto"  # auto | report | qa
    detected_mode: str | None = None  # report | qa (after detection)
    current_round: int = 0
    max_rounds: int = 4
    initial_breadth: int = 4

    # Task decomposition
    sub_tasks: list[SubTask] = field(default_factory=list)
    framework: str = "mece"  # mece | pyramid | chronological

    # Evidence store
    evidence_cards: list[EvidenceCard] = field(default_factory=list)
    visited_urls: set[str] = field(default_factory=set)

    # Search state
    pending_queries: list[str] = field(default_factory=list)
    completed_queries: list[str] = field(default_factory=list)
    search_results_buffer: list[dict[str, Any]] = field(default_factory=list)

    # Synthesis
    outline: list[dict[str, Any]] = field(default_factory=list)
    sections: list[dict[str, str]] = field(default_factory=list)
    final_answer: str | None = None
    citations: dict[str, str] = field(default_factory=dict)  # citation_id -> url

    # Metadata
    start_time: float = field(default_factory=time.time)
    step_count: int = 0
    error_log: list[str] = field(default_factory=list)
    transition_history: list[tuple[str, str]] = field(default_factory=list)

    def word_count(self) -> int:
        """Count total words in all evidence cards."""
        total = 0
        for card in self.evidence_cards:
            total += len(card.content.split())
        return total


class StateStore:
    """Manages state persistence and checkpoint recovery."""

    def __init__(self, state: AgentState | None = None, checkpoint_dir: Path | None = None):
        self._state = state or AgentState()
        self._checkpoint_dir = checkpoint_dir
        self._snapshots: list[dict[str, Any]] = []

    @property
    def state(self) -> AgentState:
        return self._state

    @state.setter
    def state(self, value: AgentState) -> None:
        self._state = value

    def snapshot(self) -> dict[str, Any]:
        """Take a full snapshot of current state. Returns serializable dict."""
        snap = {
            "phase": self._state.phase.value,
            "question": self._state.question,
            "mode": self._state.mode,
            "detected_mode": self._state.detected_mode,
            "current_round": self._state.current_round,
            "max_rounds": self._state.max_rounds,
            "initial_breadth": self._state.initial_breadth,
            "framework": self._state.framework,
            "sub_tasks": [
                {
                    "task_id": t.task_id,
                    "query": t.query,
                    "depends_on": t.depends_on,
                    "status": t.status,
                    "result": t.result,
                    "depth": t.depth,
                }
                for t in self._state.sub_tasks
            ],
            "evidence_cards": [
                {
                    "uid": c.uid,
                    "title": c.title,
                    "content": c.content,
                    "source_url": c.source_url,
                    "summary": c.summary,
                    "tags": c.tags,
                    "quality_score": c.quality_score,
                    "chunk_index": c.chunk_index,
                    "contradicts": c.contradicts,
                }
                for c in self._state.evidence_cards
            ],
            "visited_urls": list(self._state.visited_urls),
            "pending_queries": self._state.pending_queries,
            "completed_queries": self._state.completed_queries,
            "search_results_buffer": self._state.search_results_buffer,
            "outline": self._state.outline,
            "sections": self._state.sections,
            "final_answer": self._state.final_answer,
            "citations": self._state.citations,
            "start_time": self._state.start_time,
            "step_count": self._state.step_count,
            "error_log": self._state.error_log,
            "transition_history": self._state.transition_history,
            "snapshot_time": time.time(),
        }
        self._snapshots.append(snap)
        return snap

    def save_checkpoint(self, path: Path | None = None) -> Path:
        """Save current state to a checkpoint file."""
        snap = self.snapshot()
        if path is None:
            if self._checkpoint_dir is None:
                raise ValueError("No checkpoint directory configured")
            self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
            path = self._checkpoint_dir / f"checkpoint_{self._state.step_count}.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2, ensure_ascii=False)
        return path

    @classmethod
    def load_checkpoint(cls, path: str | Path) -> "StateStore":
        """Restore state from a checkpoint file."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)

        state = AgentState()
        state.phase = AgentPhase(snap["phase"])
        state.question = snap["question"]
        state.mode = snap["mode"]
        state.detected_mode = snap.get("detected_mode")
        state.current_round = snap["current_round"]
        state.max_rounds = snap["max_rounds"]
        state.initial_breadth = snap["initial_breadth"]
        state.framework = snap.get("framework", "mece")

        state.sub_tasks = [
            SubTask(
                task_id=t["task_id"],
                query=t["query"],
                depends_on=t["depends_on"],
                status=t["status"],
                result=t.get("result"),
                depth=t.get("depth", 0),
            )
            for t in snap.get("sub_tasks", [])
        ]

        state.evidence_cards = [
            EvidenceCard(
                uid=c["uid"],
                title=c["title"],
                content=c["content"],
                source_url=c["source_url"],
                summary=c["summary"],
                tags=c["tags"],
                quality_score=c["quality_score"],
                chunk_index=c.get("chunk_index", 0),
                contradicts=c.get("contradicts", []),
            )
            for c in snap.get("evidence_cards", [])
        ]

        state.visited_urls = set(snap.get("visited_urls", []))
        state.pending_queries = snap.get("pending_queries", [])
        state.completed_queries = snap.get("completed_queries", [])
        state.search_results_buffer = snap.get("search_results_buffer", [])
        state.outline = snap.get("outline", [])
        state.sections = snap.get("sections", [])
        state.final_answer = snap.get("final_answer")
        state.citations = snap.get("citations", {})
        state.start_time = snap.get("start_time", time.time())
        state.step_count = snap.get("step_count", 0)
        state.error_log = snap.get("error_log", [])
        state.transition_history = snap.get("transition_history", [])

        checkpoint_dir = path.parent
        return cls(state=state, checkpoint_dir=checkpoint_dir)

    @property
    def snapshots(self) -> list[dict[str, Any]]:
        return self._snapshots
