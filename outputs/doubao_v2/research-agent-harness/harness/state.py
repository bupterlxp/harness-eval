"""
State Store - Persists research progress and maintains state
"""

import os
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import asdict, dataclass
import time

from .tools import Source


@dataclass
class ResearchState:
    """Represents the current state of a research task"""
    research_questions: List[str]
    min_sources: int
    max_words: int
    required_sections: List[str]
    max_hops: int
    output_dir: str
    constraints: List[str]

    # Current progress
    current_hop: int = 0
    sources_collected: int = 0
    facts_extracted: int = 0
    sections_drafted: int = 0

    # Persisted data
    sources: List[Dict[str, Any]] = None
    facts: List[Dict[str, Any]] = None
    section_drafts: Dict[str, str] = None
    citation_map: Dict[int, List[int]] = None
    trajectory: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = []
        if self.facts is None:
            self.facts = []
        if self.section_drafts is None:
            self.section_drafts = {}
        if self.citation_map is None:
            self.citation_map = {}
        if self.trajectory is None:
            self.trajectory = []


class StateStore:
    """
    Persists research progress and maintains state between execution steps
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.state_file = os.path.join(output_dir, "research_state.json")
        self.current_state: Optional[ResearchState] = None

    def initialize(self, task_spec: Dict[str, Any]) -> None:
        """Initialize state from task specification"""
        self.current_state = ResearchState(
            research_questions=task_spec["research_questions"],
            min_sources=task_spec.get("min_sources", 10),
            max_words=task_spec.get("max_words", 4000),
            required_sections=task_spec.get("required_sections", []),
            max_hops=task_spec.get("max_hops", 3),
            output_dir=task_spec["output_dir"],
            constraints=task_spec.get("constraints", [])
        )
        self._save_state()

    def load(self) -> bool:
        """Load state from disk"""
        if os.path.exists(self.state_file):
            with open(self.state_file, "r") as f:
                state_data = json.load(f)
                self.current_state = ResearchState(**state_data)
            return True
        return False

    def _save_state(self) -> None:
        """Save current state to disk"""
        if self.current_state:
            state_dict = asdict(self.current_state)
            with open(self.state_file, "w") as f:
                json.dump(state_dict, f, indent=2)

    def update_progress(self, current_hop: Optional[int] = None,
                       sources_collected: Optional[int] = None,
                       facts_extracted: Optional[int] = None,
                       sections_drafted: Optional[int] = None) -> None:
        """Update progress metrics"""
        if not self.current_state:
            raise RuntimeError("State not initialized")

        if current_hop is not None:
            self.current_state.current_hop = current_hop
        if sources_collected is not None:
            self.current_state.sources_collected = sources_collected
        if facts_extracted is not None:
            self.current_state.facts_extracted = facts_extracted
        if sections_drafted is not None:
            self.current_state.sections_drafted = sections_drafted

        self._save_state()

    def add_source(self, source: Dict[str, Any]) -> None:
        """Add a source to the state"""
        if not self.current_state:
            raise RuntimeError("State not initialized")

        self.current_state.sources.append(source)
        self._save_state()

    def add_fact(self, fact: Dict[str, Any]) -> None:
        """Add a fact to the state"""
        if not self.current_state:
            raise RuntimeError("State not initialized")

        self.current_state.facts.append(fact)
        self._save_state()

    def add_section_draft(self, section_name: str, draft: str) -> None:
        """Add a section draft to the state"""
        if not self.current_state:
            raise RuntimeError("State not initialized")

        self.current_state.section_drafts[section_name] = draft
        self._save_state()

    def add_trajectory_entry(self, entry: Dict[str, Any]) -> None:
        """Add an entry to the research trajectory"""
        if not self.current_state:
            raise RuntimeError("State not initialized")

        # Add timestamp if not present
        if "timestamp" not in entry:
            entry["timestamp"] = time.time()

        self.current_state.trajectory.append(entry)
        self._save_state()

    def get_trajectory_path(self) -> str:
        """Get the path to the trajectory file"""
        return os.path.join(self.output_dir, "trajectory.jsonl")

    def save_trajectory(self) -> None:
        """Save the full trajectory to JSONL file"""
        if not self.current_state:
            raise RuntimeError("State not initialized")

        trajectory_path = self.get_trajectory_path()
        with open(trajectory_path, "w") as f:
            for entry in self.current_state.trajectory:
                json.dump(entry, f)
                f.write("\n")

    def get_state(self) -> Optional[ResearchState]:
        """Get the current state"""
        return self.current_state