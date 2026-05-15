from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime
from .schemas import Source, Evidence, ResearchQuery
from .state import ResearchStateStore


class EvidenceContext:
    """Manages evidence context and storage"""

    def __init__(self):
        self.sources: Dict[str, Source] = {}
        self.evidence: List[Evidence] = []
        self.source_evidence_map: Dict[str, List[Evidence]] = {}

    def add_source(self, source: Source) -> None:
        """Add a source to the context"""
        self.sources[source.url] = source
        if source.url not in self.source_evidence_map:
            self.source_evidence_map[source.url] = []

    def add_evidence(self, evidence: Evidence) -> None:
        """Add evidence to the context"""
        self.evidence.append(evidence)
        if evidence.source_url in self.source_evidence_map:
            self.source_evidence_map[evidence.source_url].append(evidence)
        else:
            self.source_evidence_map[evidence.source_url] = [evidence]

    def get_sources_by_relevance(self, min_score: float = 0.0) -> List[Source]:
        """Get sources sorted by relevance score"""
        sorted_sources = sorted(
            [s for s in self.sources.values() if s.relevance_score >= min_score],
            key=lambda s: s.relevance_score,
            reverse=True
        )
        return sorted_sources

    def get_evidence_for_topic(self, topic: str, min_confidence: float = 0.0) -> List[Evidence]:
        """Get evidence relevant to a topic"""
        # Simple keyword matching - in real implementation use embeddings
        relevant_evidence = []
        for evidence in self.evidence:
            if (topic.lower() in evidence.claim.lower() and
                evidence.confidence >= min_confidence):
                relevant_evidence.append(evidence)
        return relevant_evidence

    def clear(self) -> None:
        """Clear all context"""
        self.sources.clear()
        self.evidence.clear()
        self.source_evidence_map.clear()


class OutlineContext:
    """Manages report outline and section structure"""

    def __init__(self, required_sections: List[str]):
        self.required_sections = required_sections
        self.section_progress: Dict[str, bool] = {section: False for section in required_sections}
        self.section_content: Dict[str, str] = {}
        self.section_evidence: Dict[str, List[Evidence]] = {}

    def update_section(self, section_title: str, content: str, evidence: List[Evidence]) -> None:
        """Update a section"""
        if section_title not in self.required_sections:
            return

        self.section_content[section_title] = content
        self.section_evidence[section_title] = evidence
        self.section_progress[section_title] = bool(content and evidence)

    def add_to_section(self, section_title: str, content: str, evidence: List[Evidence]) -> None:
        """Add content to a section"""
        if section_title not in self.required_sections:
            return

        existing_content = self.section_content.get(section_title, "")
        if existing_content:
            self.section_content[section_title] = existing_content + "\n\n" + content
        else:
            self.section_content[section_title] = content

        existing_evidence = self.section_evidence.get(section_title, [])
        existing_evidence.extend(evidence)
        self.section_evidence[section_title] = existing_evidence

        self.section_progress[section_title] = bool(
            self.section_content.get(section_title, "") and
            self.section_evidence.get(section_title, [])
        )

    def is_section_complete(self, section_title: str) -> bool:
        """Check if a section is complete"""
        return self.section_progress.get(section_title, False)

    def is_all_complete(self) -> bool:
        """Check if all sections are complete"""
        return all(self.section_progress.values())

    def get_outline_status(self) -> Dict[str, bool]:
        """Get progress status for all sections"""
        return self.section_progress.copy()

    def generate_full_outline(self) -> str:
        """Generate human-readable outline"""
        outline = []
        for section in self.required_sections:
            status = "✓" if self.section_progress[section] else "✗"
            outline.append(f"{status} {section}")
        return "\n".join(outline)


class QueryHistory:
    """Manages query history to avoid duplicate searches"""

    def __init__(self):
        self.history: Set[str] = set()
        self.query_results: Dict[str, List[Source]] = {}

    def add_query(self, query: str, sources: Optional[List[Source]] = None) -> None:
        """Add a query to history"""
        self.history.add(query.lower())
        if sources:
            self.query_results[query] = sources

    def has_been_searched(self, query: str) -> bool:
        """Check if a query has already been searched"""
        return query.lower() in self.history

    def get_sources_for_query(self, query: str) -> List[Source]:
        """Get sources for a previously executed query"""
        return self.query_results.get(query, [])

    def clear(self) -> None:
        """Clear query history"""
        self.history.clear()
        self.query_results.clear()


class ResearchContext:
    """Combines all context managers for a research task"""

    def __init__(self, required_sections: List[str]):
        self.evidence_context = EvidenceContext()
        self.outline_context = OutlineContext(required_sections)
        self.query_history = QueryHistory()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def update_from_state_store(self, state_store: ResearchStateStore) -> None:
        """Update context from a research state store"""
        # Update sources
        for source in state_store.state.all_sources.values():
            self.evidence_context.add_source(source)

        # Update evidence
        for evidence in state_store.evidence_store.get_all_evidence():
            self.evidence_context.add_evidence(evidence)

        # Update outline
        for title, section in state_store.draft_manager.sections.items():
            if section.content and section.evidence:
                self.outline_context.update_section(title, section.content, section.evidence)

        self.updated_at = datetime.now()

    def get_info_gaps(self) -> Dict[str, List[str]]:
        """Identify information gaps in the report"""
        gaps = {}

        # Check for incomplete sections
        incomplete_sections = [
            section for section, complete in self.outline_context.section_progress.items()
            if not complete
        ]
        if incomplete_sections:
            gaps["incomplete_sections"] = incomplete_sections

        # Check for sections with insufficient evidence
        low_evidence_sections = []
        for section in self.outline_context.required_sections:
            evidence = self.outline_context.section_evidence.get(section, [])
            if len(evidence) < 3:
                low_evidence_sections.append(f"{section} (only {len(evidence)} evidence items)")
        if low_evidence_sections:
            gaps["low_evidence_sections"] = low_evidence_sections

        # Check for missing citations
        # TODO: Implement citation gap detection

        return gaps

    def get_overall_progress(self) -> float:
        """Get overall progress percentage"""
        if not self.outline_context.required_sections:
            return 0.0

        completed = sum(1 for complete in self.outline_context.section_progress.values() if complete)
        return completed / len(self.outline_context.required_sections)

    def clear(self) -> None:
        """Clear all context"""
        self.evidence_context.clear()
        self.outline_context.clear()
        self.query_history.clear()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()