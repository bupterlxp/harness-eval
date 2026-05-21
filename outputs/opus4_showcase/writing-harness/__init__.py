"""Creative Writing Agent Harness.

A complete, runnable harness that accepts writing task specifications
(genre, style, constraints) and autonomously completes the full creative
process from planning to final draft.

Architecture: H = (E, T, C, S, L, V)
- E: execution.py  — Execution Loop (FSM)
- T: tools.py      — Tool Registry
- C: context.py    — Context Manager
- S: state.py      — State Store
- L: lifecycle.py  — Lifecycle Hooks
- V: evaluation.py — Evaluation Interface
"""

from harness import execution, tools, context, state, lifecycle, evaluation

__all__ = ["execution", "tools", "context", "state", "lifecycle", "evaluation"]
