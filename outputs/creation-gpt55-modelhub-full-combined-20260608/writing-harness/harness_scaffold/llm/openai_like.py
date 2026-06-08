"""OpenAI-compatible chat client (lazy ``requests``). No import-time network.

Targets any OpenAI-compatible ``/v1/chat/completions`` endpoint. ``requests`` is
imported lazily inside :meth:`complete`; if missing, a structured
:class:`DependencyError` is raised. All HTTP calls are time-bounded.

NO third-party imports at module top level.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from ..core.errors import ProviderError
from .client import LLMClient, LLMResponse


class OpenAILikeClient(LLMClient):
    name = "openai_like"

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        default_timeout: float = 120.0,
        organization: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key or os.environ.get(api_key_env)
        self.default_timeout = float(default_timeout)
        self.organization = organization

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        **opts: Any,
    ) -> LLMResponse:
        # Lazy import: missing -> structured dependency error.
        from ..core.dependency import require

        requests = require("requests", extra="http", purpose="OpenAI-compatible HTTP client")

        if not self._api_key:
            raise ProviderError(
                "missing API key for OpenAI-compatible client",
                stage="llm",
                details={"hint": "set api_key or OPENAI_API_KEY"},
                recoverable=False,
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization

        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        for k in ("temperature", "max_tokens", "top_p", "stop", "tool_choice"):
            if k in opts:
                payload[k] = opts[k]

        to = float(timeout if timeout is not None else self.default_timeout)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=to)
        except Exception as exc:  # noqa: BLE001 - network/transport
            raise ProviderError(
                f"OpenAI-compatible request failed: {type(exc).__name__}: {exc}",
                stage="llm",
                details={"url": url, "exception_type": type(exc).__name__},
                recoverable=True,
            ) from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"OpenAI-compatible HTTP {resp.status_code}",
                stage="llm",
                details={"status_code": resp.status_code, "body_preview": resp.text[:500]},
                recoverable=resp.status_code in (429, 500, 502, 503, 504),
            )

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        text = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []
        usage = data.get("usage", {}) or {}
        self._account(usage)
        return LLMResponse(
            text=text, tool_calls=tool_calls, usage=usage, raw=data, model=data.get("model", self.model)
        )
