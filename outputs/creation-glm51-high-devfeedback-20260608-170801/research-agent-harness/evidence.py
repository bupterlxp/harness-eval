"""Evidence manager: tracking, deduplication, contradiction detection, context compression.

Called by generated_program.py to manage evidence items collected during research.
Pure logic — no I/O, no LLM calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class EvidenceItem:
    id: str
    query: str
    url: str
    title: str
    excerpt: str
    why_relevant: str = ""
    supports: str = ""
    contradicts: str = ""
    source_type: str = "web"
    retrieval_time: float = 0.0
    relevance_score: float = 0.0


@dataclass
class EvidenceStore:
    items: list[EvidenceItem] = field(default_factory=list)
    _url_index: dict[str, str] = field(default_factory=dict)
    _next_id: int = 0

    def add(
        self,
        *,
        query: str,
        url: str,
        title: str,
        excerpt: str,
        why_relevant: str = "",
        supports: str = "",
        contradicts: str = "",
        source_type: str = "web",
        retrieval_time: float = 0.0,
        relevance_score: float = 0.0,
    ) -> EvidenceItem:
        canonical = _canonical_url(url)
        if canonical in self._url_index:
            existing_id = self._url_index[canonical]
            for item in self.items:
                if item.id == existing_id:
                    if len(excerpt) > len(item.excerpt):
                        item.excerpt = excerpt
                    if title and not item.title:
                        item.title = title
                    item.relevance_score = max(item.relevance_score, relevance_score)
                    return item
        self._next_id += 1
        eid = f"E{self._next_id:03d}"
        item = EvidenceItem(
            id=eid,
            query=query,
            url=url,
            title=title,
            excerpt=excerpt,
            why_relevant=why_relevant,
            supports=supports,
            contradicts=contradicts,
            source_type=source_type,
            retrieval_time=retrieval_time,
            relevance_score=relevance_score,
        )
        self.items.append(item)
        self._url_index[canonical] = eid
        return item

    def search_results_to_evidence(
        self,
        query: str,
        results: list[dict[str, Any]],
        retrieval_time: float = 0.0,
    ) -> list[EvidenceItem]:
        added: list[EvidenceItem] = []
        for r in results:
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            title = r.get("title", "")
            if not url:
                continue
            item = self.add(
                query=query,
                url=url,
                title=title,
                excerpt=snippet,
                why_relevant=f"Retrieved for query: {query}",
                retrieval_time=retrieval_time,
                relevance_score=0.5,
            )
            added.append(item)
        return added

    def get_top(self, n: int = 10) -> list[EvidenceItem]:
        scored = sorted(self.items, key=lambda x: x.relevance_score, reverse=True)
        return scored[:n]

    def compress_for_context(self, max_chars: int = 12000) -> str:
        if not self.items:
            return "No evidence collected."
        top = self.get_top(10)
        parts: list[str] = []
        total = 0
        for item in top:
            entry = f"[{item.id}] {item.title}\n  URL: {item.url}\n  Excerpt: {item.excerpt[:500]}"
            if item.supports:
                entry += f"\n  Supports: {item.supports}"
            if item.contradicts:
                entry += f"\n  Contradicts: {item.contradicts}"
            if total + len(entry) > max_chars:
                break
            parts.append(entry)
            total += len(entry)
        return "\n\n".join(parts)

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "query": item.query,
                "url": item.url,
                "title": item.title,
                "excerpt": item.excerpt,
                "why_relevant": item.why_relevant,
                "supports": item.supports,
                "contradicts": item.contradicts,
                "source_type": item.source_type,
                "retrieval_time": item.retrieval_time,
                "relevance_score": item.relevance_score,
            }
            for item in self.items
        ]

    def find_contradictions(self) -> list[dict[str, Any]]:
        contradictions: list[dict[str, Any]] = []
        for i, item_a in enumerate(self.items):
            for item_b in self.items[i + 1:]:
                if item_a.contradicts and item_b.id in item_a.contradicts:
                    contradictions.append({
                        "item_a": item_a.id,
                        "item_b": item_b.id,
                        "nature": item_a.contradicts,
                    })
                elif item_b.contradicts and item_a.id in item_b.contradicts:
                    contradictions.append({
                        "item_a": item_b.id,
                        "item_b": item_a.id,
                        "nature": item_b.contradicts,
                    })
        return contradictions


def score_relevance(question: str, item: EvidenceItem) -> float:
    q_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", question.lower()))
    excerpt_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", item.excerpt.lower()))
    title_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", item.title.lower()))
    if not q_words:
        return 0.5
    excerpt_overlap = len(q_words & excerpt_words) / len(q_words)
    title_overlap = len(q_words & title_words) / len(q_words)
    domain_score = 0.0
    domain = _domain_of(item.url)
    trusted = {".gov", ".edu", ".org", "wikipedia.org", "nature.com", "science.org", "arxiv.org"}
    for t in trusted:
        if t in domain:
            domain_score = 0.15
            break
    return min(1.0, 0.4 * excerpt_overlap + 0.3 * title_overlap + domain_score + 0.1 * min(1.0, len(item.excerpt) / 200))


def _canonical_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        return (parsed.netloc.lower().rstrip("/") + "/" + parsed.path.strip("/")).rstrip("/")
    except Exception:
        return url.lower().strip()


def _domain_of(url: str) -> str:
    try:
        return (urlsplit(url).netloc or "").lower()
    except Exception:
        return ""
