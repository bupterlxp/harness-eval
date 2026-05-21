"""
Code Agent Harness - A modular agent for software engineering tasks.

Components:
- execution: State machine execution loop (E)
- tools: Tool registry with file/search/exec capabilities (T)
- context: Context manager with summarization (C)
- state: State store with snapshot/rollback (S)
- lifecycle: Lifecycle hooks for backup/rollback/timeout (L)
- evaluation: Trajectory logging in JSONL format (V)
"""

from harness import execution, tools, context, state, lifecycle, evaluation

__all__ = [
    "execution",
    "tools",
    "context",
    "state",
    "lifecycle",
    "evaluation",
]
