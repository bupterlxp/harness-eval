"""
Code Agent Harness - A structured agent for automated bug fixing.

Components:
- E (Execution): State machine for fix workflow
- T (Tools): Registry of code manipulation tools
- C (Context): Source/test/history context management
- S (State): Bug tracking and snapshots
- L (Lifecycle): Hooks for backup/rollback
- V (Evaluation): JSONL trajectory recording
"""

from harness.core import CodeAgentHarness
from harness.schemas import BugReport, BugSeverity, BugStatus

__all__ = ["CodeAgentHarness", "BugReport", "BugSeverity", "BugStatus"]
