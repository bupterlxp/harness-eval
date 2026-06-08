"""Deterministic mock LLM client. No network; for tests/smoke/examples."""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence, Union

from .client import LLMClient, LLMResponse

ScriptItem = Union[str, LLMResponse, dict, Callable[[list[dict[str, Any]]], "LLMResponse | str"]]


class MockLLMClient(LLMClient):
    """Returns scripted responses in order; loops on the last when exhausted.

    ``scripted`` items may be:
      * str -> LLMResponse(text=...)
      * dict -> LLMResponse(**dict)
      * LLMResponse -> as-is
      * callable(messages) -> str | LLMResponse (dynamic, still deterministic)
    """

    name = "mock"

    def __init__(
        self,
        scripted: Optional[Sequence[ScriptItem]] = None,
        *,
        model: str = "mock-model",
        default_text: str = "",
    ) -> None:
        super().__init__()
        self.model = model
        self._script: list[ScriptItem] = list(scripted or [])
        self._default_text = default_text
        self._i = 0
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        timeout: Optional[float] = None,
        **opts: Any,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "opts": opts})
        item = self._next()
        resp = self._coerce(item, messages)
        if not resp.model:
            resp.model = self.model
        if not resp.usage:
            resp.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._account(resp.usage)
        return resp

    def _next(self) -> ScriptItem:
        if not self._script:
            return self._default_text
        if self._i < len(self._script):
            item = self._script[self._i]
            self._i += 1
            return item
        return self._script[-1]

    def _coerce(self, item: ScriptItem, messages: list[dict[str, Any]]) -> LLMResponse:
        if callable(item) and not isinstance(item, (str, dict, LLMResponse)):
            item = item(messages)
        if isinstance(item, LLMResponse):
            return item
        if isinstance(item, str):
            return LLMResponse(text=item)
        if isinstance(item, dict):
            return LLMResponse(**item)
        return LLMResponse(text=str(item))
