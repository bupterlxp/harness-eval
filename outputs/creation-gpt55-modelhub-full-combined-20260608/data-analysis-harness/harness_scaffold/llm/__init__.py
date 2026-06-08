"""LLM client layer.

Eagerly exports the abstract client, response type, and the mock (all
stdlib-only). Provider clients (openai_like, anthropic_like) are importable but
defer their third-party deps to call time.
"""

from __future__ import annotations

import importlib
from typing import Any

from .client import LLMClient, LLMResponse
from .mock import MockLLMClient
from .rate_limit import TokenBucket
from .retry_policy import (
    default_llm_retry_policy,
    retry_llm_async,
    retry_llm_sync,
)

__all__ = [
    "LLMClient",
    "LLMResponse",
    "MockLLMClient",
    "TokenBucket",
    "default_llm_retry_policy",
    "retry_llm_sync",
    "retry_llm_async",
    "OpenAILikeClient",
    "AnthropicLikeClient",
]

_LAZY = {
    "OpenAILikeClient": ("openai_like", "OpenAILikeClient"),
    "AnthropicLikeClient": ("anthropic_like", "AnthropicLikeClient"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        mod_name, attr = _LAZY[name]
        mod = importlib.import_module(f"{__name__}.{mod_name}")
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
