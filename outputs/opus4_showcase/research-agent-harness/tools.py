"""Tool Registry - tool registration and dispatch with input/output schemas.

Provides a pluggable tool system for search, fetch, and LLM operations.
Tools are registered with typed schemas and dispatched by name.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import httpx
from openai import AsyncOpenAI


@dataclass
class ToolSchema:
    """Defines input/output schema for a tool."""
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


@dataclass
class ToolResult:
    """Result of a tool invocation."""
    tool_name: str
    success: bool
    data: Any
    error: str | None = None
    duration_ms: float = 0.0


ToolFunction = Callable[..., Awaitable[ToolResult]]


class ToolRegistry:
    """Registry for tool functions with schema validation and dispatch."""

    def __init__(self):
        self._tools: dict[str, ToolFunction] = {}
        self._schemas: dict[str, ToolSchema] = {}
        self._llm_client: AsyncOpenAI | None = None
        self._http_client: httpx.AsyncClient | None = None

    def register(self, schema: ToolSchema, func: ToolFunction) -> None:
        """Register a tool with its schema and implementation."""
        self._tools[schema.name] = func
        self._schemas[schema.name] = schema

    def get_schema(self, name: str) -> ToolSchema | None:
        return self._schemas.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    async def dispatch(self, name: str, **kwargs: Any) -> ToolResult:
        """Dispatch a tool call by name with given arguments."""
        if name not in self._tools:
            return ToolResult(
                tool_name=name,
                success=False,
                data=None,
                error=f"Tool '{name}' not registered",
            )
        start = time.time()
        try:
            result = await self._tools[name](**kwargs)
            result.duration_ms = (time.time() - start) * 1000
            return result
        except Exception as e:
            return ToolResult(
                tool_name=name,
                success=False,
                data=None,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    @property
    def llm_client(self) -> AsyncOpenAI:
        if self._llm_client is None:
            self._llm_client = AsyncOpenAI(
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.environ.get("OPENAI_API_KEY", ""),
            )
        return self._llm_client

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "ResearchAgent/1.0"},
            )
        return self._http_client

    async def close(self) -> None:
        """Clean up resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
        if self._llm_client is not None:
            await self._llm_client.close()


def build_default_registry() -> ToolRegistry:
    """Build a registry with all default tools pre-registered."""
    registry = ToolRegistry()

    # --- search_web tool ---
    search_schema = ToolSchema(
        name="search_web",
        description="Search the web for information. Returns a list of results with title, url, and snippet.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "snippet": {"type": "string"},
                },
            },
        },
    )

    async def search_web(query: str) -> ToolResult:
        """Search the web using LLM-simulated search (pluggable backend)."""
        model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        client = registry.llm_client

        prompt = (
            f"You are a web search engine. Given the query below, produce 5-8 realistic search results.\n"
            f"Each result must have: title, url, snippet.\n"
            f"Return valid JSON array only, no other text.\n\n"
            f"Query: {query}"
        )

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            content = response.choices[0].message.content or "[]"
            # Extract JSON from potential markdown code blocks
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if json_match:
                content = json_match.group(1).strip()
            results = json.loads(content)
            if not isinstance(results, list):
                results = []
            return ToolResult(tool_name="search_web", success=True, data=results)
        except Exception as e:
            return ToolResult(tool_name="search_web", success=False, data=[], error=str(e))

    registry.register(search_schema, search_web)

    # --- fetch_url tool ---
    fetch_schema = ToolSchema(
        name="fetch_url",
        description="Fetch content from a URL and extract text.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "status_code": {"type": "integer"},
            },
        },
    )

    async def fetch_url(url: str) -> ToolResult:
        """Fetch and extract text content from a URL."""
        try:
            resp = await registry.http_client.get(url)
            text = resp.text

            # Basic HTML to text extraction
            if "<html" in text.lower() or "<body" in text.lower():
                text = _html_to_text(text)

            # Truncate very long pages
            if len(text) > 50000:
                text = text[:50000] + "\n...[truncated]"

            return ToolResult(
                tool_name="fetch_url",
                success=True,
                data={"content": text, "status_code": resp.status_code},
            )
        except Exception as e:
            return ToolResult(
                tool_name="fetch_url",
                success=False,
                data={"content": "", "status_code": 0},
                error=str(e),
            )

    registry.register(fetch_schema, fetch_url)

    # --- llm_generate tool ---
    llm_schema = ToolSchema(
        name="llm_generate",
        description="Generate text using the LLM.",
        input_schema={
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                },
                "temperature": {"type": "number", "default": 0.4},
                "max_tokens": {"type": "integer", "default": 4000},
            },
            "required": ["messages"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "usage": {"type": "object"},
            },
        },
    )

    async def llm_generate(
        messages: list[dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 4000,
    ) -> ToolResult:
        """Generate text from the LLM."""
        model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        client = registry.llm_client
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            return ToolResult(
                tool_name="llm_generate",
                success=True,
                data={"content": content, "usage": usage},
            )
        except Exception as e:
            return ToolResult(
                tool_name="llm_generate",
                success=False,
                data={"content": "", "usage": {}},
                error=str(e),
            )

    registry.register(llm_schema, llm_generate)

    # --- llm_json tool (structured output) ---
    llm_json_schema = ToolSchema(
        name="llm_json",
        description="Generate structured JSON output from the LLM.",
        input_schema={
            "type": "object",
            "properties": {
                "messages": {"type": "array"},
                "temperature": {"type": "number", "default": 0.2},
                "max_tokens": {"type": "integer", "default": 4000},
            },
            "required": ["messages"],
        },
        output_schema={
            "type": "object",
            "properties": {"parsed": {"type": "object"}},
        },
    )

    async def llm_json(
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> ToolResult:
        """Generate JSON output from the LLM. Parses response as JSON."""
        model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        client = registry.llm_client
        try:
            # Append instruction to return JSON
            enhanced_messages = list(messages)
            if enhanced_messages:
                last = enhanced_messages[-1]
                enhanced_messages[-1] = {
                    "role": last["role"],
                    "content": last["content"] + "\n\nRespond with valid JSON only, no markdown or extra text.",
                }

            response = await client.chat.completions.create(
                model=model,
                messages=enhanced_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or "{}"
            # Extract JSON from potential code blocks
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if json_match:
                content = json_match.group(1).strip()
            parsed = json.loads(content)
            return ToolResult(tool_name="llm_json", success=True, data={"parsed": parsed})
        except json.JSONDecodeError as e:
            return ToolResult(
                tool_name="llm_json",
                success=False,
                data={"parsed": {}, "raw": content},
                error=f"JSON parse error: {e}",
            )
        except Exception as e:
            return ToolResult(
                tool_name="llm_json",
                success=False,
                data={"parsed": {}},
                error=str(e),
            )

    registry.register(llm_json_schema, llm_json)

    return registry


def _html_to_text(html: str) -> str:
    """Basic HTML to text extraction without external dependencies."""
    # Remove script and style elements
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def generate_uid(content: str, source_url: str) -> str:
    """Generate a deterministic unique ID for an evidence card."""
    raw = f"{source_url}:{content[:200]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]
