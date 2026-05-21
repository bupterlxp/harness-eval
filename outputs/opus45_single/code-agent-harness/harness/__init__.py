"""
Code Agent Harness - A general-purpose code intelligence agent.

This harness accepts software engineering tasks (bug fixes, features, refactors)
and autonomously completes code modifications with verification.
"""

from harness import execution, tools, context, state, lifecycle, evaluation

__version__ = "0.1.0"
__all__ = ["execution", "tools", "context", "state", "lifecycle", "evaluation"]
