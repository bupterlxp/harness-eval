"""Data Analysis Agent Harness.

A complete, runnable harness that accepts data files and analysis task
descriptions, then autonomously performs data exploration, statistical
analysis, visualization, and report generation using a Plan-Code-Observe
ReAct loop.

Architecture: H = (E, T, C, S, L, V)
  E - execution.py  : FSM-driven execution loop
  T - tools.py      : Tool registry and dispatch
  C - context.py    : Context management with token budget
  S - state.py      : State persistence and checkpoint recovery
  L - lifecycle.py  : Lifecycle hooks at key boundaries
  V - evaluation.py : Trajectory recording as JSONL
"""

from harness import execution, tools, context, state, lifecycle, evaluation

__all__ = ["execution", "tools", "context", "state", "lifecycle", "evaluation"]
