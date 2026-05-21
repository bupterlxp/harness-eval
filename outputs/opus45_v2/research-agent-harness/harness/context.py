"""Context Manager (C) - Manages evidence context with source-to-facts mapping and provenance."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from harness.state import StateStore, Source, Fact


@dataclass
class EvidenceItem:
    """A piece of evidence with full provenance."""
    fact: Fact
    source: Source
    relevance_score: float = 1.0
    query_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact": self.fact.to_dict(),
            "source": self.source.to_dict(),
            "relevance_score": self.relevance_score,
            "query_context": self.query_context,
        }


@dataclass
class EvidenceCluster:
    """A cluster of related evidence items around a topic."""
    topic: str
    items: list[EvidenceItem] = field(default_factory=list)
    consensus: str | None = None
    has_contradictions: bool = False

    def add_item(self, item: EvidenceItem) -> None:
        self.items.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "items": [i.to_dict() for i in self.items],
            "consensus": self.consensus,
            "has_contradictions": self.has_contradictions,
        }


class ContextManager:
    """Manages research evidence context with source-to-facts mapping."""

    def __init__(self, state_store: StateStore):
        self._state = state_store
        self._evidence_clusters: dict[str, EvidenceCluster] = {}
        self._source_facts_map: dict[int, list[int]] = {}
        self._fact_sources_map: dict[int, int] = {}

    @property
    def state(self) -> StateStore:
        return self._state

    def register_fact(self, fact: Fact, source: Source, query_context: str = "") -> EvidenceItem:
        """Register a fact with its source, creating provenance link."""
        if source.id not in self._source_facts_map:
            self._source_facts_map[source.id] = []
        self._source_facts_map[source.id].append(fact.id)
        self._fact_sources_map[fact.id] = source.id

        return EvidenceItem(
            fact=fact,
            source=source,
            query_context=query_context,
        )

    def get_facts_for_source(self, source_id: int) -> list[Fact]:
        """Get all facts extracted from a source."""
        fact_ids = self._source_facts_map.get(source_id, [])
        return [f for f in self._state.facts if f.id in fact_ids]

    def get_source_for_fact(self, fact_id: int) -> Source | None:
        """Trace a fact back to its original source."""
        source_id = self._fact_sources_map.get(fact_id)
        if source_id is None:
            return None
        return self._state.get_source(source_id)

    def create_evidence_cluster(self, topic: str) -> EvidenceCluster:
        """Create a new evidence cluster for a topic."""
        cluster = EvidenceCluster(topic=topic)
        self._evidence_clusters[topic] = cluster
        return cluster

    def get_evidence_cluster(self, topic: str) -> EvidenceCluster | None:
        return self._evidence_clusters.get(topic)

    def add_evidence_to_cluster(
        self,
        topic: str,
        fact: Fact,
        source: Source,
        relevance_score: float = 1.0,
        query_context: str = "",
    ) -> EvidenceItem:
        """Add evidence to a topic cluster with provenance."""
        if topic not in self._evidence_clusters:
            self.create_evidence_cluster(topic)

        item = EvidenceItem(
            fact=fact,
            source=source,
            relevance_score=relevance_score,
            query_context=query_context,
        )
        self._evidence_clusters[topic].add_item(item)

        self.register_fact(fact, source, query_context)

        return item

    def get_all_evidence_for_topic(self, topic: str) -> list[EvidenceItem]:
        """Get all evidence items for a topic."""
        cluster = self._evidence_clusters.get(topic)
        if cluster:
            return cluster.items
        return []

    def get_high_credibility_evidence(self, topic: str | None = None) -> list[EvidenceItem]:
        """Get evidence from high-credibility sources only."""
        result = []
        clusters = [self._evidence_clusters[topic]] if topic and topic in self._evidence_clusters else self._evidence_clusters.values()

        for cluster in clusters:
            for item in cluster.items:
                if item.source.credibility == "high":
                    result.append(item)
        return result

    def check_cross_source_verification(self, fact_id: int) -> dict[str, Any]:
        """Check if a fact has been verified or contradicted by other sources."""
        fact = self._state.get_fact(fact_id)
        if not fact:
            return {"verified": False, "contradicted": False, "verifying_sources": [], "contradicting_sources": []}

        verifying = [self._state.get_source(sid) for sid in fact.verified_by if self._state.get_source(sid)]
        contradicting = [self._state.get_source(sid) for sid in fact.contradicted_by if self._state.get_source(sid)]

        return {
            "verified": len(verifying) > 0,
            "contradicted": len(contradicting) > 0,
            "verifying_sources": [s.to_dict() for s in verifying if s],
            "contradicting_sources": [s.to_dict() for s in contradicting if s],
        }

    def mark_cluster_contradictions(self, topic: str) -> None:
        """Detect and mark contradictions within a cluster."""
        cluster = self._evidence_clusters.get(topic)
        if not cluster:
            return

        for i, item1 in enumerate(cluster.items):
            for item2 in cluster.items[i + 1:]:
                if item1.fact.id in [f.id for f in self._state.facts if item2.fact.id in f.contradicted_by]:
                    cluster.has_contradictions = True
                    return

    def get_evidence_summary(self) -> dict[str, Any]:
        """Get a summary of all collected evidence."""
        total_facts = len(self._state.facts)
        total_sources = len(self._state.sources)
        topics = list(self._evidence_clusters.keys())

        credibility_counts = {"high": 0, "medium": 0, "low": 0}
        for source in self._state.sources:
            credibility_counts[source.credibility] = credibility_counts.get(source.credibility, 0) + 1

        return {
            "total_facts": total_facts,
            "total_sources": total_sources,
            "topics": topics,
            "credibility_distribution": credibility_counts,
            "clusters_with_contradictions": [
                t for t, c in self._evidence_clusters.items() if c.has_contradictions
            ],
        }

    def get_evidence_for_section(self, section_name: str, required_facts: int = 3) -> list[EvidenceItem]:
        """Get evidence items suitable for a report section."""
        all_evidence: list[EvidenceItem] = []
        for cluster in self._evidence_clusters.values():
            all_evidence.extend(cluster.items)

        all_evidence.sort(key=lambda e: (
            -1 if e.source.credibility == "high" else (0 if e.source.credibility == "medium" else 1),
            -e.relevance_score,
        ))

        return all_evidence[:required_facts] if len(all_evidence) >= required_facts else all_evidence

    def has_sufficient_evidence(self, min_sources: int = 3, min_facts_per_source: int = 1) -> bool:
        """Check if we have sufficient evidence to proceed with drafting."""
        sources_with_facts = 0
        for source in self._state.sources:
            facts = self.get_facts_for_source(source.id)
            if len(facts) >= min_facts_per_source:
                sources_with_facts += 1

        return sources_with_facts >= min_sources

    def build_citation_context(self) -> dict[int, dict[str, Any]]:
        """Build context for citation generation."""
        context = {}
        for mapping in self._state.citation_mappings:
            source = self._state.get_source(mapping.source_id)
            facts = [self._state.get_fact(fid) for fid in mapping.fact_ids]

            context[mapping.inline_number] = {
                "source": source.to_dict() if source else None,
                "facts": [f.to_dict() for f in facts if f],
            }

        return context

    def rebuild_mappings_from_state(self) -> None:
        """Rebuild internal mappings from state store (e.g., after loading checkpoint)."""
        self._source_facts_map.clear()
        self._fact_sources_map.clear()

        for fact in self._state.facts:
            if fact.source_id not in self._source_facts_map:
                self._source_facts_map[fact.source_id] = []
            self._source_facts_map[fact.source_id].append(fact.id)
            self._fact_sources_map[fact.id] = fact.source_id
