"""Context Manager — context management and compression with token budget.

Implements three-layer memory management, token budget mechanism,
auto-summarize/truncate on overflow, and RAG-style retrieval for
distant references.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from harness.state import WritingState, SemanticMemory


@dataclass
class ContextBlock:
    """A block of context with priority and token estimate."""
    label: str
    content: str
    priority: int  # 1=highest, 5=lowest
    token_estimate: int = 0
    compressible: bool = True

    def __post_init__(self) -> None:
        if self.token_estimate == 0:
            self.token_estimate = estimate_tokens(self.content)


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English."""
    if not text:
        return 0
    return max(1, len(text) // 4)


class ContextManager:
    """Manages context window with token budget and auto-compression."""

    def __init__(self, token_budget: int = 120000):
        self.token_budget = token_budget
        self.reserved_for_output = min(4000, token_budget // 4)  # Reserve tokens for LLM response
        self.available_budget = max(1, token_budget - self.reserved_for_output)
        self._blocks: list[ContextBlock] = []

    def reset(self) -> None:
        """Clear all context blocks."""
        self._blocks = []

    def add_block(self, label: str, content: str, priority: int = 3,
                  compressible: bool = True) -> None:
        """Add a context block."""
        block = ContextBlock(
            label=label, content=content,
            priority=priority, compressible=compressible,
        )
        self._blocks.append(block)

    def total_tokens(self) -> int:
        """Total token count across all blocks."""
        return sum(b.token_estimate for b in self._blocks)

    def is_over_budget(self) -> bool:
        """Check if current context exceeds budget."""
        return self.total_tokens() > self.available_budget

    def build_context(self, state: WritingState) -> list[dict[str, str]]:
        """Build the full context as a list of message dicts for the LLM.

        Priority allocation:
        - P1: System prompt, current task, working memory
        - P2: Voice fingerprint, style constraints, world rules
        - P3: Recent episodes, chapter outline
        - P4: Semantic memory (characters, timeline)
        - P5: Historical drafts, distant references
        """
        self.reset()

        # P1: System and working context
        self.add_block("system_prompt", self._build_system_prompt(state), priority=1, compressible=False)
        self.add_block("task", state.task_prompt, priority=1, compressible=False)
        self.add_block("working_memory", self._format_working_memory(state), priority=1)

        # P2: Style and world rules
        if state.voice_fingerprint:
            self.add_block("voice_fingerprint", state.voice_fingerprint, priority=2)
        if state.forbidden_patterns:
            patterns_text = self._format_forbidden_patterns(state)
            self.add_block("forbidden_patterns", patterns_text, priority=2)
        if state.semantic_memory.world_rules:
            rules_text = self._format_world_rules(state)
            self.add_block("world_rules", rules_text, priority=2)

        # P3: Recent context
        recent_episodes = state.episodic_memory.get_recent(5)
        if recent_episodes:
            ep_text = self._format_episodes(recent_episodes)
            self.add_block("recent_episodes", ep_text, priority=3)
        if state.chapter_outlines and state.working_memory.current_chapter < len(state.chapter_outlines):
            outline = state.chapter_outlines[state.working_memory.current_chapter]
            self.add_block("current_chapter_outline", outline, priority=3)

        # P4: Semantic memory
        if state.semantic_memory.characters:
            char_text = self._format_characters(state)
            self.add_block("characters", char_text, priority=4)
        if state.semantic_memory.timeline:
            timeline_text = self._format_timeline(state)
            self.add_block("timeline", timeline_text, priority=4)

        # P5: Historical drafts (compressed)
        if state.drafts:
            drafts_text = self._format_prior_drafts(state)
            self.add_block("prior_drafts", drafts_text, priority=5)

        # Compress if over budget
        if self.is_over_budget():
            self._compress_to_budget()

        # Convert to messages
        return self._blocks_to_messages()

    def build_shortform_context(self, state: WritingState) -> list[dict[str, str]]:
        """Build context optimized for short-form / roleplay."""
        self.reset()

        self.add_block("system_prompt", self._build_shortform_system_prompt(state), priority=1, compressible=False)
        self.add_block("task", state.task_prompt, priority=1, compressible=False)

        if state.scenario_analysis:
            self.add_block("scenario_analysis", state.scenario_analysis, priority=2)
        if state.emotional_map:
            self.add_block("emotional_map", state.emotional_map, priority=2)
        if state.mental_models:
            models_text = "\n".join(f"[{k}]: {v}" for k, v in state.mental_models.items())
            self.add_block("mental_models", models_text, priority=2)
        if state.voice_fingerprint:
            self.add_block("voice_fingerprint", state.voice_fingerprint, priority=3)
        if state.forbidden_patterns:
            self.add_block("forbidden_patterns", self._format_forbidden_patterns(state), priority=3)

        if self.is_over_budget():
            self._compress_to_budget()

        return self._blocks_to_messages()

    def retrieve_relevant(self, query: str, state: WritingState, top_k: int = 3) -> str:
        """RAG-style retrieval from semantic memory for distant references."""
        query_terms = set(query.lower().split())
        scored_items: list[tuple[float, str]] = []

        # Search characters
        for name, char in state.semantic_memory.characters.items():
            char_text = f"Character {name}: {', '.join(char.knowledge[:5])}"
            score = self._relevance_score(query_terms, char_text)
            if score > 0:
                scored_items.append((score, char_text))

        # Search timeline
        for event in state.semantic_memory.timeline:
            event_text = f"[{event.timestamp_story}] {event.description}"
            score = self._relevance_score(query_terms, event_text)
            if score > 0:
                scored_items.append((score, event_text))

        # Search episodes
        for ep in state.episodic_memory.recent_scenes:
            score = self._relevance_score(query_terms, ep["summary"])
            if score > 0:
                scored_items.append((score, ep["summary"]))

        # Search plot threads
        for thread, beats in state.semantic_memory.plot_threads.items():
            thread_text = f"Thread '{thread}': {'; '.join(beats[-3:])}"
            score = self._relevance_score(query_terms, thread_text)
            if score > 0:
                scored_items.append((score, thread_text))

        # Sort by score and return top_k
        scored_items.sort(key=lambda x: x[0], reverse=True)
        results = [item for _, item in scored_items[:top_k]]
        return "\n".join(results) if results else ""

    def _relevance_score(self, query_terms: set[str], text: str) -> float:
        """Simple term-overlap relevance scoring."""
        text_terms = set(text.lower().split())
        overlap = query_terms & text_terms
        if not overlap:
            return 0.0
        return len(overlap) / len(query_terms)

    def _compress_to_budget(self) -> None:
        """Compress context blocks to fit within budget.

        Strategy: compress lowest-priority blocks first via summarization.
        If still over budget, truncate.
        """
        # Sort by priority (lowest first = most compressible)
        compressible = [b for b in self._blocks if b.compressible]
        compressible.sort(key=lambda b: b.priority, reverse=True)

        for block in compressible:
            if not self.is_over_budget():
                break
            # Compress by truncation with summary marker
            original_tokens = block.token_estimate
            target_tokens = original_tokens // 3  # Compress to 1/3
            target_chars = target_tokens * 4
            if len(block.content) > target_chars:
                truncated = block.content[:target_chars]
                block.content = truncated + "\n[... compressed ...]"
                block.token_estimate = estimate_tokens(block.content)

        # If still over budget, drop lowest priority blocks
        if self.is_over_budget():
            self._blocks.sort(key=lambda b: b.priority)
            while self.is_over_budget() and self._blocks:
                dropped = self._blocks.pop()
                if not dropped.compressible:
                    # Never drop incompressible blocks; put it back
                    self._blocks.append(dropped)
                    break

    def _blocks_to_messages(self) -> list[dict[str, str]]:
        """Convert blocks to message format for LLM."""
        messages: list[dict[str, str]] = []

        # First block is system prompt
        system_blocks = [b for b in self._blocks if b.label == "system_prompt"]
        other_blocks = [b for b in self._blocks if b.label != "system_prompt"]

        if system_blocks:
            messages.append({"role": "system", "content": system_blocks[0].content})

        # Combine remaining blocks into user message
        user_parts: list[str] = []
        for block in other_blocks:
            if block.content.strip():
                user_parts.append(f"### {block.label}\n{block.content}")

        if user_parts:
            messages.append({"role": "user", "content": "\n\n".join(user_parts)})

        return messages

    def _build_system_prompt(self, state: WritingState) -> str:
        return (
            "You are a master creative writer and novelist. Your task is to produce "
            "exceptional prose that is vivid, emotionally resonant, and stylistically "
            "distinctive. Follow the voice fingerprint and avoid forbidden patterns. "
            "Show, don't tell. Use concrete sensory details. Vary sentence length and structure. "
            "Avoid generic adverbs (suddenly, very, really), formulaic openings, and "
            "LLM-typical writing habits. Each scene must advance plot, reveal character, "
            "or build atmosphere — preferably all three.\n\n"
            f"Mode: {state.mode}\n"
            f"Genre: {state.genre}\n"
            f"Current Phase: {state.current_phase}\n"
            f"Chapter: {state.working_memory.current_chapter}, "
            f"Scene: {state.working_memory.current_scene}"
        )

    def _build_shortform_system_prompt(self, state: WritingState) -> str:
        return (
            "You are an expert at emotionally intelligent creative roleplay and "
            "short-form fiction. You model the psychology of all participants with depth "
            "and nuance. Structure your responses with clear internal logic: "
            "'thinking & feeling' (character's internal state), "
            "'their psychology' (understanding the other participants), "
            "'in-character response' (the actual creative output). "
            "Avoid platitudes, generic empathy phrases, and hollow emotional language. "
            "Be specific, embodied, and psychologically grounded.\n\n"
            f"Genre: {state.genre}\n"
            f"Current Phase: {state.current_phase}"
        )

    def _format_working_memory(self, state: WritingState) -> str:
        wm = state.working_memory
        parts = []
        if wm.scene_context:
            parts.append(f"Scene Context: {wm.scene_context}")
        if wm.active_characters:
            parts.append(f"Active Characters: {', '.join(wm.active_characters)}")
        if wm.immediate_goals:
            parts.append(f"Scene Goals: {'; '.join(wm.immediate_goals)}")
        if wm.pov_character:
            parts.append(f"POV: {wm.pov_character}")
        if wm.tone:
            parts.append(f"Tone: {wm.tone}")
        if wm.pending_hooks:
            parts.append(f"Pending Hooks: {'; '.join(wm.pending_hooks)}")
        return "\n".join(parts) if parts else "(no working memory)"

    def _format_forbidden_patterns(self, state: WritingState) -> str:
        lines = ["FORBIDDEN PATTERNS (never use these):"]
        for pat in state.forbidden_patterns:
            alt = state.pattern_alternatives.get(pat, "find a specific alternative")
            lines.append(f"  - '{pat}' → instead: {alt}")
        return "\n".join(lines)

    def _format_world_rules(self, state: WritingState) -> str:
        lines = ["WORLD RULES (hard constraints):"]
        for rule in state.semantic_memory.world_rules:
            if rule.active:
                lines.append(f"  [{rule.category}] {rule.description}")
        return "\n".join(lines)

    def _format_episodes(self, episodes: list[dict[str, Any]]) -> str:
        lines = ["RECENT SCENES:"]
        for ep in episodes:
            lines.append(f"  Ch{ep['chapter']}.{ep['scene']}: {ep['summary']}")
        return "\n".join(lines)

    def _format_characters(self, state: WritingState) -> str:
        lines = ["CHARACTERS:"]
        for name, char in state.semantic_memory.characters.items():
            info = [f"  {name}"]
            if char.emotional_state:
                info.append(f"    Emotional State: {char.emotional_state}")
            if char.location:
                info.append(f"    Location: {char.location}")
            if char.goals:
                info.append(f"    Goals: {'; '.join(char.goals[:3])}")
            if char.relationships:
                rels = [f"{k}: {v}" for k, v in list(char.relationships.items())[:3]]
                info.append(f"    Relationships: {'; '.join(rels)}")
            lines.extend(info)
        return "\n".join(lines)

    def _format_timeline(self, state: WritingState) -> str:
        # Only include last 10 events to save space
        events = state.semantic_memory.timeline[-10:]
        lines = ["TIMELINE (recent):"]
        for ev in events:
            lines.append(f"  [{ev.timestamp_story}] {ev.description} "
                         f"(Ch{ev.chapter}, thread:{ev.thread})")
        return "\n".join(lines)

    def _format_prior_drafts(self, state: WritingState) -> str:
        """Format prior drafts as compressed summaries."""
        if not state.drafts:
            return ""
        # Only include last 2 drafts, truncated
        recent = state.drafts[-2:]
        lines = ["PRIOR DRAFTS (compressed):"]
        for i, draft in enumerate(recent):
            preview = draft[:500] + "..." if len(draft) > 500 else draft
            lines.append(f"  Draft {len(state.drafts) - len(recent) + i + 1}: {preview}")
        return "\n".join(lines)


class MemoryDeduplicator:
    """Deduplicates and compresses memory entries."""

    @staticmethod
    def deduplicate_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate or near-duplicate episodes."""
        seen_hashes: set[str] = set()
        deduped: list[dict[str, Any]] = []

        for ep in episodes:
            # Hash based on chapter+scene+summary prefix
            key = f"{ep['chapter']}_{ep['scene']}_{ep['summary'][:50]}"
            h = hash(key)
            if h not in seen_hashes:
                seen_hashes.add(h)
                deduped.append(ep)

        return deduped

    @staticmethod
    def compress_knowledge(knowledge: list[str], max_items: int = 20) -> list[str]:
        """Compress a knowledge list by removing redundant entries."""
        if len(knowledge) <= max_items:
            return knowledge

        # Remove exact duplicates
        seen: set[str] = set()
        unique: list[str] = []
        for item in knowledge:
            normalized = item.strip().lower()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(item)

        # If still too many, keep most recent
        if len(unique) > max_items:
            unique = unique[-max_items:]

        return unique

    @staticmethod
    def merge_timeline_events(events: list[dict[str, Any]],
                              max_events: int = 50) -> list[dict[str, Any]]:
        """Merge timeline events if they exceed max."""
        if len(events) <= max_events:
            return events
        # Keep first 5 and last (max-5) for continuity
        return events[:5] + events[-(max_events - 5):]
