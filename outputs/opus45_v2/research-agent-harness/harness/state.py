"""State Store (S) - Maintains persistent research state with incremental updates."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json
from pathlib import Path


@dataclass
class Source:
    """A research source with metadata."""
    id: int
    url: str
    title: str
    credibility: str  # "high" | "medium" | "low"
    content: str = ""
    retrieved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "credibility": self.credibility,
            "content": self.content,
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Source:
        return cls(**data)


@dataclass
class Fact:
    """An extracted fact with provenance."""
    id: int
    content: str
    source_id: int
    confidence: float = 1.0
    verified_by: list[int] = field(default_factory=list)
    contradicted_by: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "verified_by": self.verified_by,
            "contradicted_by": self.contradicted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        return cls(**data)


@dataclass
class SectionDraft:
    """A draft section of the report."""
    name: str
    content: str
    citations: list[int] = field(default_factory=list)
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content": self.content,
            "citations": self.citations,
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectionDraft:
        return cls(**data)


@dataclass
class CitationMapping:
    """Maps inline citation numbers to source IDs."""
    inline_number: int
    source_id: int
    fact_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inline_number": self.inline_number,
            "source_id": self.source_id,
            "fact_ids": self.fact_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CitationMapping:
        return cls(**data)


class StateStore:
    """Persistent state store for research progress."""

    def __init__(self, output_dir: str | Path | None = None):
        self.output_dir = Path(output_dir) if output_dir else None
        self._sources: dict[int, Source] = {}
        self._facts: dict[int, Fact] = {}
        self._section_drafts: dict[str, SectionDraft] = {}
        self._citation_mappings: dict[int, CitationMapping] = {}
        self._seen_urls: set[str] = set()
        self._queries_executed: list[str] = []
        self._current_hop: int = 0
        self._gaps: list[str] = []
        self._next_source_id: int = 1
        self._next_fact_id: int = 1
        self._next_citation_number: int = 1

    @property
    def sources(self) -> list[Source]:
        return list(self._sources.values())

    @property
    def facts(self) -> list[Fact]:
        return list(self._facts.values())

    @property
    def section_drafts(self) -> list[SectionDraft]:
        return list(self._section_drafts.values())

    @property
    def citation_mappings(self) -> list[CitationMapping]:
        return list(self._citation_mappings.values())

    @property
    def seen_urls(self) -> set[str]:
        return self._seen_urls.copy()

    @property
    def current_hop(self) -> int:
        return self._current_hop

    @property
    def gaps(self) -> list[str]:
        return self._gaps.copy()

    def is_url_seen(self, url: str) -> bool:
        normalized = self._normalize_url(url)
        return normalized in self._seen_urls

    def _normalize_url(self, url: str) -> str:
        url = url.rstrip("/")
        if url.startswith("http://"):
            url = url[7:]
        elif url.startswith("https://"):
            url = url[8:]
        return url.lower()

    def add_source(self, url: str, title: str, credibility: str, content: str = "", retrieved_at: str = "") -> Source | None:
        """Add a source if not already seen. Returns None if duplicate."""
        normalized = self._normalize_url(url)
        if normalized in self._seen_urls:
            return None

        self._seen_urls.add(normalized)
        source = Source(
            id=self._next_source_id,
            url=url,
            title=title,
            credibility=credibility,
            content=content,
            retrieved_at=retrieved_at,
        )
        self._sources[source.id] = source
        self._next_source_id += 1
        self._save_checkpoint()
        return source

    def get_source(self, source_id: int) -> Source | None:
        return self._sources.get(source_id)

    def get_source_by_url(self, url: str) -> Source | None:
        normalized = self._normalize_url(url)
        for source in self._sources.values():
            if self._normalize_url(source.url) == normalized:
                return source
        return None

    def add_fact(self, content: str, source_id: int, confidence: float = 1.0) -> Fact:
        """Add an extracted fact with provenance."""
        fact = Fact(
            id=self._next_fact_id,
            content=content,
            source_id=source_id,
            confidence=confidence,
        )
        self._facts[fact.id] = fact
        self._next_fact_id += 1
        self._save_checkpoint()
        return fact

    def get_fact(self, fact_id: int) -> Fact | None:
        return self._facts.get(fact_id)

    def get_facts_for_source(self, source_id: int) -> list[Fact]:
        return [f for f in self._facts.values() if f.source_id == source_id]

    def mark_fact_verified(self, fact_id: int, verifying_source_id: int) -> None:
        """Mark a fact as verified by another source."""
        if fact_id in self._facts:
            self._facts[fact_id].verified_by.append(verifying_source_id)
            self._save_checkpoint()

    def mark_fact_contradicted(self, fact_id: int, contradicting_source_id: int) -> None:
        """Mark a fact as contradicted by another source."""
        if fact_id in self._facts:
            self._facts[fact_id].contradicted_by.append(contradicting_source_id)
            self._save_checkpoint()

    def add_section_draft(self, name: str, content: str = "", citations: list[int] | None = None) -> SectionDraft:
        """Add or update a section draft."""
        draft = SectionDraft(
            name=name,
            content=content,
            citations=citations or [],
        )
        self._section_drafts[name] = draft
        self._save_checkpoint()
        return draft

    def update_section_draft(self, name: str, content: str, citations: list[int] | None = None, complete: bool = False) -> SectionDraft | None:
        """Update an existing section draft."""
        if name not in self._section_drafts:
            return None
        draft = self._section_drafts[name]
        draft.content = content
        if citations is not None:
            draft.citations = citations
        draft.complete = complete
        self._save_checkpoint()
        return draft

    def get_section_draft(self, name: str) -> SectionDraft | None:
        return self._section_drafts.get(name)

    def add_citation_mapping(self, source_id: int, fact_ids: list[int] | None = None) -> CitationMapping:
        """Create a citation mapping for inline references."""
        mapping = CitationMapping(
            inline_number=self._next_citation_number,
            source_id=source_id,
            fact_ids=fact_ids or [],
        )
        self._citation_mappings[mapping.inline_number] = mapping
        self._next_citation_number += 1
        self._save_checkpoint()
        return mapping

    def get_citation_mapping(self, inline_number: int) -> CitationMapping | None:
        return self._citation_mappings.get(inline_number)

    def get_citation_for_source(self, source_id: int) -> CitationMapping | None:
        """Get existing citation mapping for a source."""
        for mapping in self._citation_mappings.values():
            if mapping.source_id == source_id:
                return mapping
        return None

    def record_query(self, query: str) -> None:
        """Record an executed query."""
        self._queries_executed.append(query)
        self._save_checkpoint()

    def increment_hop(self) -> int:
        """Increment and return the current hop count."""
        self._current_hop += 1
        self._save_checkpoint()
        return self._current_hop

    def add_gap(self, gap: str) -> None:
        """Record an unanswered sub-question."""
        if gap not in self._gaps:
            self._gaps.append(gap)
            self._save_checkpoint()

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to dictionary."""
        return {
            "sources": [s.to_dict() for s in self._sources.values()],
            "facts": [f.to_dict() for f in self._facts.values()],
            "section_drafts": [d.to_dict() for d in self._section_drafts.values()],
            "citation_mappings": [m.to_dict() for m in self._citation_mappings.values()],
            "seen_urls": list(self._seen_urls),
            "queries_executed": self._queries_executed,
            "current_hop": self._current_hop,
            "gaps": self._gaps,
            "next_source_id": self._next_source_id,
            "next_fact_id": self._next_fact_id,
            "next_citation_number": self._next_citation_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], output_dir: str | Path | None = None) -> StateStore:
        """Deserialize state from dictionary."""
        store = cls(output_dir)
        store._sources = {s["id"]: Source.from_dict(s) for s in data.get("sources", [])}
        store._facts = {f["id"]: Fact.from_dict(f) for f in data.get("facts", [])}
        store._section_drafts = {d["name"]: SectionDraft.from_dict(d) for d in data.get("section_drafts", [])}
        store._citation_mappings = {m["inline_number"]: CitationMapping.from_dict(m) for m in data.get("citation_mappings", [])}
        store._seen_urls = set(data.get("seen_urls", []))
        store._queries_executed = data.get("queries_executed", [])
        store._current_hop = data.get("current_hop", 0)
        store._gaps = data.get("gaps", [])
        store._next_source_id = data.get("next_source_id", 1)
        store._next_fact_id = data.get("next_fact_id", 1)
        store._next_citation_number = data.get("next_citation_number", 1)
        return store

    def _save_checkpoint(self) -> None:
        """Save state to checkpoint file if output_dir is set."""
        if self.output_dir:
            checkpoint_path = self.output_dir / "state_checkpoint.json"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(checkpoint_path, "w") as f:
                json.dump(self.to_dict(), f, indent=2)

    def load_checkpoint(self) -> bool:
        """Load state from checkpoint file if it exists."""
        if not self.output_dir:
            return False
        checkpoint_path = self.output_dir / "state_checkpoint.json"
        if checkpoint_path.exists():
            with open(checkpoint_path) as f:
                data = json.load(f)
            loaded = StateStore.from_dict(data, self.output_dir)
            self._sources = loaded._sources
            self._facts = loaded._facts
            self._section_drafts = loaded._section_drafts
            self._citation_mappings = loaded._citation_mappings
            self._seen_urls = loaded._seen_urls
            self._queries_executed = loaded._queries_executed
            self._current_hop = loaded._current_hop
            self._gaps = loaded._gaps
            self._next_source_id = loaded._next_source_id
            self._next_fact_id = loaded._next_fact_id
            self._next_citation_number = loaded._next_citation_number
            return True
        return False
