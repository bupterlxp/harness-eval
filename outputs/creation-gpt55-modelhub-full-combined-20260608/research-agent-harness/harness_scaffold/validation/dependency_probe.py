"""Probe optional dependencies with a short timeout. Structured report. No install.

Thin convenience wrapper over :func:`harness_scaffold.core.dependency`.

NO third-party imports.
"""

from __future__ import annotations

from typing import Any, Optional

from ..core.dependency import check_dependencies, extra_for, probe_optional

# The optional deps this scaffold knows about.
KNOWN_OPTIONAL = ["requests", "bs4", "playwright"]


def probe(names: Optional[list[str]] = None, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    return check_dependencies(names or KNOWN_OPTIONAL, timeout_seconds=timeout_seconds)


def probe_one(name: str, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    report = probe_optional([name], timeout_seconds=timeout_seconds)
    entry = report[name]
    entry["extra"] = entry.get("extra") or extra_for(name)
    return entry
