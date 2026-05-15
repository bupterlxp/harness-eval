"""
Short Story Writing Harness

A structured agent harness implementing the H = (E, T, C, S, L, V) formalism
for generating psychological thriller short stories.
"""

__version__ = "0.1.0"

def __getattr__(name: str):
    if name == "Harness":
        from harness.core import Harness
        return Harness
    if name == "TaskSpec":
        from harness.schemas import TaskSpec
        return TaskSpec
    if name == "ExecutionState":
        from harness.schemas import ExecutionState
        return ExecutionState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["Harness", "TaskSpec", "ExecutionState"]
