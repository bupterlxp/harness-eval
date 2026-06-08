"""harness_scaffold: a universal agent-harness runtime + atomic capabilities.

Public API. Import the contract types and runtime from here; leaf tool classes
are available lazily via attribute access so importing the package never pulls in
optional third-party dependencies.

Stdlib-only core. Optional features (browser/http/html) lazy-import their deps
and raise a structured ``DependencyError`` when missing.
"""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "0.1.0"

# --- Core contract (eager, stdlib-only) ----------------------------------- #
from .core.abort import AbortSignal
from .core.artifacts import ArtifactStore
from .core.budgets import Budget
from .core.context import RuntimeContext, build_context
from .core.dependency import check_dependencies, probe_optional, require
from .core import events
from .core.errors import (
    AdapterError,
    ArtifactError,
    BrowserError,
    ContractError,
    DependencyError,
    ErrorCode,
    FilesystemError,
    HarnessError,
    InvalidHarnessError,
    LLMError,
    PermissionDenied,
    ProviderError,
    ShellError,
    TimeoutErrorH,
    ToolError,
    build_error_json,
    error_from_exception,
)
from .core.permissions import PermissionPolicy
from .core.runtime import HarnessRuntime, build_failed_result
from .core.schemas import (
    HarnessResult,
    HarnessStatus,
    HarnessTask,
    RetryPolicy,
    RuntimePolicy,
    ToolResult,
)
from .core.trajectory import TrajectoryLogger

# --- Tool layer (eager: base + registry only) ----------------------------- #
from .tools.base import AtomicTool
from .tools.registry import ToolRegistry, default_registry, discover

# --- LLM layer (eager: abstract + mock; providers lazy) ------------------- #
from .llm.client import LLMClient, LLMResponse
from .llm.mock import MockLLMClient

__all__ = [
    "__version__",
    # task/result/tool
    "HarnessTask",
    "HarnessResult",
    "HarnessStatus",
    "ToolResult",
    # policies
    "RuntimePolicy",
    "RetryPolicy",
    # runtime/context
    "RuntimeContext",
    "build_context",
    "HarnessRuntime",
    "build_failed_result",
    # services
    "ArtifactStore",
    "TrajectoryLogger",
    "PermissionPolicy",
    "Budget",
    "AbortSignal",
    # tools
    "AtomicTool",
    "ToolRegistry",
    "default_registry",
    "discover",
    # llm
    "LLMClient",
    "LLMResponse",
    "MockLLMClient",
    # helpers
    "events",
    "require",
    "probe_optional",
    "check_dependencies",
    # errors / taxonomy
    "ErrorCode",
    "HarnessError",
    "DependencyError",
    "PermissionDenied",
    "TimeoutErrorH",
    "ToolError",
    "ProviderError",
    "ContractError",
    "AdapterError",
    "BrowserError",
    "ShellError",
    "FilesystemError",
    "ArtifactError",
    "LLMError",
    "InvalidHarnessError",
    "build_error_json",
    "error_from_exception",
]

# Tool classes that may be referenced lazily from the top-level package, e.g.
# ``harness_scaffold.BashTool``. Maps public name -> (submodule, attribute).
_LAZY_TOOLS = {
    "FileReadTool": ("tools.file_read", "FileReadTool"),
    "FileWriteTool": ("tools.file_write", "FileWriteTool"),
    "FileEditTool": ("tools.file_edit", "FileEditTool"),
    "GlobTool": ("tools.glob", "GlobTool"),
    "GrepTool": ("tools.grep", "GrepTool"),
    "TreeTool": ("tools.tree", "TreeTool"),
    "SearchTool": ("tools.search", "SearchTool"),
    "BashTool": ("tools.bash", "BashTool"),
    "PythonExecTool": ("tools.python_exec", "PythonExecTool"),
    "GitStatusTool": ("tools.git", "GitStatusTool"),
    "GitDiffTool": ("tools.git", "GitDiffTool"),
    "ApplyPatchTool": ("tools.patch", "ApplyPatchTool"),
    "JsonIOTool": ("tools.json_io", "JsonIOTool"),
    "WebFetchTool": ("tools.web_fetch", "WebFetchTool"),
    "WebSearchTool": ("tools.web_search", "WebSearchTool"),
    "BrowserTool": ("tools.browser", "BrowserTool"),
    "TodoTool": ("tools.todo", "TodoTool"),
    "TaskTool": ("tools.task", "TaskTool"),
    "ArtifactTool": ("tools.artifact", "ArtifactTool"),
    "NotebookTool": ("tools.notebook", "NotebookTool"),
    "LSPTool": ("tools.lsp", "LSPTool"),
    # LLM providers (lazy deps)
    "OpenAILikeClient": ("llm.openai_like", "OpenAILikeClient"),
    "AnthropicLikeClient": ("llm.anthropic_like", "AnthropicLikeClient"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_TOOLS.get(name)
    if target is not None:
        submodule, attr = target
        mod = importlib.import_module(f"{__name__}.{submodule}")
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
