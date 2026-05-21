"""Tests for the Context Manager module."""

import pytest

from harness.state import StateStore, Source, Fact
from harness.context import ContextManager, EvidenceItem, EvidenceCluster


class TestEvidenceItem:
    def test_evidence_item_creation(self):
        source = Source(id=1, url="https://example.com", title="Example", credibility="high")
        fact = Fact(id=1, content="Test fact", source_id=1)
        item = EvidenceItem(fact=fact, source=source, relevance_score=0.9)
        assert item.fact.id == 1
        assert item.source.id == 1
        assert item.relevance_score == 0.9

    def test_evidence_item_to_dict(self):
        source = Source(id=1, url="https://example.com", title="Example", credibility="high")
        fact = Fact(id=1, content="Test fact", source_id=1)
        item = EvidenceItem(fact=fact, source=source)
        d = item.to_dict()
        assert d["fact"]["id"] == 1
        assert d["source"]["id"] == 1


class TestEvidenceCluster:
    def test_cluster_creation(self):
        cluster = EvidenceCluster(topic="AI Research")
        assert cluster.topic == "AI Research"
        assert len(cluster.items) == 0

    def test_add_item_to_cluster(self):
        cluster = EvidenceCluster(topic="AI Research")
        source = Source(id=1, url="https://example.com", title="Example", credibility="high")
        fact = Fact(id=1, content="Test fact", source_id=1)
        item = EvidenceItem(fact=fact, source=source)
        cluster.add_item(item)
        assert len(cluster.items) == 1


class TestContextManager:
    def test_register_fact(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        fact = store.add_fact("Test fact", source.id)

        ctx = ContextManager(store)
        item = ctx.register_fact(fact, source, "test query")

        assert item.fact.id == fact.id
        assert item.source.id == source.id
        assert item.query_context == "test query"

    def test_get_facts_for_source(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        fact1 = store.add_fact("Fact 1", source.id)
        fact2 = store.add_fact("Fact 2", source.id)

        ctx = ContextManager(store)
        ctx.register_fact(fact1, source)
        ctx.register_fact(fact2, source)

        facts = ctx.get_facts_for_source(source.id)
        assert len(facts) == 2

    def test_get_source_for_fact(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        fact = store.add_fact("Test fact", source.id)

        ctx = ContextManager(store)
        ctx.register_fact(fact, source)

        retrieved_source = ctx.get_source_for_fact(fact.id)
        assert retrieved_source.id == source.id

    def test_create_evidence_cluster(self):
        store = StateStore()
        ctx = ContextManager(store)
        cluster = ctx.create_evidence_cluster("Machine Learning")
        assert cluster.topic == "Machine Learning"
        assert ctx.get_evidence_cluster("Machine Learning") is not None

    def test_add_evidence_to_cluster(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        fact = store.add_fact("Test fact", source.id)

        ctx = ContextManager(store)
        item = ctx.add_evidence_to_cluster(
            topic="Machine Learning",
            fact=fact,
            source=source,
            relevance_score=0.85,
        )

        cluster = ctx.get_evidence_cluster("Machine Learning")
        assert len(cluster.items) == 1
        assert cluster.items[0].relevance_score == 0.85

    def test_get_high_credibility_evidence(self):
        store = StateStore()
        high_source = store.add_source("https://arxiv.org/paper1", "Paper 1", "high")
        low_source = store.add_source("https://blog.example.com", "Blog", "low")
        fact1 = store.add_fact("High cred fact", high_source.id)
        fact2 = store.add_fact("Low cred fact", low_source.id)

        ctx = ContextManager(store)
        ctx.add_evidence_to_cluster("Topic", fact1, high_source)
        ctx.add_evidence_to_cluster("Topic", fact2, low_source)

        high_cred = ctx.get_high_credibility_evidence("Topic")
        assert len(high_cred) == 1
        assert high_cred[0].source.credibility == "high"

    def test_has_sufficient_evidence(self):
        store = StateStore()
        ctx = ContextManager(store)

        assert ctx.has_sufficient_evidence(min_sources=3) is False

        for i in range(3):
            source = store.add_source(f"https://example{i}.com", f"Example {i}", "high")
            fact = store.add_fact(f"Fact {i}", source.id)
            ctx.register_fact(fact, source)

        assert ctx.has_sufficient_evidence(min_sources=3) is True

    def test_evidence_summary(self):
        store = StateStore()
        source1 = store.add_source("https://example1.com", "Example 1", "high")
        source2 = store.add_source("https://example2.com", "Example 2", "medium")
        store.add_fact("Fact 1", source1.id)
        store.add_fact("Fact 2", source2.id)

        ctx = ContextManager(store)
        ctx.add_evidence_to_cluster("Topic 1", store.get_fact(1), source1)
        ctx.add_evidence_to_cluster("Topic 2", store.get_fact(2), source2)

        summary = ctx.get_evidence_summary()
        assert summary["total_sources"] == 2
        assert summary["total_facts"] == 2
        assert "Topic 1" in summary["topics"]
        assert summary["credibility_distribution"]["high"] == 1
        assert summary["credibility_distribution"]["medium"] == 1

    def test_check_cross_source_verification(self):
        store = StateStore()
        source1 = store.add_source("https://example1.com", "Example 1", "high")
        source2 = store.add_source("https://example2.com", "Example 2", "high")
        fact = store.add_fact("Verified fact", source1.id)
        store.mark_fact_verified(fact.id, source2.id)

        ctx = ContextManager(store)
        verification = ctx.check_cross_source_verification(fact.id)

        assert verification["verified"] is True
        assert len(verification["verifying_sources"]) == 1

    def test_rebuild_mappings_from_state(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        fact = store.add_fact("Test fact", source.id)

        ctx = ContextManager(store)
        ctx.rebuild_mappings_from_state()

        facts = ctx.get_facts_for_source(source.id)
        assert len(facts) == 1
