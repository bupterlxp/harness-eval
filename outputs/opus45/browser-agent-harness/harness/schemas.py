"""
schemas.py - Data schemas for the browser agent harness.

Defines:
- TaskStep: Individual task step with status tracking
- PageState: Current page DOM summary and interactable elements
- EmployeeInfo: Extracted employee data
- LeaveRequest: Leave request data structure
- AttendanceReport: Attendance statistics
- Screenshot: Screenshot metadata
- TaskResult: Final execution result
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    """Status of a task step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PageOperationPhase(str, Enum):
    """Inner state machine phases for page operations."""
    NAVIGATE = "navigate"
    WAIT_LOAD = "wait_load"
    POPUP_CHECK = "popup_check"
    INTERACT = "interact"
    EXTRACT = "extract"
    SCREENSHOT = "screenshot"
    RECORD = "record"


class TaskPhase(str, Enum):
    """Outer state machine phases for task execution."""
    INIT = "init"
    LOGIN = "login"
    DASHBOARD = "dashboard"
    EMPLOYEES = "employees"
    LEAVE_MGMT = "leave_mgmt"
    REPORTS = "reports"
    REPORT_GEN = "report_gen"
    COMPLETED = "completed"


@dataclass
class InteractableElement:
    """Represents an interactable DOM element."""
    tag: str
    element_type: str | None  # input type, button, link, etc.
    selector: str
    text: str | None
    placeholder: str | None
    aria_label: str | None
    name: str | None
    element_id: str | None
    is_visible: bool = True
    is_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "type": self.element_type,
            "selector": self.selector,
            "text": self.text,
            "placeholder": self.placeholder,
            "aria_label": self.aria_label,
            "name": self.name,
            "id": self.element_id,
            "visible": self.is_visible,
            "enabled": self.is_enabled,
        }


@dataclass
class PageState:
    """Current page state with DOM summary."""
    url: str
    title: str
    interactable_elements: list[InteractableElement] = field(default_factory=list)
    key_text_content: dict[str, str] = field(default_factory=dict)
    has_popup: bool = False
    popup_type: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_summary(self) -> str:
        """Generate a concise summary for LLM context."""
        elements_summary = []
        for el in self.interactable_elements[:20]:  # Limit to 20 elements
            desc = f"{el.tag}"
            if el.element_type:
                desc += f"[{el.element_type}]"
            if el.text:
                desc += f" '{el.text[:30]}'"
            elif el.placeholder:
                desc += f" placeholder='{el.placeholder}'"
            elif el.aria_label:
                desc += f" aria='{el.aria_label}'"
            desc += f" -> {el.selector}"
            elements_summary.append(desc)

        return f"""URL: {self.url}
Title: {self.title}
Popup: {self.popup_type if self.has_popup else 'None'}
Elements ({len(self.interactable_elements)} total, showing first 20):
{chr(10).join(elements_summary)}
Key Content: {self.key_text_content}"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "element_count": len(self.interactable_elements),
            "has_popup": self.has_popup,
            "popup_type": self.popup_type,
            "key_content": self.key_text_content,
        }


@dataclass
class TaskStep:
    """Individual task step with status and metadata."""
    step_id: int
    action: str
    description: str
    status: StepStatus = StepStatus.PENDING
    expected_state: str | None = None
    challenge: str | None = None
    extract_fields: list[str] = field(default_factory=list)
    extracted_data: dict[str, Any] = field(default_factory=dict)
    screenshot_path: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    depends_on: list[int] = field(default_factory=list)
    requires_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "description": self.description,
            "status": self.status.value,
            "extracted_data": self.extracted_data,
            "screenshot_path": self.screenshot_path,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "duration_ms": self.duration_ms,
        }


@dataclass
class EmployeeInfo:
    """Extracted employee information."""
    employee_id: int | None = None
    name: str | None = None
    department: str | None = None
    position: str | None = None
    hire_date: str | None = None
    annual_leave_balance: float | None = None
    performance_score: float | None = None
    gender: str | None = None
    email: str | None = None
    phone: str | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class LeaveRequest:
    """Leave request data."""
    request_id: int | None = None
    employee_name: str | None = None
    department: str | None = None
    leave_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    reason: str | None = None
    status: str | None = None
    emergency_contact: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class AttendanceReport:
    """Attendance statistics."""
    department: str
    month: str
    total_staff: int
    avg_attendance_rate: float
    late_count: int
    early_leave_count: int
    absent_count: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class DashboardStats:
    """Dashboard statistics."""
    total_employees: int | None = None
    pending_leaves: int | None = None
    new_hires: int | None = None
    contract_expiring: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Screenshot:
    """Screenshot metadata."""
    path: str
    step_id: int
    url: str
    timestamp: datetime = field(default_factory=datetime.now)
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "step_id": self.step_id,
            "url": self.url,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
        }


@dataclass
class TaskResult:
    """Final task execution result."""
    success: bool
    total_steps: int
    completed_steps: int
    failed_steps: int
    skipped_steps: int
    extracted_data: dict[str, Any] = field(default_factory=dict)
    screenshots: list[Screenshot] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    execution_time_ms: int = 0
    trajectory_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "extracted_data": self.extracted_data,
            "screenshots": [s.to_dict() for s in self.screenshots],
            "errors": self.errors,
            "execution_time_ms": self.execution_time_ms,
            "trajectory_path": self.trajectory_path,
        }

    def to_report(self) -> str:
        """Generate human-readable report."""
        lines = [
            "=" * 60,
            "Browser Agent Task Execution Report",
            "=" * 60,
            "",
            f"Status: {'SUCCESS' if self.success else 'FAILED'}",
            f"Steps: {self.completed_steps}/{self.total_steps} completed",
            f"Failed: {self.failed_steps}, Skipped: {self.skipped_steps}",
            f"Execution Time: {self.execution_time_ms}ms",
            "",
            "-" * 40,
            "Extracted Data:",
            "-" * 40,
        ]

        for key, value in self.extracted_data.items():
            if isinstance(value, dict):
                lines.append(f"  {key}:")
                for k, v in value.items():
                    lines.append(f"    {k}: {v}")
            else:
                lines.append(f"  {key}: {value}")

        if self.errors:
            lines.extend([
                "",
                "-" * 40,
                "Errors:",
                "-" * 40,
            ])
            for err in self.errors:
                lines.append(f"  - {err}")

        lines.extend([
            "",
            "-" * 40,
            f"Screenshots: {len(self.screenshots)} captured",
            "-" * 40,
        ])
        for ss in self.screenshots:
            lines.append(f"  Step {ss.step_id}: {ss.path}")

        if self.trajectory_path:
            lines.extend([
                "",
                f"Trajectory Log: {self.trajectory_path}",
            ])

        lines.append("=" * 60)
        return "\n".join(lines)
