"""Tests for the State Store module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.state import StateStore, Source, Fact, SectionDraft, CitationMapping


class TestSource:
    def test_source_creation(self):
        source = Source(
            id=1,
            url="https://example.com",
            title="Example",
            credibility="high",
            content="Test content",
            retrieved_at="2024-01-01T00:00:00",
        )
        assert source.id == 1
        assert source.url == "https://example.com"
        assert source.credibility == "high"

    def test_source_to_dict(self):
        source = Source(id=1, url="https://example.com", title="Example", credibility="high")
        d = source.to_dict()
        assert d["id"] == 1
        assert d["url"] == "https://example.com"

    def test_source_from_dict(self):
        data = {"id": 1, "url": "https://example.com", "title": "Example", "credibility": "high", "content": "", "retrieved_at": ""}
        source = Source.from_dict(data)
        assert source.id == 1
        assert source.url == "https://example.com"


class TestFact:
    def test_fact_creation(self):
        fact = Fact(id=1, content="Test fact", source_id=1, confidence=0.9)
        assert fact.id == 1
        assert fact.source_id == 1
        assert fact.confidence == 0.9

    def test_fact_verified_by(self):
        fact = Fact(id=1, content="Test fact", source_id=1)
        fact.verified_by.append(2)
        assert 2 in fact.verified_by


class TestStateStore:
    def test_add_source(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        assert source is not None
        assert source.id == 1
        assert len(store.sources) == 1

    def test_add_duplicate_source_returns_none(self):
        store = StateStore()
        store.add_source("https://example.com", "Example", "high")
        duplicate = store.add_source("https://example.com", "Example 2", "medium")
        assert duplicate is None
        assert len(store.sources) == 1

    def test_url_normalization(self):
        store = StateStore()
        store.add_source("https://example.com/", "Example 1", "high")
        duplicate = store.add_source("http://example.com", "Example 2", "medium")
        assert duplicate is None
        assert len(store.sources) == 1

    def test_add_fact(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        fact = store.add_fact("Test fact", source.id, confidence=0.9)
        assert fact.id == 1
        assert fact.source_id == source.id
        assert len(store.facts) == 1

    def test_get_facts_for_source(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        store.add_fact("Fact 1", source.id)
        store.add_fact("Fact 2", source.id)
        facts = store.get_facts_for_source(source.id)
        assert len(facts) == 2

    def test_mark_fact_verified(self):
        store = StateStore()
        source1 = store.add_source("https://example1.com", "Example 1", "high")
        source2 = store.add_source("https://example2.com", "Example 2", "high")
        fact = store.add_fact("Test fact", source1.id)
        store.mark_fact_verified(fact.id, source2.id)
        assert source2.id in store.get_fact(fact.id).verified_by

    def test_section_draft_operations(self):
        store = StateStore()
        draft = store.add_section_draft("Introduction", "Draft content", [1, 2])
        assert draft.name == "Introduction"
        assert draft.content == "Draft content"

        updated = store.update_section_draft("Introduction", "Updated content", [1, 2, 3], complete=True)
        assert updated.content == "Updated content"
        assert updated.complete is True

    def test_citation_mapping(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        mapping = store.add_citation_mapping(source.id, [1, 2])
        assert mapping.inline_number == 1
        assert mapping.source_id == source.id

    def test_get_citation_for_source(self):
        store = StateStore()
        source = store.add_source("https://example.com", "Example", "high")
        store.add_citation_mapping(source.id, [1])
        citation = store.get_citation_for_source(source.id)
        assert citation is not None
        assert citation.source_id == source.id

    def test_record_query(self):
        store = StateStore()
        store.record_query("test query")
        assert "test query" in store._queries_executed

    def test_increment_hop(self):
        store = StateStore()
        assert store.current_hop == 0
        store.increment_hop()
        assert store.current_hop == 1

    def test_add_gap(self):
        store = StateStore()
        store.add_gap("Missing information about X")
        assert "Missing information about X" in store.gaps
        store.add_gap("Missing information about X")
        assert store.gaps.count("Missing information about X") == 1

    def test_serialization(self):
        store = StateStore()
        store.add_source("https://example.com", "Example", "high")
        store.add_fact("Test fact", 1)
        store.add_gap("Test gap")

        data = store.to_dict()
        restored = StateStore.from_dict(data)

        assert len(restored.sources) == 1
        assert len(restored.facts) == 1
        assert "Test gap" in restored.gaps

    def test_checkpoint_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(tmpdir)
            store.add_source("https://example.com", "Example", "high")
            store.add_fact("Test fact", 1)

            new_store = StateStore(tmpdir)
            loaded = new_store.load_checkpoint()
            assert loaded is True
            assert len(new_store.sources) == 1
            assert len(new_store.facts) == 1

    def test_is_url_seen(self):
        store = StateStore()
        assert store.is_url_seen("https://example.com") is False
        store.add_source("https://example.com", "Example", "high")
        assert store.is_url_seen("https://example.com") is True
        assert store.is_url_seen("http://example.com/") is True
