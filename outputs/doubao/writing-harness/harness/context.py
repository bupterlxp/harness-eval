import json
import tiktoken
from typing import Dict, List, Any, Optional, Tuple
from collections import OrderedDict
from .schemas import ImageryEntry, NarratorProfile


class ContextManager:
    """Manages context with compression, retrieval, and priority strategies"""

    def __init__(self, max_context_size: int = 8192, model_name: str = "gpt-3.5-turbo"):
        self.max_context_size = max_context_size
        self.model_name = model_name
        self.encoding = tiktoken.encoding_for_model(model_name)

        # Context storage
        self.narrator_profile: Optional[NarratorProfile] = None
        self.established_imagery: Dict[str, ImageryEntry] = {}
        self.current_scenes: List[Dict[str, Any]] = []
        self.plot_outline: Optional[Dict[str, Any]] = None
        self.task_spec: Optional[Dict[str, Any]] = None
        self.style_requirements: Dict[str, Any] = {}

        # Priority weights for context compression
        self.priority_weights = {
            "narrator_profile": 10.0,
            "style_requirements": 9.0,
            "plot_outline": 8.0,
            "established_imagery": 7.0,
            "current_scenes": 5.0,
            "task_spec": 6.0
        }

    def set_narrator_profile(self, profile: NarratorProfile) -> None:
        """Set the narrator profile"""
        self.narrator_profile = profile

    def add_imagery_entry(self, entry: ImageryEntry) -> None:
        """Add or update an imagery entry"""
        if entry.term in self.established_imagery:
            existing = self.established_imagery[entry.term]
            existing.usage_count += 1
            existing.context = f"{existing.context}; {entry.context}"
        else:
            self.established_imagery[entry.term] = entry

    def add_imagery_batch(self, entries: List[ImageryEntry]) -> None:
        """Add multiple imagery entries"""
        for entry in entries:
            self.add_imagery_entry(entry)

    def set_plot_outline(self, outline: Dict[str, Any]) -> None:
        """Set the plot outline"""
        self.plot_outline = outline

    def set_task_spec(self, spec: Dict[str, Any]) -> None:
        """Set the task specification"""
        self.task_spec = spec

    def set_style_requirements(self, requirements: Dict[str, Any]) -> None:
        """Set style requirements"""
        self.style_requirements = requirements

    def add_current_scene(self, scene: Dict[str, Any]) -> None:
        """Add a completed scene to current scenes"""
        self.current_scenes.append(scene)

    def get_context_tokens(self) -> int:
        """Calculate total token count of current context"""
        context_str = self.serialize_context()
        return len(self.encoding.encode(context_str))

    def serialize_context(self, include_sections: Optional[List[str]] = None) -> str:
        """Serialize context to string for LLM prompts"""
        sections = []

        if include_sections is None:
            include_sections = ["task_spec", "narrator_profile", "style_requirements", "plot_outline", "established_imagery", "current_scenes"]

        for section in include_sections:
            if section == "task_spec" and self.task_spec:
                sections.append(f"# Task Specification\n{json.dumps(self.task_spec, indent=2)}")
            elif section == "narrator_profile" and self.narrator_profile:
                sections.append(f"# Narrator Profile\n{json.dumps(self.narrator_profile.dict(), indent=2)}")
            elif section == "style_requirements" and self.style_requirements:
                sections.append(f"# Style Requirements\n{json.dumps(self.style_requirements, indent=2)}")
            elif section == "plot_outline" and self.plot_outline:
                sections.append(f"# Plot Outline\n{json.dumps(self.plot_outline, indent=2)}")
            elif section == "established_imagery" and self.established_imagery:
                imagery_list = [entry.dict() for entry in self.established_imagery.values()]
                sections.append(f"# Established Imagery\n{json.dumps(imagery_list, indent=2)}")
            elif section == "current_scenes" and self.current_scenes:
                sections.append(f"# Current Scenes\n{json.dumps(self.current_scenes, indent=2)}")

        return "\n\n".join(sections)

    def compress_context(self) -> Tuple[str, int]:
        """Compress context to fit within max token limit"""
        total_tokens = self.get_context_tokens()

        if total_tokens <= self.max_context_size:
            return self.serialize_context(), total_tokens

        # Sort contexts by priority (lowest first to remove)
        priority_order = sorted(
            self.priority_weights.items(),
            key=lambda x: x[1]
        )

        # Remove lowest priority sections until context fits
        sections_to_include = ["task_spec", "narrator_profile", "style_requirements", "plot_outline", "established_imagery", "current_scenes"]

        for section_name, _ in priority_order:
            if total_tokens <= self.max_context_size:
                break

            if section_name in sections_to_include:
                sections_to_include.remove(section_name)
                current_str = self.serialize_context(sections_to_include)
                total_tokens = len(self.encoding.encode(current_str))

        # If still too big, truncate individual sections
        if total_tokens > self.max_context_size:
            # Simplest approach: truncate current scenes (most expendable)
            if "current_scenes" in sections_to_include:
                # Keep only most recent scenes
                max_scenes_tokens = self.max_context_size * 0.2
                scene_str = "# Current Scenes\n"
                scene_tokens = len(self.encoding.encode(scene_str))
                kept_scenes = []

                for scene in reversed(self.current_scenes):
                    scene_json = json.dumps(scene)
                    scene_tokens += len(self.encoding.encode(scene_json))

                    if scene_tokens <= max_scenes_tokens:
                        kept_scenes.insert(0, scene)
                    else:
                        break

                sections_to_include.remove("current_scenes")
                if kept_scenes:
                    sections_to_include.append("current_scenes")
                    self.current_scenes = kept_scenes

        final_context = self.serialize_context(sections_to_include)
        final_tokens = len(self.encoding.encode(final_context))

        return final_context, final_tokens

    def get_relevant_imagery(self, query: str, limit: int = 5) -> List[ImageryEntry]:
        """Retrieve most relevant imagery entries for a query"""
        if not self.established_imagery:
            return []

        # Simple keyword matching for now
        query_terms = set(query.lower().split())
        scored_entries = []

        for term, entry in self.established_imagery.items():
            score = 0
            if term.lower() in query_terms:
                score += 10

            # Check category
            if entry.category.lower() in query.lower():
                score += 5

            # Weight by usage count
            score += entry.usage_count * 0.5

            if score > 0:
                scored_entries.append((score, entry))

        # Sort by score descending and take top N
        scored_entries.sort(reverse=True, key=lambda x: x[0])
        return [entry for _, entry in scored_entries[:limit]]

    def get_narrator_voice_prompt(self) -> str:
        """Get prompt fragment for narrator voice"""
        if not self.narrator_profile:
            return ""

        return f"""Narrator Voice Guidelines:
- Use this voice sample as reference: {self.narrator_profile.voice_sample}
- Narrator is {'' if self.narrator_profile.unreliable else 'not'} unreliable
- Core motivation: {self.narrator_profile.core_motivation}
"""

    def clear(self) -> None:
        """Clear all context"""
        self.narrator_profile = None
        self.established_imagery = {}
        self.current_scenes = []
        self.plot_outline = None
        self.task_spec = None
        self.style_requirements = {}