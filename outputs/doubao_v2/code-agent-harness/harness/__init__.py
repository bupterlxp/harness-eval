"""
Code Intelligence Harness
A general-purpose code intelligence agent that can perform software engineering tasks
"""

__version__ = "0.1.0"

# Import core components
from .execution import ExecutionLoop, ExecutionState, TaskStep
from .tools import ToolRegistry, Tool, ToolSchema
from .context import ContextManager, ContextItem, ContextCompressor, SimpleContextCompressor
from .state import StateStore, StateSnapshot
from .lifecycle import LifecycleHooks
from .evaluation import Evaluator, EvaluationStep


__all__ = [
    "ExecutionLoop",
    "ExecutionState",
    "TaskStep",
    "ToolRegistry",
    "Tool",
    "ToolSchema",
    "ContextManager",
    "ContextItem",
    "ContextCompressor",
    "SimpleContextCompressor",
    "StateStore",
    "StateSnapshot",
    "LifecycleHooks",
    "Evaluator",
    "EvaluationStep",
    "__version__"
]