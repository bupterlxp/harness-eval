"""
Browser Agent Harness - Digital Employee / Browser Agent

A complete automation framework for multi-step web task execution.
"""

__version__ = "1.0.0"
__author__ = "Harness Eval"

from .schemas import (
    TaskStatus,
    PopupType,
    StepResult,
    EmployeeInfo,
    LeaveRequest,
    AttendanceRecord,
    TaskContext,
    PageState,
    Config
)

from .tools import BrowserTools
from .context import ContextManager
from .domain.popup import PopupHandler
from .lifecycle import LifecycleHooks
from .evaluation import EvaluationRecorder
from .execution import ExecutionEngine
from .cli import BrowserAgent, main


__all__ = [
    # Schemas
    "TaskStatus",
    "PopupType",
    "StepResult",
    "EmployeeInfo",
    "LeaveRequest",
    "AttendanceRecord",
    "TaskContext",
    "PageState",
    "Config",

    # Core components
    "BrowserTools",
    "ContextManager",
    "PopupHandler",
    "LifecycleHooks",
    "EvaluationRecorder",
    "ExecutionEngine",

    # CLI
    "BrowserAgent",
    "main"
]