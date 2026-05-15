#!/usr/bin/env python3
"""Short Story Generation Harness

A complete agent harness for generating short stories following formal specifications.
"""

from .core import Harness
from .schemas import (
    StoryGenre, Perspective, ImageryEntry, Scene, PlotOutline,
    TaskSpec, NarratorProfile, ConsistencyReport, GenerationState,
    TrajectoryEntry, SessionInfo, DiffReport
)
from .state import StateStore
from .context import ContextManager
from .tools import ToolRegistry, ToolBase, ToolCallResult, ToolResultStatus
from .lifecycle import HookManager, HookEvent, HookEventType
from .evaluation import TrajectoryRecorder
from .execution import ExecutionLoop, ExecutionStepResult

__version__ = "0.1.0"
__author__ = "Claude Code Agent"

__all__ = [
    "Harness",
    "StoryGenre", "Perspective", "ImageryEntry", "Scene", "PlotOutline",
    "TaskSpec", "NarratorProfile", "ConsistencyReport", "GenerationState",
    "TrajectoryEntry", "SessionInfo", "DiffReport",
    "StateStore", "ContextManager", "ToolRegistry", "ToolBase",
    "ToolCallResult", "ToolResultStatus", "HookManager", "HookEvent",
    "HookEventType", "TrajectoryRecorder", "ExecutionLoop", "ExecutionStepResult"
]