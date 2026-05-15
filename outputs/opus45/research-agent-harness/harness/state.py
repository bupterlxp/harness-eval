"""State Store (S) - Maintains research state with persistence support.

Components:
- EvidenceStore: Manages sources and extracted evidence with traceability
- CitationMapper: Maintains citation numbering consistency
- DraftManager: Manages section drafts with incremental updates
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

from harness.schemas import (
    Source,
    Evidence,
    Citation,
    Section,
    SectionStatus,
    SourceReliability,
    ResearchState,
)


class EvidenceStore:
    """Manages sources and extracted evidence with full traceability."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._evidence: dict[str, Evidence] = {}
        self._source_to_evidence: dict[str, list[str]] = {}
        self._section_to_evidence: dict[str, list[str]] = {}

    def add_source(self, source: Source) -> str:
        """Add a source to the store."""
        if not source.id:
            source.id = f"src_{uuid.uuid4().hex[:8]}"
        self._sources[source.id] = source
        self._source_to_evidence[source.id] = []
        return source.id

    def get_source(self, source_id: str) -> Optional[Source]:
        """Get a source by ID."""
        return self._sources.get(source_id)

    def get_source_by_url(self, url: str) -> Optional[Source]:
        """Get a source by URL (for deduplication)."""
        for source in self._sources.values():
            if source.url == url:
                return source
        return None

    def get_all_sources(self) -> list[Source]:
        """Get all sources sorted by overall score."""
        return sorted(
            self._sources.values(),
            key=lambda s: s.overall_score,
            reverse=True
        )

    def get_evaluated_sources(self) -> list[Source]:
        """Get only evaluated sources."""
        return [s for s in self._sources.values() if s.evaluated]

    def add_evidence(self, evidence: Evidence) -> str:
        """Add evidence with source linkage."""
        if not evidence.id:
            evidence.id = f"ev_{uuid.uuid4().hex[:8]}"

        self._evidence[evidence.id] = evidence

        if evidence.source_id in self._source_to_evidence:
            self._source_to_evidence[evidence.source_id].append(evidence.id)

        if evidence.target_section not in self._section_to_evidence:
            self._section_to_evidence[evidence.target_section] = []
        self._section_to_evidence[evidence.target_section].append(evidence.id)

        return evidence.id

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        """Get evidence by ID."""
        return self._evidence.get(evidence_id)

    def get_evidence_for_source(self, source_id: str) -> list[Evidence]:
        """Get all evidence extracted from a source."""
        evidence_ids = self._source_to_evidence.get(source_id, [])
        return [self._evidence[eid] for eid in evidence_ids if eid in self._evidence]

    def get_evidence_for_section(self, section_name: str) -> list[Evidence]:
        """Get all evidence for a section."""
        evidence_ids = self._section_to_evidence.get(section_name, [])
        return [self._evidence[eid] for eid in evidence_ids if eid in self._evidence]

    def trace_evidence_to_source(self, evidence_id: str) -> tuple[Optional[Evidence], Optional[Source]]:
        """Trace evidence back to its source (for provenance)."""
        evidence = self._evidence.get(evidence_id)
        if not evidence:
            return None, None
        source = self._sources.get(evidence.source_id)
        return evidence, source

    def get_source_count(self) -> int:
        """Get total number of sources."""
        return len(self._sources)

    def get_evidence_count(self) -> int:
        """Get total number of evidence items."""
        return len(self._evidence)

    def to_snapshot(self) -> dict:
        """Create a full snapshot for persistence."""
        return {
            "sources": {k: self._source_to_dict(v) for k, v in self._sources.items()},
            "evidence": {k: self._evidence_to_dict(v) for k, v in self._evidence.items()},
            "source_to_evidence": self._source_to_evidence,
            "section_to_evidence": self._section_to_evidence,
        }

    def _source_to_dict(self, source: Source) -> dict:
        """Convert source to dict for serialization."""
        return {
            "id": source.id,
            "url": source.url,
            "title": source.title,
            "content": source.content,
            "reliability": source.reliability.value,
            "relevance_score": source.relevance_score,
            "timeliness_score": source.timeliness_score,
            "overall_score": source.overall_score,
            "fetched_at": source.fetched_at.isoformat(),
            "evaluated": source.evaluated,
        }

    def _evidence_to_dict(self, evidence: Evidence) -> dict:
        """Convert evidence to dict for serialization."""
        return {
            "id": evidence.id,
            "source_id": evidence.source_id,
            "content": evidence.content,
            "source_paragraph": evidence.source_paragraph,
            "target_section": evidence.target_section,
            "related_questions": evidence.related_questions,
            "confidence": evidence.confidence,
            "cross_validated": evidence.cross_validated,
            "validation_sources": evidence.validation_sources,
            "extracted_at": evidence.extracted_at.isoformat(),
        }


class CitationMapper:
    """Maintains citation numbering consistency throughout the report."""

    def __init__(self) -> None:
        self._citations: dict[str, Citation] = {}
        self._source_to_citation: dict[str, str] = {}
        self._number_to_citation: dict[int, str] = {}
        self._next_number: int = 1

    def add_citation(self, source: Source, authors: str, year: str,
                     title: str, venue: str) -> Citation:
        """Add a citation for a source, maintaining consistent numbering."""
        if source.id in self._source_to_citation:
            return self._citations[self._source_to_citation[source.id]]

        citation = Citation(
            id=f"cite_{uuid.uuid4().hex[:8]}",
            source_id=source.id,
            citation_number=self._next_number,
            authors=authors,
            year=year,
            title=title,
            venue=venue,
            url=source.url,
        )
        citation.format_citation()

        self._citations[citation.id] = citation
        self._source_to_citation[source.id] = citation.id
        self._number_to_citation[self._next_number] = citation.id
        self._next_number += 1

        return citation

    def get_citation_number(self, source_id: str) -> Optional[int]:
        """Get citation number for a source."""
        citation_id = self._source_to_citation.get(source_id)
        if citation_id:
            return self._citations[citation_id].citation_number
        return None

    def get_citation_by_number(self, number: int) -> Optional[Citation]:
        """Get citation by its number."""
        citation_id = self._number_to_citation.get(number)
        if citation_id:
            return self._citations[citation_id]
        return None

    def get_citation_for_source(self, source_id: str) -> Optional[Citation]:
        """Get citation for a source."""
        citation_id = self._source_to_citation.get(source_id)
        if citation_id:
            return self._citations[citation_id]
        return None

    def get_all_citations(self) -> list[Citation]:
        """Get all citations in order."""
        return sorted(
            self._citations.values(),
            key=lambda c: c.citation_number
        )

    def validate_citations(self, text: str) -> list[int]:
        """Check for broken citation references in text."""
        import re
        broken = []
        matches = re.findall(r'\[(\d+)\]', text)
        for match in matches:
            num = int(match)
            if num not in self._number_to_citation:
                broken.append(num)
        return broken

    def get_citation_count(self) -> int:
        """Get total number of citations."""
        return len(self._citations)

    def format_reference_list(self) -> str:
        """Generate formatted reference list."""
        citations = self.get_all_citations()
        lines = []
        for citation in citations:
            lines.append(f"{citation.citation_number}. {citation.formatted}")
        return "\n".join(lines)


class DraftManager:
    """Manages section drafts with incremental updates."""

    def __init__(self, required_sections: list[str]) -> None:
        self._sections: dict[str, Section] = {}
        self._section_order = required_sections

        section_titles = {
            "摘要": "摘要",
            "背景与动机": "1. 背景与动机",
            "主流模型对比": "2. 主流模型对比",
            "关键技术进展": "3. 关键技术进展",
            "当前挑战": "4. 当前挑战",
            "未来方向": "5. 未来方向",
            "参考文献": "参考文献",
        }

        for section_name in required_sections:
            self._sections[section_name] = Section(
                name=section_name,
                title=section_titles.get(section_name, section_name),
            )

    def update_section(self, section_name: str, content: str,
                       evidence_ids: list[str], citation_ids: list[str]) -> None:
        """Update a section's content."""
        if section_name not in self._sections:
            return

        section = self._sections[section_name]
        section.content = content
        section.evidence_ids = evidence_ids
        section.citation_ids = citation_ids
        section.update_status()

    def get_section(self, section_name: str) -> Optional[Section]:
        """Get a section by name."""
        return self._sections.get(section_name)

    def get_all_sections(self) -> list[Section]:
        """Get all sections in order."""
        return [self._sections[name] for name in self._section_order
                if name in self._sections]

    def get_section_status(self) -> dict[str, SectionStatus]:
        """Get status of all sections."""
        return {name: section.status for name, section in self._sections.items()}

    def get_incomplete_sections(self) -> list[str]:
        """Get names of incomplete sections."""
        return [name for name, section in self._sections.items()
                if section.status != SectionStatus.COMPLETE]

    def get_total_word_count(self) -> int:
        """Get total word count across all sections."""
        return sum(section.word_count for section in self._sections.values())

    def generate_report(self) -> str:
        """Generate the full report from sections."""
        lines = []
        for section in self.get_all_sections():
            if section.content:
                if section.name == "摘要":
                    lines.append(f"## {section.title}\n")
                elif section.name == "参考文献":
                    lines.append(f"\n## {section.title}\n")
                else:
                    lines.append(f"\n## {section.title}\n")
                lines.append(section.content)
                lines.append("")
        return "\n".join(lines)

    def get_outline(self) -> dict[str, dict]:
        """Get current outline with completion status."""
        outline = {}
        for section in self.get_all_sections():
            outline[section.name] = {
                "status": section.status.value,
                "word_count": section.word_count,
                "evidence_count": len(section.evidence_ids),
                "citation_count": len(section.citation_ids),
            }
        return outline


class StateStore:
    """Unified state store combining all state components."""

    def __init__(self, required_sections: list[str]) -> None:
        self.evidence_store = EvidenceStore()
        self.citation_mapper = CitationMapper()
        self.draft_manager = DraftManager(required_sections)
        self.current_state = ResearchState.DECOMPOSE
        self.hop_count = 0
        self.max_hops = 3

    def save_snapshot(self, path: Path) -> None:
        """Save full state snapshot to file."""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "current_state": self.current_state.value,
            "hop_count": self.hop_count,
            "evidence_store": self.evidence_store.to_snapshot(),
            "citations": [
                {
                    "id": c.id,
                    "source_id": c.source_id,
                    "citation_number": c.citation_number,
                    "authors": c.authors,
                    "year": c.year,
                    "title": c.title,
                    "venue": c.venue,
                    "url": c.url,
                    "formatted": c.formatted,
                }
                for c in self.citation_mapper.get_all_citations()
            ],
            "draft_outline": self.draft_manager.get_outline(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

    def get_summary(self) -> dict:
        """Get a summary of current state."""
        return {
            "state": self.current_state.value,
            "sources": self.evidence_store.get_source_count(),
            "evidence": self.evidence_store.get_evidence_count(),
            "citations": self.citation_mapper.get_citation_count(),
            "word_count": self.draft_manager.get_total_word_count(),
            "hops": self.hop_count,
            "sections": self.draft_manager.get_outline(),
        }
