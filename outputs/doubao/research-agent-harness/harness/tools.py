import os
import time
import json
from typing import List, Dict, Optional, Any, Tuple
import httpx
from datetime import datetime
from .schemas import Source, SourceReliability


class ToolRegistry:
    """Registry for all tools used in the research process"""

    def __init__(self):
        self.tools: Dict[str, Any] = {
            "web_search": WebSearchTool(),
            "fetch_page": PageFetcherTool(),
            "evaluate_source": SourceEvaluatorTool(),
            "format_citation": CitationFormatterTool()
        }

    def get_tool(self, tool_name: str) -> Optional[Any]:
        """Get a tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """List all available tools"""
        return list(self.tools.keys())


class WebSearchTool:
    """Tool for web search with rate limiting"""

    def __init__(self, max_results: int = 10, rate_limit_delay: float = 1.0):
        self.max_results = max_results
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0

    async def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """Perform web search"""
        # Respect rate limits
        current_time = time.time()
        if current_time - self.last_request_time < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - (current_time - self.last_request_time))
        self.last_request_time = time.time()

        # This would normally call a real search API
        # For now, return mock results
        results = [
            {
                "title": f"Result for {query} - {i}",
                "url": f"https://example.com/search/{query}/{i}",
                "snippet": f"This is a snippet about {query} from result {i}",
                "source": "example"
            }
            for i in range(min(max_results or self.max_results, 10))
        ]

        return results


class PageFetcherTool:
    """Tool for fetching web page content"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> Optional[str]:
        """Fetch content from a URL"""
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    async def batch_fetch(self, urls: List[str]) -> Dict[str, Optional[str]]:
        """Fetch multiple URLs in parallel"""
        results = {}
        for url in urls:
            results[url] = await self.fetch(url)
        return results


class SourceEvaluatorTool:
    """Tool for evaluating source reliability and relevance"""

    RELIABLE_DOMAINS = {
        "arxiv.org": SourceReliability.ACADEMIC,
        "academic.oup.com": SourceReliability.ACADEMIC,
        "ieeexplore.ieee.org": SourceReliability.ACADEMIC,
        "dl.acm.org": SourceReliability.ACADEMIC,
        "scholar.google.com": SourceReliability.ACADEMIC,
        "github.com": SourceReliability.TECHNICAL_BLOG,
        "developer." : SourceReliability.OFFICIAL_DOC,
        "blog." : SourceReliability.TECHNICAL_BLOG,
        "medium.com": SourceReliability.TECHNICAL_BLOG,
    }

    def evaluate(self, source: Source, content: Optional[str] = None) -> Tuple[SourceReliability, float]:
        """Evaluate source reliability and relevance"""
        # Determine reliability based on domain
        reliability = self._get_domain_reliability(source.url)

        # Calculate relevance score if content is provided
        relevance_score = 0.0
        if content:
            relevance_score = self._calculate_relevance(content, source.title)

        source.reliability = reliability
        source.relevance_score = relevance_score

        return reliability, relevance_score

    def _get_domain_reliability(self, url: str) -> SourceReliability:
        """Get reliability rating based on domain"""
        for domain, rating in self.RELIABLE_DOMAINS.items():
            if domain in url.lower():
                return rating

        if "arxiv.org/abs/" in url.lower():
            return SourceReliability.ACADEMIC

        return SourceReliability.UNKNOWN

    def _calculate_relevance(self, content: str, title: str) -> float:
        """Calculate relevance score based on content"""
        # Simple relevance calculation - count keyword matches
        # In real implementation, use embeddings or NLP
        words = content.lower().split()
        title_words = title.lower().split()

        matches = sum(1 for word in title_words if word in words)
        return min(matches / len(title_words) if title_words else 0, 1.0)


class CitationFormatterTool:
    """Tool for formatting citations"""

    DEFAULT_FORMAT = "{authors}({year}). {title}. {url}"

    def format(self, source: Source, format_string: Optional[str] = None) -> str:
        """Format a source according to citation format"""
        format_str = format_string or self.DEFAULT_FORMAT

        authors = " ".join(source.authors) if source.authors else "Unknown"
        year = str(source.year) if source.year else "n.d."
        title = source.title or "Untitled"

        return format_str.format(
            authors=authors,
            year=year,
            title=title,
            url=source.url
        )


class LLMClient:
    """Client for LLM interactions using OpenAI-compatible API"""

    def __init__(self):
        import openai
        self.client = openai.AsyncOpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "dummy_key")
        )
        self.model = os.environ.get("MODEL_NAME", "claude-3-5-sonnet-20240620")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                      temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """Generate text using LLM"""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"LLM generation error: {e}")
            return f"Error generating response: {str(e)}"

    async def extract_facts(self, content: str, questions: List[str]) -> List[Dict[str, Any]]:
        """Extract facts from content based on questions"""
        prompt = f"""Please extract factual information from the following content that answers these questions:

Questions:
{chr(10).join(f"- {q}" for q in questions)}

Content:
{content}

Please return your answer as a JSON array of objects with keys 'question', 'fact', and 'source_url'.
Only include facts that are directly supported by the content.
"""

        response = await self.generate(prompt, temperature=0.1)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback parsing if JSON is malformed
            return [{"error": "Failed to parse LLM response", "raw_response": response}]