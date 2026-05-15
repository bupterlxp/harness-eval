from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set
from enum import Enum
from datetime import datetime


class SourceReliability(Enum):
    """Reliability ratings for sources"""
    ACADEMIC = 5
    TECHNICAL_BLOG = 4
    OFFICIAL_DOC = 4
    NEWS = 3
    FORUM = 2
    UNKNOWN = 1


@dataclass
class Source:
    """Represents a source document"""
    url: str
    title: str
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    reliability: SourceReliability = SourceReliability.UNKNOWN
    content: Optional[str] = None
    extracted_at: datetime = field(default_factory=datetime.now)
    relevance_score: float = 0.0


@dataclass
class Evidence:
    """Represents extracted evidence/fact from a source"""
    source_url: str
    claim: str
    citation_key: Optional[str] = None
    confidence: float = 1.0
    extracted_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Citation:
    """Represents a citation entry"""
    key: str
    source: Source
    formatted: str


@dataclass
class Section:
    """Represents a report section"""
    title: str
    content: str = ""
    evidence: List[Evidence] = field(default_factory=list)
    references: List[Citation] = field(default_factory=list)


@dataclass
class ResearchQuery:
    """Represents a research query"""
    query: str
    description: Optional[str] = None
    max_results: int = 10
    sources: List[Source] = field(default_factory=list)
    completed: bool = False


@dataclass
class ValidationResult:
    """Result of a validation check"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchState:
    """Full state of a research task"""
    topic: str
    original_questions: List[str]
    current_questions: List[str]
    sections: Dict[str, Section] = field(default_factory=dict)
    all_sources: Dict[str, Source] = field(default_factory=dict)
    citations: Dict[str, Citation] = field(default_factory=dict)
    query_history: Set[str] = field(default_factory=set)
    completed_steps: List[str] = field(default_factory=list)
    current_step: str = "INITIALIZED"
    hop_count: int = 0
    max_hops: int = 3
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)