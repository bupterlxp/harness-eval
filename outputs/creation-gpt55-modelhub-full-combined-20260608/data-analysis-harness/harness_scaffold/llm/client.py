"""LLM client abstraction.

Provider-neutral interface. Concrete clients (openai_like, anthropic_like) lazy
import their SDK / requests inside methods so importing this package never
requires network access or third-party packages. All calls are bounded by
``max_llm_seconds`` and surface structured :class:`ProviderError`.

NO third-party imports at module top level.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    model: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": list(self.tool_calls),
            "usage": dict(self.usage),
            "model": self.model,
        }


class LLMClient(abc.ABC):
    """Abstract async LLM client.

    Implementations must enforce a timeout (default from policy/opts) and raise
    :class:`harness_scaffold.core.errors.ProviderError` on transport/HTTP
    failures, never blocking indefinitely.
    """

    name: str = "llm"
    model: Optional[str] = None

    def __init__(self) -> None:
        self.usage: dict[str, Any] = {}

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        **opts: Any,
    ) -> LLMResponse:
        """Return a single completion. MUST be time-bounded."""
        raise NotImplementedError

    def _account(self, usage: dict[str, Any]) -> None:
        for k, v in (usage or {}).items():
            if isinstance(v, (int, float)):
                self.usage[k] = self.usage.get(k, 0) + v
            else:
                self.usage[k] = v
