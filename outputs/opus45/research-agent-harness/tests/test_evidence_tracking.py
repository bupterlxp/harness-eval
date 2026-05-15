"""Tests for evidence tracking and source traceability."""

import pytest
from datetime import datetime

from harness.schemas import Source, Evidence, SourceReliability
from harness.state import EvidenceStore
from harness.context import EvidenceContext


@pytest.fixture
def evidence_store():
    """Create an evidence store for testing."""
    return EvidenceStore()


@pytest.fixture
def sample_source():
    """Create a sample source."""
    return Source(
        id="src_test",
        url="https://arxiv.org/abs/2107.03374",
        title="Test Paper",
        content="This is the paper content with important facts.",
        reliability=SourceReliability.ACADEMIC_PAPER,
        relevance_score=0.8,
        timeliness_score=0.9,
    )


@pytest.fixture
def sample_evidence(sample_source):
    """Create sample evidence items."""
    return [
        Evidence(
            id="ev_1",
            source_id=sample_source.id,
            content="Codex achieves 28.8% on HumanEval",
            source_paragraph="The model achieves 28.8% pass@1 on HumanEval...",
            target_section="主流模型对比",
            related_questions=[0],
            confidence=0.95,
        ),
        Evidence(
            id="ev_2",
            source_id=sample_source.id,
            content="Training data from GitHub public repositories",
            source_paragraph="The model was trained on publicly available code...",
            target_section="背景与动机",
            related_questions=[1],
            confidence=0.9,
        ),
    ]


class TestEvidenceStorage:
    """Tests for evidence storage operations."""

    def test_add_source(self, evidence_store, sample_source):
        """Test adding a source."""
        source_id = evidence_store.add_source(sample_source)
        assert source_id == sample_source.id
        assert evidence_store.get_source_count() == 1

    def test_add_source_generates_id(self, evidence_store):
        """Test that source ID is generated if not provided."""
        source = Source(
            id="",
            url="https://example.com",
            title="Test",
            content="Content",
        )
        source_id = evidence_store.add_source(source)
        assert source_id.startswith("src_")
        assert len(source_id) > 4

    def test_get_source_by_url(self, evidence_store, sample_source):
        """Test retrieving source by URL."""
        evidence_store.add_source(sample_source)

        found = evidence_store.get_source_by_url(sample_source.url)
        assert found is not None
        assert found.id == sample_source.id

        not_found = evidence_store.get_source_by_url("https://nonexistent.com")
        assert not_found is None

    def test_add_evidence(self, evidence_store, sample_source, sample_evidence):
        """Test adding evidence."""
        evidence_store.add_source(sample_source)

        for ev in sample_evidence:
            evidence_store.add_evidence(ev)

        assert evidence_store.get_evidence_count() == 2

    def test_add_evidence_generates_id(self, evidence_store, sample_source):
        """Test that evidence ID is generated if not provided."""
        evidence_store.add_source(sample_source)

        evidence = Evidence(
            id="",
            source_id=sample_source.id,
            content="Test fact",
            source_paragraph="Original text",
            target_section="摘要",
        )

        evidence_id = evidence_store.add_evidence(evidence)
        assert evidence_id.startswith("ev_")


class TestEvidenceTraceability:
    """Tests for evidence-to-source traceability."""

    def test_trace_evidence_to_source(self, evidence_store, sample_source, sample_evidence):
        """Test tracing evidence back to source."""
        evidence_store.add_source(sample_source)
        evidence_store.add_evidence(sample_evidence[0])

        evidence, source = evidence_store.trace_evidence_to_source(sample_evidence[0].id)

        assert evidence is not None
        assert source is not None
        assert evidence.source_id == source.id
        assert source.url == sample_source.url

    def test_trace_includes_paragraph(self, evidence_store, sample_source, sample_evidence):
        """Test that traced evidence includes source paragraph."""
        evidence_store.add_source(sample_source)
        evidence_store.add_evidence(sample_evidence[0])

        evidence, source = evidence_store.trace_evidence_to_source(sample_evidence[0].id)

        assert evidence.source_paragraph is not None
        assert len(evidence.source_paragraph) > 0

    def test_get_evidence_for_source(self, evidence_store, sample_source, sample_evidence):
        """Test getting all evidence for a source."""
        evidence_store.add_source(sample_source)
        for ev in sample_evidence:
            evidence_store.add_evidence(ev)

        source_evidence = evidence_store.get_evidence_for_source(sample_source.id)
        assert len(source_evidence) == 2

    def test_get_evidence_for_section(self, evidence_store, sample_source, sample_evidence):
        """Test getting evidence by section."""
        evidence_store.add_source(sample_source)
        for ev in sample_evidence:
            evidence_store.add_evidence(ev)

        section_evidence = evidence_store.get_evidence_for_section("主流模型对比")
        assert len(section_evidence) == 1
        assert section_evidence[0].id == "ev_1"


class TestEvidenceContext:
    """Tests for evidence context management."""

    def test_add_to_context(self, sample_source, sample_evidence):
        """Test adding evidence to context."""
        context = EvidenceContext(max_active_entries=100)

        context.add_evidence(sample_evidence[0], sample_source, relevance_score=0.8)

        active = context.get_active_evidence()
        assert len(active) == 1

    def test_context_compression(self, sample_source):
        """Test context compression when limit exceeded."""
        context = EvidenceContext(max_active_entries=3, relevance_threshold=0.5)

        for i in range(5):
            evidence = Evidence(
                id=f"ev_{i}",
                source_id=sample_source.id,
                content=f"Fact {i}",
                source_paragraph=f"Paragraph {i}",
                target_section="摘要",
            )
            relevance = 0.3 + (i * 0.1)
            context.add_evidence(evidence, sample_source, relevance_score=relevance)

        active = context.get_active_evidence()
        assert len(active) <= 3

    def test_relevance_based_demotion(self, sample_source):
        """Test that low-relevance evidence is demoted first."""
        context = EvidenceContext(max_active_entries=2, relevance_threshold=0.5)

        low_relevance = Evidence(
            id="ev_low",
            source_id=sample_source.id,
            content="Low relevance fact",
            source_paragraph="...",
            target_section="摘要",
        )
        high_relevance = Evidence(
            id="ev_high",
            source_id=sample_source.id,
            content="High relevance fact",
            source_paragraph="...",
            target_section="摘要",
        )
        medium_relevance = Evidence(
            id="ev_med",
            source_id=sample_source.id,
            content="Medium relevance fact",
            source_paragraph="...",
            target_section="摘要",
        )

        context.add_evidence(low_relevance, sample_source, relevance_score=0.3)
        context.add_evidence(high_relevance, sample_source, relevance_score=0.9)
        context.add_evidence(medium_relevance, sample_source, relevance_score=0.6)

        active = context.get_active_evidence()
        active_ids = {e.evidence.id for e in active}

        assert "ev_high" in active_ids

    def test_section_specific_retrieval(self, sample_source, sample_evidence):
        """Test retrieving evidence for specific section."""
        context = EvidenceContext()

        for ev in sample_evidence:
            context.add_evidence(ev, sample_source, relevance_score=0.8)

        section_evidence = context.get_evidence_for_section("主流模型对比")
        assert len(section_evidence) == 1
        assert section_evidence[0].evidence.id == "ev_1"


class TestEvidenceSnapshot:
    """Tests for evidence store snapshots."""

    def test_snapshot_includes_sources(self, evidence_store, sample_source, sample_evidence):
        """Test that snapshot includes all sources."""
        evidence_store.add_source(sample_source)
        for ev in sample_evidence:
            evidence_store.add_evidence(ev)

        snapshot = evidence_store.to_snapshot()

        assert "sources" in snapshot
        assert len(snapshot["sources"]) == 1
        assert sample_source.id in snapshot["sources"]

    def test_snapshot_includes_evidence(self, evidence_store, sample_source, sample_evidence):
        """Test that snapshot includes all evidence."""
        evidence_store.add_source(sample_source)
        for ev in sample_evidence:
            evidence_store.add_evidence(ev)

        snapshot = evidence_store.to_snapshot()

        assert "evidence" in snapshot
        assert len(snapshot["evidence"]) == 2

    def test_snapshot_includes_mappings(self, evidence_store, sample_source, sample_evidence):
        """Test that snapshot includes source-evidence mappings."""
        evidence_store.add_source(sample_source)
        for ev in sample_evidence:
            evidence_store.add_evidence(ev)

        snapshot = evidence_store.to_snapshot()

        assert "source_to_evidence" in snapshot
        assert "section_to_evidence" in snapshot
        assert sample_source.id in snapshot["source_to_evidence"]
