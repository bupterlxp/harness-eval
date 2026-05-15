import time
from typing import List, Dict, Set, Tuple, Optional
from .schemas import Source, SourceReliability, ResearchQuery, ValidationResult
from .context import ResearchContext


class LifecycleHooks:
    """Implements lifecycle hooks for the research process"""

    def __init__(self, max_hops: int = 3):
        self.max_hops = max_hops
        self.rate_limit_delay = 1.0
        self.last_request_time = 0

    async def pre_search(self, query: str, query_history: Set[str]) -> Tuple[bool, str]:
        """Hook before executing a search"""
        # Check if query has already been searched
        query_lower = query.lower()
        if query_lower in query_history:
            return False, f"Query '{query}' has already been searched"

        # Additional pre-search checks
        return True, "Query is valid"

    async def post_search(self, sources: List[Source], min_relevance: float = 0.3) -> List[Source]:
        """Hook after executing a search - filter and sort sources"""
        # Filter sources by relevance
        filtered_sources = [
            s for s in sources
            if s.relevance_score >= min_relevance or s.reliability.value >= SourceReliability.TECHNICAL_BLOG.value
        ]

        # Sort by reliability and relevance
        sorted_sources = sorted(
            filtered_sources,
            key=lambda s: (s.reliability.value, s.relevance_score),
            reverse=True
        )

        return sorted_sources

    async def pre_draft(self, section_title: str, evidence: List[Evidence], min_evidence: int = 3) -> ValidationResult:
        """Hook before drafting a section - check evidence sufficiency"""
        result = ValidationResult(valid=True)

        if len(evidence) < min_evidence:
            result.valid = False
            result.errors.append(f"Section '{section_title}' has only {len(evidence)} evidence items, need at least {min_evidence}")

        # Check for duplicate evidence
        seen_claims = set()
        duplicate_claims = []
        for e in evidence:
            if e.claim in seen_claims:
                duplicate_claims.append(e.claim)
            seen_claims.add(e.claim)

        if duplicate_claims:
            result.warnings.append(f"Found {len(duplicate_claims)} duplicate evidence claims")

        return result

    async def post_draft(self, section_title: str, content: str, citations: List[str]) -> ValidationResult:
        """Hook after drafting a section - check citation integrity"""
        result = ValidationResult(valid=True)

        # Check if content contains citations
        if not citations and section_title not in ["摘要", "背景与动机"]:
            result.warnings.append(f"Section '{section_title}' has no citations")

        # Check citation format
        # TODO: Implement citation format validation

        return result

    async def on_rate_limit(self) -> None:
        """Handle rate limiting - wait with backoff"""
        current_time = time.time()
        if current_time - self.last_request_time < self.rate_limit_delay:
            wait_time = self.rate_limit_delay - (current_time - self.last_request_time)
            time.sleep(wait_time)

        self.last_request_time = time.time()
        # Increase delay for next time
        self.rate_limit_delay *= 2

    async def reset_rate_limit(self) -> None:
        """Reset rate limit delay"""
        self.rate_limit_delay = 1.0

    async def check_evidence_sufficiency(self, required_sections: Dict[str, int]) -> Dict[str, List[str]]:
        """Check sufficiency of evidence across all sections"""
        gaps = {}

        for section, min_evidence in required_sections.items():
            section_evidence = []  # This would normally come from context
            if len(section_evidence) < min_evidence:
                gaps[section] = [
                    f"Need at least {min_evidence} evidence items for section '{section}'",
                    f"Current: {len(section_evidence)} items"
                ]

        return gaps

    async def validate_citation_integrity(self, citations_used: Dict[str, int], all_citations: Set[str]) -> ValidationResult:
        """Validate that all citations in text are present in references"""
        result = ValidationResult(valid=True)

        # Check for citations in text that aren't in references
        missing_references = []
        for citation_key in citations_used.keys():
            if citation_key not in all_citations:
                missing_references.append(citation_key)

        if missing_references:
            result.valid = False
            result.errors.append(f"Citations missing from references: {missing_references}")

        # Check for unused references
        unused_references = [key for key in all_citations if key not in citations_used]
        if unused_references:
            result.warnings.append(f"Unused citations in references: {unused_references}")

        return result

    def should_continue_searching(self, hop_count: int) -> bool:
        """Check if more search hops are allowed"""
        return hop_count < self.max_hops