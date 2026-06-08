"""ToolRegistry + lazy default registry discovery.

The registry holds AtomicTool instances by name and can produce LLM-facing
specs and filtered views. ``default_registry()`` lazily imports each leaf tool
module and collects its tools, guarded so a single broken/optional tool module
never breaks the whole registry.

NO third-party imports.
"""

from __future__ import annotations

import importlib
from typing import Any, Iterable, Optional

from .base import AtomicTool


class ToolRegistry:
    def __init__(self, tools: Optional[Iterable[AtomicTool]] = None) -> None:
        self._tools: dict[str, AtomicTool] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: AtomicTool, *, override: bool = False) -> AtomicTool:
        if tool.name in self._tools and not override:
            raise ValueError(f"tool already registered: {tool.name!r}")
        self._tools[tool.name] = tool
        return tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> AtomicTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"no such tool: {name!r}") from exc

    def has(self, name: str) -> bool:
        return name in self._tools

    def list(self) -> list[AtomicTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def specs(self) -> list[dict[str, Any]]:
        """JSON-schema specs for advertising tools to an LLM."""
        return [t.spec() for t in self._tools.values()]

    def filtered(
        self,
        *,
        read_only: Optional[bool] = None,
        network: Optional[bool] = None,
        destructive: Optional[bool] = None,
    ) -> "ToolRegistry":
        out: list[AtomicTool] = []
        for t in self._tools.values():
            if read_only is not None and t.is_read_only != read_only:
                continue
            if network is not None and t.requires_network != network:
                continue
            if destructive is not None and t.is_destructive != destructive:
                continue
            out.append(t)
        return ToolRegistry(out)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def __iter__(self):
        return iter(self._tools.values())


# --------------------------------------------------------------------------- #
# Default registry: lazily import leaf tool modules and collect their tools.
# --------------------------------------------------------------------------- #

# (module_name, optional) — optional modules that fail to import are skipped.
_DEFAULT_TOOL_MODULES: list[tuple[str, bool]] = [
    ("file_read", False),
    ("file_write", False),
    ("file_edit", False),
    ("glob", False),
    ("grep", False),
    ("tree", False),
    ("search", False),
    ("bash", False),
    ("python_exec", False),
    ("git", False),
    ("patch", False),
    ("json_io", False),
    ("todo", False),
    ("task", False),
    ("task_graph", False),
    ("checkpoint", False),
    ("context_compactor", False),
    ("mcp_tool_discovery", False),
    ("domain_artifact_validator", False),
    ("repair_feedback", False),
    ("cost_tracker", False),
    ("artifact", False),
    ("web_fetch", True),
    ("web_search", True),
    ("browser", True),
    ("notebook", True),
    ("lsp", True),
]


def _collect_from_module(mod: Any) -> list[AtomicTool]:
    """Collect tools from a leaf module via get_tools() or TOOLS or classes."""
    tools: list[AtomicTool] = []
    get_tools = getattr(mod, "get_tools", None)
    if callable(get_tools):
        try:
            collected = get_tools()
            for t in collected:
                if isinstance(t, AtomicTool):
                    tools.append(t)
            return tools
        except Exception:  # pragma: no cover - guarded
            return tools
    module_tools = getattr(mod, "TOOLS", None)
    if isinstance(module_tools, (list, tuple)):
        for t in module_tools:
            if isinstance(t, AtomicTool):
                tools.append(t)
        if tools:
            return tools
    # Last resort: instantiate AtomicTool subclasses defined in the module.
    for attr in vars(mod).values():
        if isinstance(attr, type) and issubclass(attr, AtomicTool) and attr is not AtomicTool:
            try:
                tools.append(attr())
            except Exception:  # pragma: no cover - guarded
                continue
    return tools


def discover(*, include_optional: bool = True) -> list[AtomicTool]:
    """Import known leaf tool modules and return all collected tool instances.

    Guarded: a failing optional module is skipped; a failing required module is
    skipped too (so the registry is always constructible even mid-build).
    """
    tools: list[AtomicTool] = []
    for mod_name, optional in _DEFAULT_TOOL_MODULES:
        if optional and not include_optional:
            continue
        try:
            mod = importlib.import_module(f"harness_scaffold.tools.{mod_name}")
        except Exception:  # noqa: BLE001 - missing leaf module is tolerated
            continue
        tools.extend(_collect_from_module(mod))
    return tools


def default_registry(*, include_optional: bool = True) -> ToolRegistry:
    """Build a ToolRegistry from all discoverable leaf tool modules.

    De-duplicates by tool name (first wins). Always returns a valid registry,
    even if some/all leaf tool modules are not present yet.
    """
    reg = ToolRegistry()
    for tool in discover(include_optional=include_optional):
        if not reg.has(tool.name):
            reg.register(tool)
    return reg
