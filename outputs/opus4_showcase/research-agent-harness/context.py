"""Context Manager - context management and compression with token budget.

Manages the evidence context window with a hard word limit (25000 words).
Implements dynamic truncation of lowest-relevance evidence when exceeded,
and auto-summarization to compress context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from harness.state import AgentState, EvidenceCard
from harness.tools import ToolRegistry, ToolResult


WORD_LIMIT = 25000
CHUNK_SIZE = 1000  # characters per chunk
CHUNK_OVERLAP = 100  # character overlap between chunks


@dataclass
class ContextBudget:
    """Tracks context budget usage."""
    max_words: int = WORD_LIMIT
    current_words: int = 0
    num_cards: int = 0
    truncated_count: int = 0
    summarized_count: int = 0

    @property
    def utilization(self) -> float:
        if self.max_words == 0:
            return 0.0
        return self.current_words / self.max_words

    @property
    def remaining_words(self) -> int:
        return max(0, self.max_words - self.current_words)


class ContextManager:
    """Manages evidence context within token budget constraints."""

    def __init__(self, state: AgentState, registry: ToolRegistry):
        self._state = state
        self._registry = registry
        self._budget = ContextBudget()
        self._recalculate_budget()

    @property
    def budget(self) -> ContextBudget:
        self._recalculate_budget()
        return self._budget

    def _recalculate_budget(self) -> None:
        """Recalculate current word usage."""
        total = 0
        for card in self._state.evidence_cards:
            total += len(card.content.split())
        self._budget.current_words = total
        self._budget.num_cards = len(self._state.evidence_cards)

    def is_over_budget(self) -> bool:
        """Check if current context exceeds word limit."""
        self._recalculate_budget()
        return self._budget.current_words > self._budget.max_words

    def add_evidence(self, card: EvidenceCard) -> bool:
        """Add an evidence card, triggering truncation if over budget.

        Returns True if card was added, False if it was a duplicate.
        """
        # URL deduplication check
        if card.source_url in self._state.visited_urls:
            # Check if exact same chunk
            for existing in self._state.evidence_cards:
                if existing.uid == card.uid:
                    return False

        self._state.evidence_cards.append(card)
        self._state.visited_urls.add(card.source_url)
        self._recalculate_budget()

        # Trigger truncation if over budget
        if self.is_over_budget():
            self._truncate_lowest_relevance()

        return True

    def _truncate_lowest_relevance(self) -> None:
        """Remove lowest-quality evidence cards until within budget."""
        while self.is_over_budget() and len(self._state.evidence_cards) > 1:
            # Find card with lowest quality score
            min_idx = 0
            min_score = self._state.evidence_cards[0].quality_score
            for i, card in enumerate(self._state.evidence_cards):
                if card.quality_score < min_score:
                    min_score = card.quality_score
                    min_idx = i

            removed = self._state.evidence_cards.pop(min_idx)
            self._budget.truncated_count += 1
            self._recalculate_budget()

    async def compress_context(self) -> None:
        """Summarize long evidence cards to free up budget space."""
        # Sort by content length descending, summarize longest cards first
        cards_by_length = sorted(
            enumerate(self._state.evidence_cards),
            key=lambda x: len(x[1].content.split()),
            reverse=True,
        )

        for idx, card in cards_by_length:
            if not self.is_over_budget():
                break
            word_count = len(card.content.split())
            if word_count < 100:
                continue  # Already short

            # Summarize via LLM
            result = await self._registry.dispatch(
                "llm_generate",
                messages=[
                    {
                        "role": "system",
                        "content": "Summarize the following text concisely, preserving key facts and data points. Keep to 1/3 of original length.",
                    },
                    {"role": "user", "content": card.content},
                ],
                temperature=0.2,
                max_tokens=500,
            )

            if result.success and result.data.get("content"):
                self._state.evidence_cards[idx].content = result.data["content"]
                self._budget.summarized_count += 1
                self._recalculate_budget()

    def build_context_window(self, include_metadata: bool = True) -> str:
        """Build the context string for LLM consumption.

        Returns formatted evidence context within budget.
        """
        self._recalculate_budget()
        parts: list[str] = []

        if include_metadata:
            parts.append(
                f"[Context: {self._budget.current_words}/{self._budget.max_words} words, "
                f"{self._budget.num_cards} evidence cards]\n"
            )

        # Sort by quality score descending for priority
        sorted_cards = sorted(
            self._state.evidence_cards,
            key=lambda c: c.quality_score,
            reverse=True,
        )

        for card in sorted_cards:
            entry = (
                f"--- Evidence [{card.uid}] ---\n"
                f"Title: {card.title}\n"
                f"Source: {card.source_url}\n"
                f"Summary: {card.summary}\n"
                f"Tags: {', '.join(card.tags)}\n"
                f"Quality: {card.quality_score:.2f}\n"
                f"Content:\n{card.content}\n"
            )
            if card.contradicts:
                entry += f"Contradicts: {', '.join(card.contradicts)}\n"
            parts.append(entry)

        return "\n".join(parts)

    def get_near_limit_reminder(self) -> str | None:
        """Return a reminder message if near round/context limits."""
        self._recalculate_budget()
        messages = []

        if self._budget.utilization > 0.85:
            messages.append(
                "WARNING: Context is at {:.0%} capacity. Prioritize completing key evidence collection.".format(
                    self._budget.utilization
                )
            )

        rounds_remaining = self._state.max_rounds - self._state.current_round
        if rounds_remaining <= 1:
            messages.append(
                "NOTICE: This is the final retrieval round. Focus on filling critical evidence gaps."
            )

        return "\n".join(messages) if messages else None

    def get_contradiction_summary(self) -> str:
        """Build a summary of contradicting evidence."""
        contradictions: list[tuple[EvidenceCard, EvidenceCard]] = []
        card_map = {c.uid: c for c in self._state.evidence_cards}

        for card in self._state.evidence_cards:
            for contra_uid in card.contradicts:
                if contra_uid in card_map:
                    contradictions.append((card, card_map[contra_uid]))

        if not contradictions:
            return ""

        parts = ["## Contradicting Sources\n"]
        seen = set()
        for a, b in contradictions:
            pair_key = tuple(sorted([a.uid, b.uid]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            parts.append(
                f"- **Disagreement**: {a.title} vs {b.title}\n"
                f"  - Position A [{a.uid}]: {a.summary}\n"
                f"    Source: {a.source_url}\n"
                f"  - Position B [{b.uid}]: {b.summary}\n"
                f"    Source: {b.source_url}\n"
            )

        return "\n".join(parts)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count.

    Args:
        text: Text to split
        chunk_size: Maximum characters per chunk
        overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at sentence boundary
        if end < len(text):
            last_period = chunk.rfind(". ")
            last_newline = chunk.rfind("\n")
            break_point = max(last_period, last_newline)
            if break_point > chunk_size * 0.5:
                chunk = text[start : start + break_point + 1]
                end = start + break_point + 1

        chunks.append(chunk.strip())
        start = end - overlap

    return [c for c in chunks if c]  # Filter empty chunks


def compute_relevance_score(chunk: str, query: str) -> float:
    """Compute a simple relevance score between a chunk and query.

    Uses keyword overlap as a basic heuristic. For production,
    this would use embeddings or LLM-based scoring.
    """
    query_terms = set(re.findall(r"\w+", query.lower()))
    chunk_terms = set(re.findall(r"\w+", chunk.lower()))

    if not query_terms:
        return 0.0

    overlap = query_terms & chunk_terms
    score = len(overlap) / len(query_terms)

    # Boost for exact phrase matches
    query_lower = query.lower()
    chunk_lower = chunk.lower()
    if query_lower in chunk_lower:
        score = min(1.0, score + 0.3)

    return min(1.0, score)
