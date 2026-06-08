"""Optional-dependency handling. LAZY import; NEVER auto-install.

A missing optional dependency must produce a structured
:class:`DependencyError` that names the pip extra to install, rather than
hanging the experiment on an online install. ``check_dependencies`` probes
importability with a short per-module timeout so a broken package's
import-time side effects cannot stall the run.

NO third-party imports at module top level.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Optional

from .errors import DependencyError

# Map well-known module names -> the pip extra that provides them.
_EXTRA_BY_MODULE: dict[str, str] = {
    "playwright": "browser",
    "requests": "http",
    "bs4": "html",
    "beautifulsoup4": "html",
    "pytest": "test",
}


def extra_for(module_name: str) -> Optional[str]:
    return _EXTRA_BY_MODULE.get(module_name.split(".")[0])


def require(module_name: str, *, extra: Optional[str] = None, purpose: Optional[str] = None) -> ModuleType:
    """Import ``module_name`` lazily; raise structured DependencyError if missing.

    ``extra`` overrides the auto-detected pip extra name in the message.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        pip_extra = extra or extra_for(module_name)
        hint = (
            f"pip install 'harness_scaffold[{pip_extra}]'"
            if pip_extra
            else f"pip install {module_name}"
        )
        raise DependencyError(
            f"optional dependency '{module_name}' is not installed",
            stage="dependency",
            details={
                "module": module_name,
                "pip_extra": pip_extra,
                "install_hint": hint,
                "purpose": purpose,
                "import_error": str(exc),
            },
            recoverable=False,
        ) from exc


def probe_optional(names: list[str], *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Probe a list of modules for importability with a SHORT timeout each.

    Returns ``{module: {"available": bool, "extra": str|None, "error": str|None}}``.
    Never raises; never installs anything.
    """
    # Local import to avoid a top-level dependency on timeouts in this module's
    # import graph (keeps dependency.py importable in isolation).
    from .timeouts import run_with_timeout
    from .errors import TimeoutErrorH

    report: dict[str, Any] = {}
    for name in names:
        entry: dict[str, Any] = {"available": False, "extra": extra_for(name), "error": None}
        try:
            run_with_timeout(importlib.import_module, timeout_seconds, name, stage="dependency")
            entry["available"] = True
        except TimeoutErrorH:
            entry["error"] = f"import timed out after {timeout_seconds}s"
        except ImportError as exc:
            entry["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - any import-time crash
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report[name] = entry
    return report


def check_dependencies(names: list[str], *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Like ``probe_optional`` but adds a summary and a structured overall report."""
    probe = probe_optional(names, timeout_seconds=timeout_seconds)
    missing = [n for n, e in probe.items() if not e["available"]]
    return {
        "checked": list(names),
        "missing": missing,
        "all_available": len(missing) == 0,
        "details": probe,
    }
