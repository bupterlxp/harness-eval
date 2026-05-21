"""Creative Writing Agent Harness

A generic creative writing harness that accepts writing task specifications and
completes the full创作流程 from planning to final manuscript."""

__version__ = "0.1.0"

# Import core components
from .execution import ExecutionLoop, ExecutionPhase, ExecutionState
from .tools import ToolRegistry, Tool
from .context import ContextManager, ContextSnapshot, StyleAnchor
from .state import StateStore, SceneState, ManuscriptState
from .lifecycle import LifecycleHooks, HookContext
from .evaluation import EvaluationLogger, EvaluationEvent


__all__ = [
    "ExecutionLoop",
    "ExecutionPhase",
    "ExecutionState",
    "ToolRegistry",
    "Tool",
    "ContextManager",
    "ContextSnapshot",
    "StyleAnchor",
    "StateStore",
    "SceneState",
    "ManuscriptState",
    "LifecycleHooks",
    "HookContext",
    "EvaluationLogger",
    "EvaluationEvent",
]
