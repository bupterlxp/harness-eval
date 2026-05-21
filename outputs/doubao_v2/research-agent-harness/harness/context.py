"""
Context Manager - Manages evidence context and fact attribution
"""

from typing import Dict, List, Any, Optional
from collections import defaultdict
from .tools import Source, Fact, Citation


class ContextManager:
    """
    Core context manager that maintains the evidence library (source → facts mapping)
    and manages fact attribution
    """

    def __init__(self):
        # Source library: source_id -> Source
        self.source_library: Dict[int, Source] = {}
        # Fact library: fact_id -> Fact
        self.fact_library: Dict[int, Fact] = {}
        # Source to facts mapping: source_id -> list of fact_ids
        self.source_to_facts: Dict[int, List[int]] = defaultdict(list)
        # Fact citations: fact_id -> list of citations
        self.fact_citations: Dict[int, List[Citation]] = defaultdict(list)
        # Next available ID
        self.next_fact_id = 1

    def add_source(self, source: Source) -> None:
        """Add a source to the context library"""
        self.source_library[source.id] = source

    def get_source(self, source_id: int) -> Optional[Source]:
        """Get a source by ID"""
        return self.source_library.get(source_id)

    def get_all_sources(self) -> List[Source]:
        """Get all sources in the library"""
        return list(self.source_library.values())

    def add_fact(self, content: str, source_ids: List[int], confidence: float = 1.0) -> int:
        """
        Add a factual statement with attribution to sources
        Returns the fact ID
        """
        fact_id = self.next_fact_id
        self.next_fact_id += 1

        fact = Fact(
            content=content,
            source_ids=source_ids,
            confidence=confidence
        )

        self.fact_library[fact_id] = fact

        # Update source to facts mapping
        for source_id in source_ids:
            self.source_to_facts[source_id].append(fact_id)

        return fact_id

    def add_citation(self, fact_id: int, source_id: int, page: Optional[int] = None, quote: Optional[str] = None) -> None:
        """Add a citation for a fact"""
        if fact_id not in self.fact_library:
            raise ValueError(f"Fact {fact_id} not found")

        if source_id not in self.source_library:
            raise ValueError(f"Source {source_id} not found")

        citation = Citation(
            source_id=source_id,
            page=page,
            quote=quote
        )

        self.fact_citations[fact_id].append(citation)

    def get_fact(self, fact_id: int) -> Optional[Fact]:
        """Get a fact by ID"""
        return self.fact_library.get(fact_id)

    def get_facts_for_source(self, source_id: int) -> List[Fact]:
        """Get all facts attributed to a source"""
        fact_ids = self.source_to_facts.get(source_id, [])
        return [self.fact_library[fact_id] for fact_id in fact_ids]

    def get_all_facts(self) -> List[Fact]:
        """Get all facts in the library"""
        return list(self.fact_library.values())

    def get_source_fact_map(self) -> Dict[int, List[Fact]]:
        """Get mapping of sources to their facts"""
        return {
            source_id: [self.fact_library[fact_id] for fact_id in fact_ids]
            for source_id, fact_ids in self.source_to_facts.items()
        }

    def search_facts(self, query: str) -> List[Fact]:
        """Search facts by content query"""
        results = []
        query_lower = query.lower()
        for fact in self.fact_library.values():
            if query_lower in fact.content.lower():
                results.append(fact)
        return results

    def clear(self) -> None:
        """Clear all context"""
        self.source_library.clear()
        self.fact_library.clear()
        self.source_to_facts.clear()
        self.fact_citations.clear()
        self.next_fact_id = 1