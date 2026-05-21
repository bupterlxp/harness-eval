"""Browser Agent Harness - A general-purpose browser automation framework.

This harness accepts web task descriptions and autonomously executes multi-step
browser operations including navigation, form filling, data extraction, and file downloads.

Architecture Components (H = (E, T, C, S, L, V)):
- E (execution): Execution loop with explicit state machine
- T (tools): Browser operation tool registry
- C (context): Page context manager with accessibility tree summarization
- S (state): Task state persistence with checkpoint/resume support
- L (lifecycle): Page event and lifecycle hooks
- V (evaluation): Operation trajectory recording
"""

from harness.state import StateStore, TaskState, StepState
from harness.context import ContextManager
from harness.tools import ToolRegistry
from harness.lifecycle import LifecycleHooks
from harness.evaluation import TrajectoryRecorder
from harness.execution import ExecutionLoop, BrowserAgent

__version__ = "0.1.0"

__all__ = [
    "StateStore",
    "TaskState",
    "StepState",
    "ContextManager",
    "ToolRegistry",
    "LifecycleHooks",
    "TrajectoryRecorder",
    "ExecutionLoop",
    "BrowserAgent",
]
