"""
S component - Pydantic schemas for structured data.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class BugSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BugCategory(str, Enum):
    SECURITY = "security"
    CORRECTNESS = "correctness"
    LOGIC = "logic"
    TIMING = "timing"
    VALIDATION = "validation"
    SPEC = "spec"


class BugStatus(str, Enum):
    PENDING = "pending"
    FIXING = "fixing"
    FIXED = "fixed"
    BLOCKED = "blocked"


class BugReport(BaseModel):
    """Represents a discovered bug."""
    id: str
    title: str
    description: str
    file_path: str
    line_number: int
    category: BugCategory
    severity: BugSeverity
    status: BugStatus = BugStatus.PENDING
    root_cause: Optional[str] = None
    fix_suggestion: Optional[str] = None


class FixAttempt(BaseModel):
    """Records a single fix attempt."""
    bug_id: str
    attempt_number: int
    timestamp: datetime = Field(default_factory=datetime.now)
    diff: str
    success: bool
    error_message: Optional[str] = None
    tests_passed: int = 0
    tests_failed: int = 0


class TestResult(BaseModel):
    """Result of running tests."""
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int
    duration_ms: float
    failures: list[dict] = Field(default_factory=list)
    output: str = ""


class CommitRecord(BaseModel):
    """Records a git commit."""
    commit_hash: str
    bug_id: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    files_changed: list[str] = Field(default_factory=list)


class FileSnapshot(BaseModel):
    """Snapshot of a file for rollback."""
    path: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ToolCall(BaseModel):
    """Records a tool invocation."""
    tool_name: str
    inputs: dict
    outputs: dict
    duration_ms: float
    success: bool
    error: Optional[str] = None


class TrajectoryStep(BaseModel):
    """Single step in execution trajectory."""
    step_number: int
    timestamp: datetime = Field(default_factory=datetime.now)
    state: str
    action: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    code_diff: Optional[str] = None
    test_result: Optional[TestResult] = None
    duration_ms: float = 0.0
    metadata: dict = Field(default_factory=dict)
