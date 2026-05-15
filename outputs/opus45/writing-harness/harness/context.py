"""
context.py - C: Context Manager

Implements compression, retrieval, and priority interfaces for managing
LLM context windows. Handles narrator voice anchoring, imagery tables,
and scene history.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContextCategory(str, Enum):
    """Categories of context with different priority and retention"""
    SYSTEM = "system"
    NARRATOR_VOICE = "narrator_voice"
    STYLE_ANCHORS = "style_anchors"
    IMAGERY_TABLE = "imagery_table"
    PLOT_OUTLINE = "plot_outline"
    SCENE_HISTORY = "scene_history"
    CURRENT_SCENE = "current_scene"
    TASK_SPEC = "task_spec"
    WORKING = "working"


@dataclass
class ContextEntry:
    """A single entry in the context"""
    category: ContextCategory
    key: str
    content: str
    token_estimate: int = 0
    priority: int = 0
    pinned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = len(self.content) // 4


@dataclass
class ContextBudget:
    """Token budget allocation by category"""
    total_tokens: int = 8000
    reserved_for_output: int = 2000
    category_limits: dict[ContextCategory, int] = field(default_factory=dict)

    def __post_init__(self):
        if not self.category_limits:
            available = self.total_tokens - self.reserved_for_output
            self.category_limits = {
                ContextCategory.SYSTEM: 500,
                ContextCategory.NARRATOR_VOICE: 300,
                ContextCategory.STYLE_ANCHORS: 200,
                ContextCategory.IMAGERY_TABLE: 400,
                ContextCategory.PLOT_OUTLINE: 500,
                ContextCategory.SCENE_HISTORY: min(2000, available // 3),
                ContextCategory.CURRENT_SCENE: 800,
                ContextCategory.TASK_SPEC: 500,
                ContextCategory.WORKING: available - 5200,
            }


class CompressionStrategy(ABC):
    """Abstract compression strategy"""

    @abstractmethod
    def compress(self, entries: list[ContextEntry], target_tokens: int) -> list[ContextEntry]:
        """Compress entries to fit within target token count"""
        pass


class TruncationStrategy(CompressionStrategy):
    """Simple truncation-based compression"""

    def compress(self, entries: list[ContextEntry], target_tokens: int) -> list[ContextEntry]:
        result = []
        current_tokens = 0

        sorted_entries = sorted(entries, key=lambda e: (-int(e.pinned), -e.priority))

        for entry in sorted_entries:
            if current_tokens + entry.token_estimate <= target_tokens:
                result.append(entry)
                current_tokens += entry.token_estimate
            elif entry.pinned:
                excess = (current_tokens + entry.token_estimate) - target_tokens
                char_excess = excess * 4
                truncated_content = entry.content[:-char_excess] if len(entry.content) > char_excess else entry.content[:100]
                truncated = ContextEntry(
                    category=entry.category,
                    key=entry.key,
                    content=truncated_content + "...[truncated]",
                    priority=entry.priority,
                    pinned=True,
                    metadata=entry.metadata
                )
                result.append(truncated)
                current_tokens += truncated.token_estimate

        return result


class SummarizationStrategy(CompressionStrategy):
    """Compression via summarization (for scene history)"""

    def __init__(self, summarizer: callable | None = None):
        self.summarizer = summarizer

    def compress(self, entries: list[ContextEntry], target_tokens: int) -> list[ContextEntry]:
        pinned = [e for e in entries if e.pinned]
        unpinned = [e for e in entries if not e.pinned]

        pinned_tokens = sum(e.token_estimate for e in pinned)
        available_for_unpinned = target_tokens - pinned_tokens

        if available_for_unpinned <= 0:
            return pinned

        unpinned_sorted = sorted(unpinned, key=lambda e: -e.priority)

        scene_entries = [e for e in unpinned_sorted if e.category == ContextCategory.SCENE_HISTORY]
        other_entries = [e for e in unpinned_sorted if e.category != ContextCategory.SCENE_HISTORY]

        result = list(pinned)
        current_tokens = pinned_tokens

        for entry in other_entries:
            if current_tokens + entry.token_estimate <= target_tokens:
                result.append(entry)
                current_tokens += entry.token_estimate

        remaining = target_tokens - current_tokens
        if scene_entries and remaining > 0:
            if self.summarizer and sum(e.token_estimate for e in scene_entries) > remaining:
                combined_content = "\n\n---\n\n".join(e.content for e in scene_entries)
                summary = self.summarizer(combined_content, remaining * 4)
                result.append(ContextEntry(
                    category=ContextCategory.SCENE_HISTORY,
                    key="scene_history_summary",
                    content=summary,
                    priority=5,
                    metadata={"summarized_from": len(scene_entries)}
                ))
            else:
                for entry in scene_entries:
                    if current_tokens + entry.token_estimate <= target_tokens:
                        result.append(entry)
                        current_tokens += entry.token_estimate

        return result


class ContextManager:
    """
    C component: Manages context for LLM prompts.

    Provides:
    - compress: Reduce context to fit token budget
    - retrieve: Get relevant context for current task
    - prioritize: Rank context by relevance
    """

    def __init__(
        self,
        budget: ContextBudget | None = None,
        compression_strategy: CompressionStrategy | None = None
    ):
        self.budget = budget or ContextBudget()
        self.compression_strategy = compression_strategy or TruncationStrategy()
        self._entries: dict[str, ContextEntry] = {}
        self._category_priorities = {
            ContextCategory.SYSTEM: 100,
            ContextCategory.NARRATOR_VOICE: 95,
            ContextCategory.STYLE_ANCHORS: 90,
            ContextCategory.IMAGERY_TABLE: 85,
            ContextCategory.PLOT_OUTLINE: 80,
            ContextCategory.CURRENT_SCENE: 75,
            ContextCategory.TASK_SPEC: 70,
            ContextCategory.SCENE_HISTORY: 50,
            ContextCategory.WORKING: 30,
        }

    def add(
        self,
        category: ContextCategory,
        key: str,
        content: str,
        priority: int | None = None,
        pinned: bool = False,
        metadata: dict[str, Any] | None = None
    ) -> None:
        """Add or update a context entry"""
        if priority is None:
            priority = self._category_priorities.get(category, 0)

        entry = ContextEntry(
            category=category,
            key=key,
            content=content,
            priority=priority,
            pinned=pinned,
            metadata=metadata or {}
        )
        self._entries[key] = entry

    def remove(self, key: str) -> None:
        """Remove a context entry"""
        self._entries.pop(key, None)

    def get(self, key: str) -> ContextEntry | None:
        """Get a specific context entry"""
        return self._entries.get(key)

    def get_by_category(self, category: ContextCategory) -> list[ContextEntry]:
        """Get all entries in a category"""
        return [e for e in self._entries.values() if e.category == category]

    def compress(self, target_tokens: int | None = None) -> list[ContextEntry]:
        """Compress context to fit within token budget"""
        if target_tokens is None:
            target_tokens = self.budget.total_tokens - self.budget.reserved_for_output

        entries = list(self._entries.values())
        return self.compression_strategy.compress(entries, target_tokens)

    def retrieve(
        self,
        categories: list[ContextCategory] | None = None,
        include_pinned: bool = True
    ) -> list[ContextEntry]:
        """Retrieve relevant context entries"""
        entries = list(self._entries.values())

        if categories:
            entries = [e for e in entries if e.category in categories]
        if include_pinned:
            pinned = [e for e in self._entries.values() if e.pinned and e not in entries]
            entries.extend(pinned)

        return sorted(entries, key=lambda e: -e.priority)

    def prioritize(self, query: str | None = None) -> list[ContextEntry]:
        """Return all entries sorted by priority"""
        return sorted(self._entries.values(), key=lambda e: -e.priority)

    def build_prompt_context(
        self,
        categories: list[ContextCategory] | None = None,
        max_tokens: int | None = None
    ) -> str:
        """Build a formatted context string for LLM prompt"""
        if categories is None:
            categories = [
                ContextCategory.SYSTEM,
                ContextCategory.NARRATOR_VOICE,
                ContextCategory.STYLE_ANCHORS,
                ContextCategory.TASK_SPEC,
                ContextCategory.PLOT_OUTLINE,
                ContextCategory.IMAGERY_TABLE,
                ContextCategory.SCENE_HISTORY,
                ContextCategory.CURRENT_SCENE,
            ]

        entries = self.retrieve(categories)

        if max_tokens:
            entries = self.compression_strategy.compress(entries, max_tokens)

        sections = []
        current_category = None

        for entry in entries:
            if entry.category != current_category:
                current_category = entry.category
                sections.append(f"\n### {current_category.value.upper().replace('_', ' ')}")

            sections.append(entry.content)

        return "\n".join(sections)

    def get_token_usage(self) -> dict[str, int]:
        """Get current token usage by category"""
        usage = {}
        for entry in self._entries.values():
            cat = entry.category.value
            usage[cat] = usage.get(cat, 0) + entry.token_estimate
        usage["total"] = sum(usage.values())
        return usage

    def clear_category(self, category: ContextCategory) -> None:
        """Clear all entries in a category"""
        to_remove = [k for k, v in self._entries.items() if v.category == category]
        for key in to_remove:
            del self._entries[key]

    def reset(self, preserve_pinned: bool = True) -> None:
        """Reset context, optionally preserving pinned entries"""
        if preserve_pinned:
            self._entries = {k: v for k, v in self._entries.items() if v.pinned}
        else:
            self._entries = {}

    def set_narrator_voice(self, voice_sample: str) -> None:
        """Set the narrator voice anchor (always injected)"""
        self.add(
            ContextCategory.NARRATOR_VOICE,
            "narrator_voice_sample",
            f"NARRATOR VOICE SAMPLE (maintain this tone throughout):\n\n{voice_sample}",
            pinned=True
        )

    def set_imagery_table(self, imagery_entries: list[dict[str, Any]]) -> None:
        """Set the imagery table for consistency"""
        if not imagery_entries:
            return

        table_lines = ["ESTABLISHED IMAGERY (reference consistently):"]
        for entry in imagery_entries:
            table_lines.append(
                f"- {entry['name']}: {entry['description']} "
                f"(introduced scene {entry.get('first_scene', '?')})"
            )

        self.add(
            ContextCategory.IMAGERY_TABLE,
            "imagery_table",
            "\n".join(table_lines),
            pinned=True
        )

    def add_scene_history(self, scene_id: int, content: str, is_current: bool = False) -> None:
        """Add a scene to history"""
        category = ContextCategory.CURRENT_SCENE if is_current else ContextCategory.SCENE_HISTORY

        self.add(
            category,
            f"scene_{scene_id}",
            f"SCENE {scene_id}:\n{content}",
            priority=75 if is_current else 50 - scene_id,
            metadata={"scene_id": scene_id}
        )

    def snapshot(self) -> dict[str, Any]:
        """Create a snapshot of current context state"""
        return {
            "entries": {k: {
                "category": v.category.value,
                "content": v.content,
                "priority": v.priority,
                "pinned": v.pinned,
                "metadata": v.metadata
            } for k, v in self._entries.items()},
            "token_usage": self.get_token_usage()
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore context from snapshot"""
        self._entries = {}
        for key, data in snapshot.get("entries", {}).items():
            self.add(
                category=ContextCategory(data["category"]),
                key=key,
                content=data["content"],
                priority=data.get("priority"),
                pinned=data.get("pinned", False),
                metadata=data.get("metadata")
            )
