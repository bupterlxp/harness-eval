"""Adapters: CLI, task-json, out-dir IO, generated-program loading, judge IO."""

from __future__ import annotations

from . import bmk_io
from .generated_harness_adapter import (
    FunctionProgram,
    extract_program,
    load_program,
    preflight_program,
)
from .task_json import example_task, load_task, parse_task

__all__ = [
    "bmk_io",
    "load_task",
    "parse_task",
    "example_task",
    "load_program",
    "extract_program",
    "preflight_program",
    "FunctionProgram",
]
