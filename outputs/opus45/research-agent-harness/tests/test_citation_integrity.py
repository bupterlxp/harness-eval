"""Tests for citation integrity and consistency."""

import pytest
from harness.schemas import Source, SourceReliability
from harness.state import CitationMapper, EvidenceStore


@pytest.fixture
def citation_mapper():
    """Create a citation mapper for testing."""
    return CitationMapper()


@pytest.fixture
def sample_sources():
    """Create sample sources for testing."""
    return [
        Source(
            id="src_1",
            url="https://arxiv.org/abs/2107.03374",
            title="Evaluating Large Language Models Trained on Code",
            content="Codex paper content...",
            reliability=SourceReliability.ACADEMIC_PAPER,
        ),
        Source(
            id="src_2",
            url="https://arxiv.org/abs/2305.06161",
            title="StarCoder: May the source be with you!",
            content="StarCoder paper content...",
            reliability=SourceReliability.ACADEMIC_PAPER,
        ),
        Source(
            id="src_3",
            url="https://github.com/example/repo",
            title="Example Repository",
            content="Repository documentation...",
            reliability=SourceReliability.OFFICIAL_DOCS,
        ),
    ]


class TestCitationNumbering:
    """Tests for citation number consistency."""

    def test_sequential_numbering(self, citation_mapper, sample_sources):
        """Verify citations are numbered sequentially."""
        for i, source in enumerate(sample_sources):
            citation = citation_mapper.add_citation(
                source=source,
                authors=f"Author {i+1}",
                year="2023",
                title=source.title,
                venue="arXiv",
            )
            assert citation.citation_number == i + 1

    def test_no_duplicate_citations(self, citation_mapper, sample_sources):
        """Verify same source gets same citation number."""
        source = sample_sources[0]

        citation1 = citation_mapper.add_citation(
            source=source,
            authors="Chen et al.",
            year="2021",
            title=source.title,
            venue="arXiv",
        )

        citation2 = citation_mapper.add_citation(
            source=source,
            authors="Different Author",
            year="2022",
            title="Different Title",
            venue="Different Venue",
        )

        assert citation1.citation_number == citation2.citation_number
        assert citation_mapper.get_citation_count() == 1

    def test_citation_lookup_by_number(self, citation_mapper, sample_sources):
        """Verify citations can be looked up by number."""
        for source in sample_sources:
            citation_mapper.add_citation(
                source=source,
                authors="Author",
                year="2023",
                title=source.title,
                venue="arXiv",
            )

        citation = citation_mapper.get_citation_by_number(2)
        assert citation is not None
        assert citation.source_id == "src_2"

    def test_citation_lookup_by_source(self, citation_mapper, sample_sources):
        """Verify citations can be looked up by source ID."""
        for source in sample_sources:
            citation_mapper.add_citation(
                source=source,
                authors="Author",
                year="2023",
                title=source.title,
                venue="arXiv",
            )

        citation = citation_mapper.get_citation_for_source("src_1")
        assert citation is not None
        assert citation.citation_number == 1


class TestCitationValidation:
    """Tests for citation validation in text."""

    def test_valid_citations(self, citation_mapper, sample_sources):
        """Verify valid citations pass validation."""
        for source in sample_sources:
            citation_mapper.add_citation(
                source=source,
                authors="Author",
                year="2023",
                title=source.title,
                venue="arXiv",
            )

        text = "This is supported by research [1] and further confirmed [2][3]."
        broken = citation_mapper.validate_citations(text)
        assert broken == []

    def test_broken_citations_detected(self, citation_mapper, sample_sources):
        """Verify broken citations are detected."""
        citation_mapper.add_citation(
            source=sample_sources[0],
            authors="Author",
            year="2023",
            title=sample_sources[0].title,
            venue="arXiv",
        )

        text = "This cites [1] and [5] which doesn't exist."
        broken = citation_mapper.validate_citations(text)
        assert 5 in broken
        assert 1 not in broken

    def test_multiple_broken_citations(self, citation_mapper, sample_sources):
        """Verify multiple broken citations are detected."""
        citation_mapper.add_citation(
            source=sample_sources[0],
            authors="Author",
            year="2023",
            title=sample_sources[0].title,
            venue="arXiv",
        )

        text = "Citations [1], [10], [15], and [20] are used."
        broken = citation_mapper.validate_citations(text)
        assert set(broken) == {10, 15, 20}


class TestCitationFormatting:
    """Tests for citation formatting."""

    def test_citation_format(self, citation_mapper, sample_sources):
        """Verify citation format matches spec."""
        source = sample_sources[0]
        citation = citation_mapper.add_citation(
            source=source,
            authors="Chen, M. et al.",
            year="2021",
            title="Evaluating Large Language Models Trained on Code",
            venue="arXiv",
        )

        expected = "Chen, M. et al. (2021). Evaluating Large Language Models Trained on Code. arXiv. https://arxiv.org/abs/2107.03374"
        assert citation.formatted == expected

    def test_reference_list_format(self, citation_mapper, sample_sources):
        """Verify reference list is formatted correctly."""
        citation_mapper.add_citation(
            source=sample_sources[0],
            authors="Chen, M. et al.",
            year="2021",
            title="Codex Paper",
            venue="arXiv",
        )
        citation_mapper.add_citation(
            source=sample_sources[1],
            authors="Li, R. et al.",
            year="2023",
            title="StarCoder Paper",
            venue="arXiv",
        )

        ref_list = citation_mapper.format_reference_list()
        lines = ref_list.split("\n")

        assert len(lines) == 2
        assert lines[0].startswith("1.")
        assert lines[1].startswith("2.")


class TestCitationSourceTracing:
    """Tests for tracing citations back to sources."""

    def test_source_to_citation_mapping(self, citation_mapper, sample_sources):
        """Verify source ID maps to citation number."""
        for source in sample_sources:
            citation_mapper.add_citation(
                source=source,
                authors="Author",
                year="2023",
                title=source.title,
                venue="arXiv",
            )

        assert citation_mapper.get_citation_number("src_1") == 1
        assert citation_mapper.get_citation_number("src_2") == 2
        assert citation_mapper.get_citation_number("src_3") == 3

    def test_nonexistent_source(self, citation_mapper):
        """Verify None returned for nonexistent source."""
        assert citation_mapper.get_citation_number("nonexistent") is None
        assert citation_mapper.get_citation_for_source("nonexistent") is None

    def test_all_citations_retrievable(self, citation_mapper, sample_sources):
        """Verify all citations can be retrieved in order."""
        for source in sample_sources:
            citation_mapper.add_citation(
                source=source,
                authors="Author",
                year="2023",
                title=source.title,
                venue="arXiv",
            )

        all_citations = citation_mapper.get_all_citations()
        assert len(all_citations) == 3
        assert [c.citation_number for c in all_citations] == [1, 2, 3]
