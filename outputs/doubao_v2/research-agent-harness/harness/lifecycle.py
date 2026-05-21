"""
Lifecycle Hooks - Handles research boundary control and validation
"""

import re
from typing import List, Dict, Any, Set, Optional
from collections import defaultdict

from .tools import Source


class LifecycleHooks:
    """
    Implements lifecycle hooks for research process control:
    - Search deduplication
    - Evidence sufficiency checking before drafting
    - Citation integrity validation after drafting
    """

    def __init__(self):
        self.visited_urls: Set[str] = set()
        self.visited_queries: Set[str] = set()

    def pre_search_deduplicate(self, query: str) -> bool:
        """
        Check if a search query has already been executed
        Returns True if query is new, False if duplicated
        """
        if query in self.visited_queries:
            return False
        self.visited_queries.add(query)
        return True

    def pre_search_url_filter(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out already visited URLs from search results
        """
        filtered = []
        for source in sources:
            url = source.get("url", "")
            if url not in self.visited_urls:
                filtered.append(source)
        return filtered

    def mark_urls_visited(self, sources: List[Dict[str, Any]]) -> None:
        """
        Mark URLs as visited after processing
        """
        for source in sources:
            url = source.get("url", "")
            if url:
                self.visited_urls.add(url)

    def check_evidence_sufficiency(self, collected_facts: int, required_facts: int = 5) -> bool:
        """
        Check if there's sufficient evidence to proceed to drafting
        """
        return collected_facts >= required_facts

    def check_source_sufficiency(self, collected_sources: int, min_sources: int = 10) -> bool:
        """
        Check if enough sources have been collected
        """
        return collected_sources >= min_sources

    def validate_citation_integrity(self, report_sections: Dict[str, str],
                                  sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate citation integrity in the report
        Returns statistics about citations
        """
        # Extract all citation markers from report
        citation_pattern = r'\[(\d+)\]'
        cited_source_ids: Set[int] = set()
        all_source_ids: Set[int] = {source["id"] for source in sources}

        for section_content in report_sections.values():
            matches = re.findall(citation_pattern, section_content)
            for match in matches:
                try:
                    source_id = int(match)
                    cited_source_ids.add(source_id)
                except ValueError:
                    continue

        # Calculate statistics
        orphaned_citations = cited_source_ids - all_source_ids
        unused_sources = all_source_ids - cited_source_ids

        return {
            "total_citations": len(cited_source_ids),
            "orphaned": len(orphaned_citations),
            "unused": len(unused_sources),
            "orphaned_ids": list(orphaned_citations),
            "unused_ids": list(unused_sources)
        }

    def extract_cited_sources(self, report_sections: Dict[str, str]) -> Set[int]:
        """
        Extract all cited source IDs from report sections
        """
        citation_pattern = r'\[(\d+)\]'
        cited_ids: Set[int] = set()

        for section_content in report_sections.values():
            matches = re.findall(citation_pattern, section_content)
            for match in matches:
                try:
                    source_id = int(match)
                    cited_ids.add(source_id)
                except ValueError:
                    continue

        return cited_ids

    def reset(self) -> None:
        """Reset the lifecycle hooks state"""
        self.visited_urls.clear()
        self.visited_queries.clear()