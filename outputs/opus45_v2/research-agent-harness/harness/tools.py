"""Tool Registry (T) - Research tools with retry strategies for search, extraction, and evaluation."""

from __future__ import annotations
import asyncio
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from enum import Enum

import httpx


class CredibilityLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SearchResult:
    """A search result from any search tool."""
    url: str
    title: str
    snippet: str
    source_type: str = "web"
    relevance_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source_type": self.source_type,
            "relevance_score": self.relevance_score,
        }


@dataclass
class ExtractedContent:
    """Content extracted from a source."""
    url: str
    title: str
    content: str
    facts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "facts": self.facts,
            "metadata": self.metadata,
        }


@dataclass
class SourceEvaluation:
    """Evaluation result for a source."""
    url: str
    credibility: CredibilityLevel
    source_type: str
    timeliness_score: float
    relevance_score: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "credibility": self.credibility.value,
            "source_type": self.source_type,
            "timeliness_score": self.timeliness_score,
            "relevance_score": self.relevance_score,
            "reasoning": self.reasoning,
        }


class RetryStrategy:
    """Configurable retry strategy for tools."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def get_delay(self, attempt: int) -> float:
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)

    async def execute_with_retry(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    await asyncio.sleep(delay)
        raise last_error  # type: ignore


class Tool(ABC):
    """Base class for research tools."""

    def __init__(self, name: str, description: str, retry_strategy: RetryStrategy | None = None):
        self.name = name
        self.description = description
        self.retry_strategy = retry_strategy or RetryStrategy()

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given parameters."""
        pass

    async def execute_with_retry(self, **kwargs: Any) -> Any:
        """Execute with configured retry strategy."""
        return await self.retry_strategy.execute_with_retry(self.execute, **kwargs)


class WebSearchTool(Tool):
    """Web search tool using configurable search API."""

    def __init__(
        self,
        api_key: str | None = None,
        search_endpoint: str | None = None,
        retry_strategy: RetryStrategy | None = None,
    ):
        super().__init__(
            name="web_search",
            description="Search the web for information",
            retry_strategy=retry_strategy,
        )
        self.api_key = api_key or os.environ.get("SEARCH_API_KEY", "")
        self.search_endpoint = search_endpoint or os.environ.get(
            "SEARCH_ENDPOINT", "https://api.search.example.com/search"
        )

    async def execute(self, query: str, num_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        """Execute web search and return results."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    self.search_endpoint,
                    params={"q": query, "num": num_results},
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("results", data.get("items", [])):
                    results.append(SearchResult(
                        url=item.get("url", item.get("link", "")),
                        title=item.get("title", ""),
                        snippet=item.get("snippet", item.get("description", "")),
                        source_type="web",
                    ))
                return results
            except httpx.HTTPError:
                return []


class AcademicSearchTool(Tool):
    """Academic/scholarly search tool."""

    def __init__(
        self,
        api_key: str | None = None,
        search_endpoint: str | None = None,
        retry_strategy: RetryStrategy | None = None,
    ):
        super().__init__(
            name="academic_search",
            description="Search academic and scholarly sources",
            retry_strategy=retry_strategy,
        )
        self.api_key = api_key or os.environ.get("ACADEMIC_API_KEY", "")
        self.search_endpoint = search_endpoint or os.environ.get(
            "ACADEMIC_ENDPOINT", "https://api.semanticscholar.org/graph/v1/paper/search"
        )

    async def execute(self, query: str, num_results: int = 10, **kwargs: Any) -> list[SearchResult]:
        """Execute academic search and return results."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(
                    self.search_endpoint,
                    params={
                        "query": query,
                        "limit": num_results,
                        "fields": "title,url,abstract",
                    },
                    headers={"x-api-key": self.api_key} if self.api_key else {},
                )
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("data", []):
                    url = item.get("url", "")
                    if not url and item.get("paperId"):
                        url = f"https://www.semanticscholar.org/paper/{item['paperId']}"

                    results.append(SearchResult(
                        url=url,
                        title=item.get("title", ""),
                        snippet=item.get("abstract", "")[:500] if item.get("abstract") else "",
                        source_type="academic",
                        relevance_score=1.2,
                    ))
                return results
            except httpx.HTTPError:
                return []


class ContentExtractorTool(Tool):
    """Tool for extracting content from web pages."""

    def __init__(self, retry_strategy: RetryStrategy | None = None):
        super().__init__(
            name="content_extractor",
            description="Extract content and facts from web pages",
            retry_strategy=retry_strategy,
        )

    async def execute(self, url: str, **kwargs: Any) -> ExtractedContent:
        """Fetch and extract content from a URL."""
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(url, headers={
                    "User-Agent": "ResearchAgent/1.0 (Research Bot)"
                })
                response.raise_for_status()
                html = response.text

                title = self._extract_title(html)
                content = self._extract_text_content(html)
                facts = self._extract_potential_facts(content)

                return ExtractedContent(
                    url=url,
                    title=title,
                    content=content,
                    facts=facts,
                    metadata={
                        "fetched_at": datetime.now().isoformat(),
                        "content_length": len(content),
                    },
                )
            except httpx.HTTPError as e:
                return ExtractedContent(
                    url=url,
                    title="",
                    content="",
                    facts=[],
                    metadata={"error": str(e)},
                )

    def _extract_title(self, html: str) -> str:
        match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _extract_text_content(self, html: str) -> str:
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()[:10000]

    def _extract_potential_facts(self, content: str) -> list[str]:
        sentences = re.split(r"[.!?]+", content)
        facts = []
        for s in sentences:
            s = s.strip()
            if len(s) > 30 and len(s) < 500:
                if re.search(r"\d", s) or any(
                    kw in s.lower()
                    for kw in ["according to", "study", "research", "found", "shows", "percent", "million", "billion"]
                ):
                    facts.append(s)
        return facts[:20]


class SourceEvaluatorTool(Tool):
    """Tool for evaluating source credibility."""

    HIGH_CREDIBILITY_DOMAINS = [
        ".edu", ".gov", "nature.com", "science.org", "arxiv.org",
        "semanticscholar.org", "pubmed.ncbi", "ieee.org", "acm.org",
        "springer.com", "wiley.com", "elsevier.com",
    ]

    MEDIUM_CREDIBILITY_DOMAINS = [
        "wikipedia.org", "britannica.com", "reuters.com", "apnews.com",
        "bbc.com", "nytimes.com", "washingtonpost.com", "theguardian.com",
        "docs.", "documentation.", "developer.",
    ]

    LOW_CREDIBILITY_PATTERNS = [
        "twitter.com", "facebook.com", "reddit.com", "quora.com",
        "medium.com", "blog.", "forum.",
    ]

    SOURCE_TYPE_MAP = {
        "arxiv.org": "academic_paper",
        "semanticscholar.org": "academic_paper",
        "pubmed.ncbi": "academic_paper",
        ".edu": "academic",
        ".gov": "government",
        "wikipedia.org": "encyclopedia",
        "docs.": "official_documentation",
        "documentation.": "official_documentation",
        "developer.": "official_documentation",
    }

    def __init__(self, retry_strategy: RetryStrategy | None = None):
        super().__init__(
            name="source_evaluator",
            description="Evaluate source credibility and type",
            retry_strategy=retry_strategy,
        )

    async def execute(
        self,
        url: str,
        content: str = "",
        query_context: str = "",
        **kwargs: Any,
    ) -> SourceEvaluation:
        """Evaluate a source's credibility."""
        url_lower = url.lower()

        credibility = self._assess_credibility(url_lower)
        source_type = self._determine_source_type(url_lower)
        timeliness = self._assess_timeliness(content)
        relevance = self._assess_relevance(content, query_context)

        reasoning = self._generate_reasoning(url, credibility, source_type, timeliness, relevance)

        return SourceEvaluation(
            url=url,
            credibility=credibility,
            source_type=source_type,
            timeliness_score=timeliness,
            relevance_score=relevance,
            reasoning=reasoning,
        )

    def _assess_credibility(self, url: str) -> CredibilityLevel:
        for domain in self.HIGH_CREDIBILITY_DOMAINS:
            if domain in url:
                return CredibilityLevel.HIGH

        for domain in self.MEDIUM_CREDIBILITY_DOMAINS:
            if domain in url:
                return CredibilityLevel.MEDIUM

        for pattern in self.LOW_CREDIBILITY_PATTERNS:
            if pattern in url:
                return CredibilityLevel.LOW

        return CredibilityLevel.MEDIUM

    def _determine_source_type(self, url: str) -> str:
        for pattern, stype in self.SOURCE_TYPE_MAP.items():
            if pattern in url:
                return stype
        return "web_page"

    def _assess_timeliness(self, content: str) -> float:
        current_year = datetime.now().year
        years_found = re.findall(r"\b(20\d{2})\b", content)

        if not years_found:
            return 0.5

        recent_years = [int(y) for y in years_found if int(y) >= current_year - 2]
        if recent_years:
            return min(1.0, 0.7 + 0.1 * len(recent_years))

        oldest = min(int(y) for y in years_found)
        age = current_year - oldest
        return max(0.2, 1.0 - age * 0.1)

    def _assess_relevance(self, content: str, query_context: str) -> float:
        if not query_context or not content:
            return 0.5

        query_terms = set(query_context.lower().split())
        content_lower = content.lower()

        matches = sum(1 for term in query_terms if term in content_lower and len(term) > 3)
        return min(1.0, matches / max(len(query_terms), 1))

    def _generate_reasoning(
        self,
        url: str,
        credibility: CredibilityLevel,
        source_type: str,
        timeliness: float,
        relevance: float,
    ) -> str:
        parts = [f"Source type: {source_type}"]

        if credibility == CredibilityLevel.HIGH:
            parts.append("High credibility domain")
        elif credibility == CredibilityLevel.LOW:
            parts.append("Lower credibility source (social/blog)")
        else:
            parts.append("Standard web source")

        if timeliness > 0.7:
            parts.append("Recent content")
        elif timeliness < 0.4:
            parts.append("Potentially outdated")

        if relevance > 0.6:
            parts.append("Highly relevant to query")

        return "; ".join(parts)


class LLMTool(Tool):
    """Tool for LLM-based operations using OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        retry_strategy: RetryStrategy | None = None,
    ):
        super().__init__(
            name="llm",
            description="LLM for analysis and generation",
            retry_strategy=retry_strategy or RetryStrategy(max_retries=2),
        )
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = model or os.environ.get("MODEL_NAME", "gpt-4o-mini")

    async def execute(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> str:
        """Execute LLM completion."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def analyze_facts(self, content: str, query: str) -> list[dict[str, Any]]:
        """Extract and analyze facts from content."""
        prompt = f"""Analyze the following content and extract key facts relevant to the query.

Query: {query}

Content:
{content[:5000]}

Return a JSON array of facts, each with:
- "content": the fact statement
- "confidence": confidence score 0-1
- "supports_query": boolean if directly relevant

Return ONLY valid JSON array, no other text."""

        try:
            result = await self.execute_with_retry(prompt=prompt, temperature=0.3)
            json_match = re.search(r"\[.*\]", result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, httpx.HTTPError):
            pass
        return []

    async def generate_section(
        self,
        section_name: str,
        facts: list[dict[str, Any]],
        citations: dict[int, str],
        max_words: int = 500,
    ) -> str:
        """Generate a report section with citations."""
        facts_text = "\n".join(
            f"- [{f.get('citation_num', '?')}] {f.get('content', '')}"
            for f in facts
        )

        prompt = f"""Write a research report section titled "{section_name}".

Use ONLY the following facts and include inline citations [N] for each fact used:

Facts with citations:
{facts_text}

Requirements:
- Write approximately {max_words} words
- Include inline citations [N] for every factual claim
- Be objective and present multiple perspectives if available
- Do not add information not in the facts

Write the section content only, no section title needed."""

        return await self.execute_with_retry(prompt=prompt, temperature=0.5, max_tokens=max_words * 2)

    async def decompose_query(self, query: str) -> list[dict[str, Any]]:
        """Decompose a complex query into sub-queries."""
        prompt = f"""Decompose this research question into atomic sub-queries that can be searched independently.

Research Question: {query}

Return a JSON array where each item has:
- "query": the sub-query string
- "dependency": index of query this depends on (-1 if independent)
- "priority": 1-5 (1 highest)

Return ONLY valid JSON array."""

        try:
            result = await self.execute_with_retry(prompt=prompt, temperature=0.3)
            json_match = re.search(r"\[.*\]", result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, httpx.HTTPError):
            pass
        return [{"query": query, "dependency": -1, "priority": 1}]


class ToolRegistry:
    """Registry for all research tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of research tools."""
        self.register(WebSearchTool())
        self.register(AcademicSearchTool())
        self.register(ContentExtractorTool())
        self.register(SourceEvaluatorTool())
        self.register(LLMTool())

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    async def execute(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a tool by name with retry."""
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        return await tool.execute_with_retry(**kwargs)

    @property
    def web_search(self) -> WebSearchTool:
        return self._tools["web_search"]  # type: ignore

    @property
    def academic_search(self) -> AcademicSearchTool:
        return self._tools["academic_search"]  # type: ignore

    @property
    def content_extractor(self) -> ContentExtractorTool:
        return self._tools["content_extractor"]  # type: ignore

    @property
    def source_evaluator(self) -> SourceEvaluatorTool:
        return self._tools["source_evaluator"]  # type: ignore

    @property
    def llm(self) -> LLMTool:
        return self._tools["llm"]  # type: ignore
