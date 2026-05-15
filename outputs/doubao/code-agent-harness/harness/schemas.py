"""
Pydantic schemas for the agent harness.
"""

from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Dict, Optional, Any
from datetime import datetime


class BugSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BugType(str, Enum):
    SECURITY = "security"
    LOGIC = "logic"
    PERFORMANCE = "performance"
    NAMING = "naming"
    TYPO = "typo"
    COMPATIBILITY = "compatibility"


class BugReport(BaseModel):
    """Represents a bug found in the codebase."""
    bug_id: int
    title: str
    description: str
    severity: BugSeverity
    bug_type: BugType
    file_path: str
    line_number: int
    code_snippet: str
    fixed_snippet: Optional[str] = None
    status: str = Field(default="pending", description="pending|fixing|fixed|blocked")
    commit_hash: Optional[str] = None


class TestResult(BaseModel):
    """Result of running a test."""
    test_name: str
    passed: bool
    error_message: Optional[str] = None
    duration: float = 0.0


class FixAttempt(BaseModel):
    """Represents an attempt to fix a bug."""
    bug_id: int
    timestamp: datetime = Field(default_factory=datetime.now)
    changes: Dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    test_results: List[TestResult] = Field(default_factory=list)
    error_message: Optional[str] = None


class CommitRecord(BaseModel):
    """Record of a git commit."""
    commit_hash: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    files_changed: List[str] = Field(default_factory=list)
    bug_id: Optional[int] = None


class TrajectoryStep(BaseModel):
    """A single step in the evaluation trajectory."""
    step_number: int
    state: str
    action: str
    timestamp: datetime = Field(default_factory=datetime.now)
    code_diff: Optional[str] = None
    test_results: List[TestResult] = Field(default_factory=list)
    duration: float = 0.0
