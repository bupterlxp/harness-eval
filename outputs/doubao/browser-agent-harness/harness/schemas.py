from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PopupType(str, Enum):
    COOKIE_CONSENT = "cookie_consent"
    MODAL = "modal"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class StepResult:
    step_id: int
    status: TaskStatus
    url: str
    timestamp: datetime = field(default_factory=datetime.now)
    screenshot_path: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    retry_count: int = 0


@dataclass
class EmployeeInfo:
    id: int
    name: str
    gender: str
    department: str
    position: str
    email: str
    phone: str
    hire_date: str
    status: str
    annual_leave_balance: float
    performance_score: float


@dataclass
class LeaveRequest:
    id: int
    employee_name: str
    department: str
    leave_type: str
    start_date: str
    end_date: str
    reason: str
    emergency_contact: str
    status: str
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    created_at: str
    reviewed_at: Optional[str] = None


@dataclass
class AttendanceRecord:
    department: str
    month: str
    total_staff: int
    avg_attendance_rate: float
    late_count: int
    early_leave_count: int
    absent_count: int


@dataclass
class TaskContext:
    task_id: str
    current_step: int = 0
    status: TaskStatus = TaskStatus.PENDING
    completed_steps: List[int] = field(default_factory=list)
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    screenshots: List[str] = field(default_factory=list)
    navigation_history: List[str] = field(default_factory=list)
    session_cookies: Dict[str, str] = field(default_factory=dict)


@dataclass
class PageState:
    url: str
    title: str
    interactive_elements: List[str] = field(default_factory=list)
    key_text_content: List[str] = field(default_factory=list)
    loaded: bool = False


@dataclass
class Config:
    base_url: str = "http://localhost:5000"
    default_timeout: int = 30000
    max_retries: int = 3
    viewport_width: int = 1280
    viewport_height: int = 720
    screenshot_dir: str = "screenshots"
    download_dir: str = "downloads"
    report_dir: str = "reports"
