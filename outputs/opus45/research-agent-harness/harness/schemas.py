"""Schema definitions for the Research Agent Harness.

Defines core data structures: Source, Evidence, Citation, Section,
ResearchQuery, ValidationResult, and enumerations for states and reliability.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ResearchState(Enum):
    """States in the research execution loop."""
    DECOMPOSE = "decompose"
    SEARCH = "search"
    EVALUATE = "evaluate"
    EXTRACT = "extract"
    ORGANIZE = "organize"
    GAP_FILL = "gap_fill"
    CROSS_VALIDATE = "cross_validate"
    DRAFT = "draft"
    CONSISTENCY_CHECK = "consistency_check"
    FINALIZE = "finalize"
    COMPLETED = "completed"


class SourceReliability(Enum):
    """Reliability levels for sources."""
    ACADEMIC_PAPER = "academic_paper"  # Highest: peer-reviewed papers, arXiv
    OFFICIAL_DOCS = "official_docs"    # Official documentation, tech reports
    TECH_BLOG = "tech_blog"            # Reputable tech blogs, company blogs
    NEWS = "news"                       # News articles
    FORUM = "forum"                     # Stack Overflow, forums
    UNKNOWN = "unknown"                 # Unverified sources

    @property
    def score(self) -> float:
        """Return reliability score (0-1)."""
        scores = {
            SourceReliability.ACADEMIC_PAPER: 1.0,
            SourceReliability.OFFICIAL_DOCS: 0.9,
            SourceReliability.TECH_BLOG: 0.7,
            SourceReliability.NEWS: 0.5,
            SourceReliability.FORUM: 0.4,
            SourceReliability.UNKNOWN: 0.2,
        }
        return scores[self]


class SectionStatus(Enum):
    """Status of a report section."""
    EMPTY = "empty"
    PARTIAL = "partial"
    COMPLETE = "complete"


@dataclass
class ResearchQuery:
    """A decomposed search query derived from research questions."""
    id: str
    original_question_index: int
    query_text: str
    target_section: str
    created_at: datetime = field(default_factory=datetime.now)
    executed: bool = False
    result_count: int = 0


@dataclass
class Source:
    """A collected source with evaluation metadata."""
    id: str
    url: str
    title: str
    content: str
    reliability: SourceReliability = SourceReliability.UNKNOWN
    relevance_score: float = 0.0
    timeliness_score: float = 0.0
    overall_score: float = 0.0
    fetched_at: datetime = field(default_factory=datetime.now)
    evaluated: bool = False

    def compute_overall_score(self) -> float:
        """Compute weighted overall score."""
        self.overall_score = (
            self.reliability.score * 0.4 +
            self.relevance_score * 0.4 +
            self.timeliness_score * 0.2
        )
        return self.overall_score


@dataclass
class Evidence:
    """Extracted fact or data point from a source."""
    id: str
    source_id: str
    content: str
    source_paragraph: str
    target_section: str
    related_questions: list[int] = field(default_factory=list)
    confidence: float = 1.0
    cross_validated: bool = False
    validation_sources: list[str] = field(default_factory=list)
    extracted_at: datetime = field(default_factory=datetime.now)


@dataclass
class Citation:
    """A formatted citation entry."""
    id: str
    source_id: str
    citation_number: int
    authors: str
    year: str
    title: str
    venue: str
    url: str
    formatted: str = ""

    def format_citation(self) -> str:
        """Format citation according to spec: 作者(年份). 标题. 来源. URL"""
        self.formatted = f"{self.authors} ({self.year}). {self.title}. {self.venue}. {self.url}"
        return self.formatted


@dataclass
class Section:
    """A section of the research report."""
    name: str
    title: str
    content: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    citation_ids: list[str] = field(default_factory=list)
    status: SectionStatus = SectionStatus.EMPTY
    word_count: int = 0
    required_evidence_count: int = 2

    def update_status(self) -> None:
        """Update section status based on content and evidence."""
        if not self.content:
            self.status = SectionStatus.EMPTY
        elif len(self.evidence_ids) < self.required_evidence_count:
            self.status = SectionStatus.PARTIAL
        else:
            self.status = SectionStatus.COMPLETE
        self.word_count = len(self.content.split())


@dataclass
class ValidationResult:
    """Result of cross-validation for a claim."""
    claim: str
    is_valid: bool
    supporting_sources: list[str]
    conflicting_sources: list[str]
    confidence: float
    notes: str = ""


@dataclass
class ResearchTask:
    """Complete research task specification."""
    topic: str
    questions: list[str]
    constraints: dict[str, any]
    required_sections: list[str]
    min_sources: int = 10
    max_report_length: int = 3000

    @classmethod
    def from_json(cls, data: dict) -> "ResearchTask":
        """Create ResearchTask from JSON data."""
        task_data = data.get("research_task", data)
        constraints = task_data.get("constraints", {})
        return cls(
            topic=task_data["topic"],
            questions=task_data["questions"],
            constraints=constraints,
            required_sections=constraints.get("required_sections", []),
            min_sources=constraints.get("min_sources", 10),
            max_report_length=constraints.get("max_report_length_words", 3000),
        )


@dataclass
class TrajectoryEntry:
    """A single entry in the evaluation trajectory log."""
    timestamp: datetime
    state: ResearchState
    action: str
    details: dict[str, any]
    source_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSONL serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "state": self.state.value,
            "action": self.action,
            "details": self.details,
            "source_ids": self.source_ids,
            "evidence_ids": self.evidence_ids,
        }


@dataclass
class GapAnalysis:
    """Analysis of information gaps for a section."""
    section_name: str
    has_gap: bool
    missing_topics: list[str]
    current_evidence_count: int
    required_evidence_count: int
    suggested_queries: list[str]
