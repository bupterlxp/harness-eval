"""
Data Analysis Agent Harness

A six-component harness for data analysis tasks:
- E: Execution Loop (state machine)
- T: Tool Registry
- C: Context Manager
- S: State Store
- L: Lifecycle Hooks
- V: Evaluation Interface
"""

from harness.core import DataAnalysisHarness
from harness.schemas import (
    DataProfile,
    AnalysisStep,
    ChartRecord,
    Insight,
    ValidationResult,
    AnalysisState,
)

__all__ = [
    "DataAnalysisHarness",
    "DataProfile",
    "AnalysisStep",
    "ChartRecord",
    "Insight",
    "ValidationResult",
    "AnalysisState",
]

__version__ = "1.0.0"
