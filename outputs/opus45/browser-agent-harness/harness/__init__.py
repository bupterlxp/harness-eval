"""
Browser Agent Harness - A framework for browser automation and multi-step web task execution.

This harness implements a six-component architecture (H = E, T, C, S, L, V):
- E: Execution Loop (dual-layer state machine)
- T: Tool Registry (browser operation tools)
- C: Context Manager (page, task, navigation contexts)
- S: State Store (task graph, cross-page data, checkpoints)
- L: Lifecycle Hooks (navigation, popup, timeout handling)
- V: Evaluation Interface (JSONL trajectory logging)
"""

from harness.core import BrowserAgentHarness
from harness.schemas import (
    TaskStep,
    StepStatus,
    PageState,
    EmployeeInfo,
    LeaveRequest,
    AttendanceReport,
    Screenshot,
    TaskResult,
)
from harness.state import TaskGraph, CrossPageDataStore
from harness.context import PageContext, TaskContext, NavigationHistory
from harness.tools import ToolRegistry
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryLogger
from harness.execution import ExecutionEngine

__version__ = "1.0.0"
__all__ = [
    "BrowserAgentHarness",
    "TaskStep",
    "StepStatus",
    "PageState",
    "EmployeeInfo",
    "LeaveRequest",
    "AttendanceReport",
    "Screenshot",
    "TaskResult",
    "TaskGraph",
    "CrossPageDataStore",
    "PageContext",
    "TaskContext",
    "NavigationHistory",
    "ToolRegistry",
    "LifecycleManager",
    "TrajectoryLogger",
    "ExecutionEngine",
]
