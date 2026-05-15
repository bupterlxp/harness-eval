"""Context Manager (C) - Three-layer context management.

Components:
- EvidenceContext: Source → extracted_facts mapping with relevance scoring
- OutlineContext: Current section structure and content
- QueryHistory: Tracks executed queries to avoid duplication
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from harness.schemas import Evidence, Source, Section, ResearchQuery


@dataclass
class EvidenceContextEntry:
    """An entry in the evidence context with relevance metadata."""
    evidence: Evidence
    source: Source
    relevance_score: float
    in_active_context: bool = True
    demoted_at: Optional[datetime] = None


class EvidenceContext:
    """Manages evidence with relevance-based compression.

    Evidence is kept in active context while relevant. When context
    grows too large, low-relevance evidence is demoted to storage
    (still traceable but not included in active prompts).
    """

    def __init__(self, max_active_entries: int = 100, relevance_threshold: float = 0.5) -> None:
        self._entries: dict[str, EvidenceContextEntry] = {}
        self._section_entries: dict[str, list[str]] = {}
        self.max_active_entries = max_active_entries
        self.relevance_threshold = relevance_threshold

    def add_evidence(self, evidence: Evidence, source: Source, relevance_score: float) -> None:
        """Add evidence to context."""
        entry = EvidenceContextEntry(
            evidence=evidence,
            source=source,
            relevance_score=relevance_score,
            in_active_context=True,
        )
        self._entries[evidence.id] = entry

        section = evidence.target_section
        if section not in self._section_entries:
            self._section_entries[section] = []
        self._section_entries[section].append(evidence.id)

        self._compress_if_needed()

    def get_active_evidence(self) -> list[EvidenceContextEntry]:
        """Get all evidence in active context."""
        return [e for e in self._entries.values() if e.in_active_context]

    def get_evidence_for_section(self, section: str) -> list[EvidenceContextEntry]:
        """Get evidence for a specific section."""
        evidence_ids = self._section_entries.get(section, [])
        return [self._entries[eid] for eid in evidence_ids
                if eid in self._entries and self._entries[eid].in_active_context]

    def get_all_evidence_for_section(self, section: str) -> list[EvidenceContextEntry]:
        """Get all evidence for section including demoted."""
        evidence_ids = self._section_entries.get(section, [])
        return [self._entries[eid] for eid in evidence_ids if eid in self._entries]

    def update_relevance(self, evidence_id: str, new_score: float) -> None:
        """Update relevance score for evidence."""
        if evidence_id in self._entries:
            self._entries[evidence_id].relevance_score = new_score
            if new_score >= self.relevance_threshold:
                self._entries[evidence_id].in_active_context = True
                self._entries[evidence_id].demoted_at = None

    def _compress_if_needed(self) -> None:
        """Demote low-relevance evidence if context is too large."""
        active = [e for e in self._entries.values() if e.in_active_context]
        if len(active) <= self.max_active_entries:
            return

        sorted_entries = sorted(active, key=lambda e: e.relevance_score)
        to_demote = len(active) - self.max_active_entries

        for entry in sorted_entries[:to_demote]:
            if entry.relevance_score < self.relevance_threshold:
                entry.in_active_context = False
                entry.demoted_at = datetime.now()

    def get_context_summary(self) -> dict:
        """Get summary of context state."""
        active = sum(1 for e in self._entries.values() if e.in_active_context)
        demoted = len(self._entries) - active
        return {
            "total_entries": len(self._entries),
            "active_entries": active,
            "demoted_entries": demoted,
            "sections": {
                section: len(ids)
                for section, ids in self._section_entries.items()
            },
        }


@dataclass
class OutlineEntry:
    """Entry for a section in the outline context."""
    section: Section
    current_focus: bool = False
    last_updated: Optional[datetime] = None


class OutlineContext:
    """Manages current outline structure and section focus."""

    def __init__(self, required_sections: list[str]) -> None:
        self._outline: dict[str, OutlineEntry] = {}
        self._section_order = required_sections
        self._current_focus: Optional[str] = None

        for section_name in required_sections:
            self._outline[section_name] = OutlineEntry(
                section=Section(name=section_name, title=section_name)
            )

    def set_focus(self, section_name: str) -> None:
        """Set the current focus section."""
        if self._current_focus and self._current_focus in self._outline:
            self._outline[self._current_focus].current_focus = False

        if section_name in self._outline:
            self._outline[section_name].current_focus = True
            self._current_focus = section_name

    def get_focus(self) -> Optional[str]:
        """Get current focus section."""
        return self._current_focus

    def update_section(self, section: Section) -> None:
        """Update a section in the outline."""
        if section.name in self._outline:
            self._outline[section.name].section = section
            self._outline[section.name].last_updated = datetime.now()

    def get_section(self, section_name: str) -> Optional[Section]:
        """Get a section from the outline."""
        if section_name in self._outline:
            return self._outline[section_name].section
        return None

    def get_outline_status(self) -> list[dict]:
        """Get status of all sections in order."""
        result = []
        for name in self._section_order:
            if name in self._outline:
                entry = self._outline[name]
                result.append({
                    "name": name,
                    "status": entry.section.status.value,
                    "word_count": entry.section.word_count,
                    "evidence_count": len(entry.section.evidence_ids),
                    "is_focus": entry.current_focus,
                })
        return result

    def get_next_incomplete_section(self) -> Optional[str]:
        """Get the next section that needs work."""
        for name in self._section_order:
            if name in self._outline:
                section = self._outline[name].section
                if section.status.value != "complete":
                    return name
        return None


@dataclass
class QueryHistoryEntry:
    """Entry in query history."""
    query: ResearchQuery
    executed_at: datetime
    result_count: int
    source_ids: list[str] = field(default_factory=list)


class QueryHistory:
    """Tracks executed queries to avoid duplication."""

    def __init__(self) -> None:
        self._queries: dict[str, QueryHistoryEntry] = {}
        self._query_texts: set[str] = set()
        self._section_queries: dict[str, list[str]] = {}

    def add_query(self, query: ResearchQuery, result_count: int,
                  source_ids: list[str]) -> None:
        """Record an executed query."""
        entry = QueryHistoryEntry(
            query=query,
            executed_at=datetime.now(),
            result_count=result_count,
            source_ids=source_ids,
        )
        self._queries[query.id] = entry
        self._query_texts.add(self._normalize_query(query.query_text))

        section = query.target_section
        if section not in self._section_queries:
            self._section_queries[section] = []
        self._section_queries[section].append(query.id)

    def is_duplicate(self, query_text: str) -> bool:
        """Check if a similar query was already executed."""
        normalized = self._normalize_query(query_text)
        return normalized in self._query_texts

    def get_queries_for_section(self, section: str) -> list[QueryHistoryEntry]:
        """Get all queries executed for a section."""
        query_ids = self._section_queries.get(section, [])
        return [self._queries[qid] for qid in query_ids if qid in self._queries]

    def get_total_queries(self) -> int:
        """Get total number of executed queries."""
        return len(self._queries)

    def get_total_sources_found(self) -> int:
        """Get total unique sources found across all queries."""
        all_sources = set()
        for entry in self._queries.values():
            all_sources.update(entry.source_ids)
        return len(all_sources)

    def _normalize_query(self, query_text: str) -> str:
        """Normalize query for comparison."""
        return " ".join(query_text.lower().split())

    def get_history_summary(self) -> dict:
        """Get summary of query history."""
        return {
            "total_queries": len(self._queries),
            "unique_query_texts": len(self._query_texts),
            "queries_by_section": {
                section: len(ids)
                for section, ids in self._section_queries.items()
            },
        }


class ContextManager:
    """Unified context manager combining all three layers."""

    def __init__(self, required_sections: list[str],
                 max_evidence_entries: int = 100,
                 relevance_threshold: float = 0.5) -> None:
        self.evidence = EvidenceContext(max_evidence_entries, relevance_threshold)
        self.outline = OutlineContext(required_sections)
        self.history = QueryHistory()

    def get_context_summary(self) -> dict:
        """Get summary of all context layers."""
        return {
            "evidence": self.evidence.get_context_summary(),
            "outline": self.outline.get_outline_status(),
            "history": self.history.get_history_summary(),
        }

    def get_active_context_for_section(self, section: str) -> dict:
        """Get all active context relevant to a section."""
        evidence_entries = self.evidence.get_evidence_for_section(section)
        section_obj = self.outline.get_section(section)
        queries = self.history.get_queries_for_section(section)

        return {
            "section": section_obj,
            "evidence": [
                {
                    "content": e.evidence.content,
                    "source_url": e.source.url,
                    "source_title": e.source.title,
                    "relevance": e.relevance_score,
                }
                for e in evidence_entries
            ],
            "queries_executed": len(queries),
        }
