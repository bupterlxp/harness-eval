"""Anthropic Messages-compatible client (lazy ``requests``). No import-time network.

``requests`` is imported lazily inside :meth:`complete`; if missing, a structured
:class:`DependencyError` is raised. All HTTP calls are time-bounded.

NO third-party imports at module top level.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from ..core.errors import ProviderError
from .client import LLMClient, LLMResponse


class AnthropicLikeClient(LLMClient):
    name = "anthropic_like"

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "https://api.anthropic.com",
        api_key: Optional[str] = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        anthropic_version: str = "2023-06-01",
        default_timeout: float = 120.0,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get(api_key_env)
        self.anthropic_version = anthropic_version
        self.default_timeout = float(default_timeout)
        self.max_tokens = int(max_tokens)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        **opts: Any,
    ) -> LLMResponse:
        from ..core.dependency import require

        requests = require("requests", extra="http", purpose="Anthropic-compatible HTTP client")

        if not self._api_key:
            raise ProviderError(
                "missing API key for Anthropic-compatible client",
                stage="llm",
                details={"hint": "set api_key or ANTHROPIC_API_KEY"},
                recoverable=False,
            )

        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }

        # Split out any system message(s) per Anthropic Messages API shape.
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        chat = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": chat,
            "max_tokens": int(opts.get("max_tokens", self.max_tokens)),
        }
        if system_parts:
            payload["system"] = "\n\n".join(str(s) for s in system_parts)
        if tools:
            payload["tools"] = tools
        for k in ("temperature", "top_p", "stop_sequences", "tool_choice"):
            if k in opts:
                payload[k] = opts[k]

        to = float(timeout if timeout is not None else self.default_timeout)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=to)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Anthropic-compatible request failed: {type(exc).__name__}: {exc}",
                stage="llm",
                details={"url": url, "exception_type": type(exc).__name__},
                recoverable=True,
            ) from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"Anthropic-compatible HTTP {resp.status_code}",
                stage="llm",
                details={"status_code": resp.status_code, "body_preview": resp.text[:500]},
                recoverable=resp.status_code in (429, 500, 502, 503, 504),
            )

        data = resp.json()
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in data.get("content", []) or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(block)
        usage = data.get("usage", {}) or {}
        self._account(usage)
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            raw=data,
            model=data.get("model", self.model),
        )
