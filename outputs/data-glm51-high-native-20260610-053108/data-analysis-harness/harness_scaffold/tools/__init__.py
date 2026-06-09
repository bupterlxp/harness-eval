"""Atomic tools package.

Exposes the tool base classes and the registry eagerly (stdlib-only), and leaf
tool modules lazily via ``__getattr__`` so importing this package never pulls in
optional dependencies. Leaf tool modules are authored by later agents; the
registry's ``default_registry()`` tolerates their absence.
"""

from __future__ import annotations

import importlib
from typing import Any

from .base import AtomicTool, SubprocessResult, _run_subprocess
from .registry import ToolRegistry, default_registry, discover

__all__ = [
    "AtomicTool",
    "SubprocessResult",
    "ToolRegistry",
    "default_registry",
    "discover",
]

# Leaf module names that may be imported lazily by attribute access.
_LEAF_MODULES = {
    "file_read",
    "file_write",
    "file_edit",
    "glob",
    "grep",
    "tree",
    "search",
    "bash",
    "python_exec",
    "git",
    "patch",
    "json_io",
    "web_fetch",
    "web_search",
    "browser",
    "todo",
    "task",
    "artifact",
    "notebook",
    "lsp",
}


def __getattr__(name: str) -> Any:
    if name in _LEAF_MODULES:
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
