import json
import os
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime
from .schemas import Source, Evidence, Citation, Section, ResearchState


class EvidenceStore:
    """Stores and manages extracted evidence from sources"""

    def __init__(self):
        self.evidence_by_source: Dict[str, List[Evidence]] = {}
        self.all_evidence: List[Evidence] = []

    def add_evidence(self, evidence: Evidence) -> None:
        """Add evidence to the store"""
        if evidence.source_url not in self.evidence_by_source:
            self.evidence_by_source[evidence.source_url] = []
        self.evidence_by_source[evidence.source_url].append(evidence)
        self.all_evidence.append(evidence)

    def get_evidence_for_source(self, source_url: str) -> List[Evidence]:
        """Get all evidence for a specific source"""
        return self.evidence_by_source.get(source_url, [])

    def get_all_evidence(self) -> List[Evidence]:
        """Get all evidence in the store"""
        return self.all_evidence

    def clear(self) -> None:
        """Clear all evidence"""
        self.evidence_by_source.clear()
        self.all_evidence.clear()


class CitationMapper:
    """Manages citation mapping and formatting"""

    def __init__(self, citation_format: str = "{authors}. {title}. {source}. {url}"):
        self.citation_format = citation_format
        self.source_to_citation_key: Dict[str, str] = {}
        self.citations: Dict[str, Citation] = {}
        self.next_id: int = 1

    def add_source(self, source: Source) -> str:
        """Add a source and generate a citation key"""
        if source.url in self.source_to_citation_key:
            return self.source_to_citation_key[source.url]

        citation_key = f"[{self.next_id}]"
        self.next_id += 1

        formatted = self._format_citation(source)
        citation = Citation(
            key=citation_key,
            source=source,
            formatted=formatted
        )

        self.source_to_citation_key[source.url] = citation_key
        self.citations[citation_key] = citation

        return citation_key

    def _format_citation(self, source: Source) -> str:
        """Format a source according to the citation format"""
        authors = " ".join(source.authors) if source.authors else "Unknown authors"
        year = source.year if source.year else "n.d."
        title = source.title or "Untitled"

        return self.citation_format.format(
            authors=authors,
            year=year,
            title=title,
            url=source.url
        )

    def get_citation_key(self, source_url: str) -> Optional[str]:
        """Get citation key for a source URL"""
        return self.source_to_citation_key.get(source_url)

    def get_citation(self, citation_key: str) -> Optional[Citation]:
        """Get citation by key"""
        return self.citations.get(citation_key)

    def get_all_citations(self) -> List[Citation]:
        """Get all citations in order"""
        sorted_keys = sorted(self.citations.keys(), key=lambda k: int(k.strip('[]')))
        return [self.citations[k] for k in sorted_keys]

    def clear(self) -> None:
        """Clear all citations"""
        self.source_to_citation_key.clear()
        self.citations.clear()
        self.next_id = 1


class DraftManager:
    """Manages report draft sections"""

    def __init__(self, required_sections: List[str]):
        self.required_sections = required_sections
        self.sections: Dict[str, Section] = {}

        for section_title in required_sections:
            self.sections[section_title] = Section(title=section_title)

    def update_section(self, section_title: str, content: str, evidence: List[Evidence]) -> None:
        """Update a section with content and evidence"""
        if section_title not in self.sections:
            self.sections[section_title] = Section(title=section_title)

        section = self.sections[section_title]
        section.content = content
        section.evidence = evidence

    def add_to_section(self, section_title: str, content: str, evidence: List[Evidence]) -> None:
        """Add content and evidence to a section"""
        if section_title not in self.sections:
            self.sections[section_title] = Section(title=section_title)

        section = self.sections[section_title]
        if section.content:
            section.content += "\n\n" + content
        else:
            section.content = content

        section.evidence.extend(evidence)

    def get_section(self, section_title: str) -> Optional[Section]:
        """Get a section by title"""
        return self.sections.get(section_title)

    def get_all_sections(self) -> Dict[str, Section]:
        """Get all sections"""
        return self.sections

    def is_complete(self) -> bool:
        """Check if all required sections have content"""
        for section_title in self.required_sections:
            if section_title not in self.sections or not self.sections[section_title].content:
                return False
        return True

    def generate_full_report(self) -> str:
        """Generate full report text from all sections"""
        report_parts = []

        for section_title in self.required_sections:
            if section_title in self.sections and self.sections[section_title].content:
                section = self.sections[section_title]
                report_parts.append(f"# {section_title}\n\n{section.content}\n")

                if section.references:
                    report_parts.append("## References\n\n")
                    for citation in section.references:
                        report_parts.append(f"{citation.formatted}\n")

        return "\n".join(report_parts)


class ResearchStateStore:
    """Maintains the full state of a research task"""

    def __init__(self, topic: str, questions: List[str], max_hops: int = 3):
        self.state = ResearchState(
            topic=topic,
            original_questions=questions,
            current_questions=questions.copy(),
            max_hops=max_hops
        )
        self.evidence_store = EvidenceStore()
        self.citation_mapper = CitationMapper()
        self.draft_manager = DraftManager([
            "摘要", "背景与动机", "主流模型对比", "关键技术进展",
            "当前挑战", "未来方向", "参考文献"
        ])

    def add_source(self, source: Source) -> str:
        """Add a source to the state"""
        self.state.all_sources[source.url] = source
        return self.citation_mapper.add_source(source)

    def add_evidence(self, evidence: Evidence) -> None:
        """Add evidence to the store"""
        self.evidence_store.add_evidence(evidence)

    def update_section(self, section_title: str, content: str, evidence: List[Evidence]) -> None:
        """Update a report section"""
        self.draft_manager.update_section(section_title, content, evidence)

    def add_to_section(self, section_title: str, content: str, evidence: List[Evidence]) -> None:
        """Add to a report section"""
        self.draft_manager.add_to_section(section_title, content, evidence)

    def get_section_content(self, section_title: str) -> Optional[str]:
        """Get section content"""
        section = self.draft_manager.get_section(section_title)
        return section.content if section else None

    def get_full_report(self) -> str:
        """Get full report"""
        return self.draft_manager.generate_full_report()

    def increment_hop_count(self) -> bool:
        """Increment hop count and check if max hops exceeded"""
        self.state.hop_count += 1
        return self.state.hop_count <= self.state.max_hops

    def update_step(self, step: str) -> None:
        """Update current progress step"""
        self.state.current_step = step
        self.state.updated_at = datetime.now()

    def add_completed_step(self, step: str) -> None:
        """Add a completed step"""
        self.state.completed_steps.append(step)
        self.state.updated_at = datetime.now()

    def save(self, filepath: str) -> None:
        """Save state to file"""
        # Convert to serializable dict
        state_dict = {
            "research_state": {
                "topic": self.state.topic,
                "original_questions": self.state.original_questions,
                "current_questions": self.state.current_questions,
                "completed_steps": self.state.completed_steps,
                "current_step": self.state.current_step,
                "hop_count": self.state.hop_count,
                "max_hops": self.state.max_hops,
                "created_at": self.state.created_at.isoformat(),
                "updated_at": self.state.updated_at.isoformat()
            },
            "sources": {url: vars(source) for url, source in self.state.all_sources.items()},
            "citations": {key: vars(citation) for key, citation in self.citation_mapper.citations.items()},
            "sections": {
                title: {
                    "content": section.content,
                    "evidence": [vars(e) for e in section.evidence],
                    "references": [vars(r) for r in section.references]
                }
                for title, section in self.draft_manager.sections.items()
            }
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(state_dict, f, ensure_ascii=False, indent=2, default=str)

    @classmethod
    def load(cls, filepath: str) -> 'ResearchStateStore':
        """Load state from file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            state_dict = json.load(f)

        # TODO: Implement proper deserialization
        raise NotImplementedError("Loading not implemented yet")