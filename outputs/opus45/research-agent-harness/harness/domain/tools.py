"""Domain Tools - Search, extraction, validation, and drafting tools.

Tools:
- web_search: Search engine interface
- fetch_page: Web page content extraction
- extract_facts: Fact extraction from content
- evaluate_source: Source reliability evaluation
- format_citation: Citation formatting
- cross_validate: Claim cross-validation
- draft_section: Section drafting
- decompose_questions: Question decomposition
- analyze_gap: Gap analysis
- generate_gap_queries: Generate queries for gap filling
"""

import os
import re
import json
import asyncio
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from harness.schemas import (
    ResearchQuery,
    Source,
    Evidence,
    SourceReliability,
    Citation,
)
from harness.tools import tool, ToolSafety, RateLimitConfig


def get_llm_client() -> OpenAI:
    """Get OpenAI-compatible LLM client."""
    return OpenAI(
        base_url=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:3457/v1"),
        api_key=os.environ.get("OPENAI_API_KEY", "dummy-key"),
    )


def get_model_name() -> str:
    """Get model name from environment."""
    return os.environ.get("MODEL_NAME", "gpt-4")


class DomainTools:
    """Domain-specific tools for research agent."""

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http_client = http_client
        self._llm_client: Optional[OpenAI] = None

    @property
    def llm_client(self) -> OpenAI:
        """Lazy-load LLM client."""
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    async def get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    @tool(
        name="web_search",
        description="Search the web for information",
        safety=ToolSafety.SAFE,
        rate_limit=RateLimitConfig(max_calls_per_minute=30),
        parameters={"query": "Search query string", "max_results": "Maximum results to return"},
    )
    async def web_search(self, query: str, max_results: int = 10) -> list[dict]:
        """Execute a web search query.

        In production, this would call a real search API.
        For testing/demo, uses LLM to simulate search results.
        """
        from harness.domain.prompts import PromptTemplates

        prompt = PromptTemplates.web_search_simulation(query, max_results)

        try:
            response = self.llm_client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            content = response.choices[0].message.content
            json_match = re.search(r'\[[\s\S]*\]', content)
            if json_match:
                results = json.loads(json_match.group())
                return results[:max_results]

        except Exception as e:
            return [{
                "url": f"https://example.com/search-error",
                "title": f"Search Error: {query}",
                "content": f"Error executing search: {str(e)}",
            }]

        return []

    @tool(
        name="fetch_page",
        description="Fetch and extract content from a web page",
        safety=ToolSafety.SAFE,
        rate_limit=RateLimitConfig(max_calls_per_minute=60),
        parameters={"url": "URL to fetch"},
    )
    async def fetch_page(self, url: str) -> dict:
        """Fetch content from a URL."""
        try:
            client = await self.get_http_client()
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            content = response.text

            title_match = re.search(r'<title[^>]*>([^<]+)</title>', content, re.I)
            title = title_match.group(1) if title_match else url

            text_content = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', content)
            text_content = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', text_content)
            text_content = re.sub(r'<[^>]+>', ' ', text_content)
            text_content = re.sub(r'\s+', ' ', text_content).strip()

            return {
                "url": url,
                "title": title,
                "content": text_content[:10000],
                "fetched_at": datetime.now().isoformat(),
            }

        except Exception as e:
            return {
                "url": url,
                "title": "Fetch Error",
                "content": f"Error fetching URL: {str(e)}",
                "error": str(e),
            }

    @tool(
        name="extract_facts",
        description="Extract facts from content relevant to research questions",
        safety=ToolSafety.SAFE,
        parameters={
            "content": "Content to extract from",
            "questions": "Research questions",
            "sections": "Target sections",
        },
    )
    async def extract_facts(
        self,
        content: str,
        questions: list[str],
        sections: list[str],
    ) -> list[dict]:
        """Extract facts from content using LLM."""
        from harness.domain.prompts import PromptTemplates

        prompt = PromptTemplates.extract_facts(content, questions, sections)

        try:
            response = self.llm_client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )

            result_text = response.choices[0].message.content
            json_match = re.search(r'\[[\s\S]*\]', result_text)
            if json_match:
                facts = json.loads(json_match.group())
                return facts

        except Exception as e:
            return [{
                "content": f"Error extracting facts: {str(e)}",
                "source_paragraph": "",
                "target_section": sections[0] if sections else "",
                "related_questions": [],
                "confidence": 0.5,
            }]

        return []

    @tool(
        name="evaluate_source",
        description="Evaluate source reliability, relevance, and timeliness",
        safety=ToolSafety.SAFE,
        parameters={"url": "Source URL", "content": "Source content"},
    )
    async def evaluate_source(self, url: str, content: str) -> dict:
        """Evaluate a source's quality."""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        reliability = SourceReliability.UNKNOWN
        if 'arxiv.org' in domain:
            reliability = SourceReliability.ACADEMIC_PAPER
        elif any(d in domain for d in ['github.com', 'docs.', 'developer.']):
            reliability = SourceReliability.OFFICIAL_DOCS
        elif any(d in domain for d in ['medium.com', 'blog.', 'towardsdatascience']):
            reliability = SourceReliability.TECH_BLOG
        elif any(d in domain for d in ['news.', 'techcrunch', 'wired', 'theverge']):
            reliability = SourceReliability.NEWS
        elif any(d in domain for d in ['stackoverflow', 'reddit', 'forum']):
            reliability = SourceReliability.FORUM

        year_matches = re.findall(r'20[12][0-9]', content)
        current_year = datetime.now().year
        timeliness_score = 0.5

        if year_matches:
            years = [int(y) for y in year_matches]
            max_year = max(years)
            timeliness_score = max(0, 1 - (current_year - max_year) * 0.2)

        code_patterns = ['def ', 'class ', 'function ', 'import ', 'from ', '```']
        has_code = any(p in content for p in code_patterns)

        data_patterns = ['%', 'benchmark', 'evaluation', 'performance', 'accuracy']
        has_data = any(p.lower() in content.lower() for p in data_patterns)

        relevance_score = 0.5
        if has_code:
            relevance_score += 0.2
        if has_data:
            relevance_score += 0.2
        relevance_score = min(1.0, relevance_score)

        return {
            "reliability": reliability,
            "relevance_score": relevance_score,
            "timeliness_score": timeliness_score,
            "domain": domain,
            "has_code_examples": has_code,
            "has_data": has_data,
        }

    @tool(
        name="format_citation",
        description="Format a citation according to specification",
        safety=ToolSafety.SAFE,
        parameters={"source_info": "Source information dictionary"},
    )
    async def format_citation(self, source_info: dict) -> str:
        """Format citation: 作者(年份). 标题. 来源. URL"""
        authors = source_info.get("authors", "Unknown")
        year = source_info.get("year", "n.d.")
        title = source_info.get("title", "Untitled")
        venue = source_info.get("venue", "Web")
        url = source_info.get("url", "")

        return f"{authors} ({year}). {title}. {venue}. {url}"

    @tool(
        name="cross_validate",
        description="Cross-validate a claim against multiple sources",
        safety=ToolSafety.SAFE,
        parameters={"claim": "Claim to validate", "sources": "Sources to check against"},
    )
    async def cross_validate(
        self,
        claim: str,
        sources: list[Any],
    ) -> dict:
        """Cross-validate a claim using LLM."""
        from harness.domain.prompts import PromptTemplates

        source_contents = []
        for s in sources:
            if s and hasattr(s, 'content'):
                source_contents.append({
                    "url": s.url if hasattr(s, 'url') else "",
                    "content": s.content[:1000] if hasattr(s, 'content') else "",
                })

        if not source_contents:
            return {
                "is_valid": True,
                "supporting_sources": [],
                "conflicting_sources": [],
                "confidence": 0.5,
            }

        prompt = PromptTemplates.cross_validate(claim, source_contents)

        try:
            response = self.llm_client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )

            result_text = response.choices[0].message.content
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                return json.loads(json_match.group())

        except Exception:
            pass

        return {
            "is_valid": True,
            "supporting_sources": [],
            "conflicting_sources": [],
            "confidence": 0.5,
        }

    @tool(
        name="draft_section",
        description="Draft a section of the research report",
        safety=ToolSafety.SAFE,
        parameters={
            "section": "Section name",
            "evidence": "Evidence items",
            "sources": "Source objects",
            "outline": "Expected outline",
            "citation_mapper": "Citation mapper instance",
        },
    )
    async def draft_section(
        self,
        section: str,
        evidence: list[Any],
        sources: list[Any],
        outline: dict,
        citation_mapper: Any,
    ) -> dict:
        """Draft a section using LLM."""
        from harness.domain.prompts import PromptTemplates

        evidence_texts = []
        source_map = {s.id: s for s in sources if s}

        for ev in evidence:
            source = source_map.get(ev.source_id)
            if source:
                citation = citation_mapper.get_citation_for_source(source.id)
                if not citation:
                    year_match = re.search(r'20[12][0-9]', source.content or "")
                    year = year_match.group() if year_match else "n.d."

                    author_match = re.search(r'([A-Z][a-z]+(?:\s+et\s+al\.)?)', source.title or "")
                    authors = author_match.group() if author_match else "Unknown"

                    citation = citation_mapper.add_citation(
                        source=source,
                        authors=authors,
                        year=year,
                        title=source.title or "Untitled",
                        venue="arXiv" if "arxiv" in (source.url or "").lower() else "Web",
                    )

                evidence_texts.append({
                    "content": ev.content,
                    "citation_number": citation.citation_number,
                    "source_title": source.title,
                })

        section_expectations = outline.get(section, {})

        prompt = PromptTemplates.draft_section(
            section_name=section,
            evidence=evidence_texts,
            expectations=section_expectations,
        )

        try:
            response = self.llm_client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
            )

            content = response.choices[0].message.content
            citation_ids = [e.get("citation_number") for e in evidence_texts]

            return {
                "content": content,
                "citation_ids": citation_ids,
            }

        except Exception as e:
            return {
                "content": f"Error drafting section: {str(e)}",
                "citation_ids": [],
            }

    @tool(
        name="decompose_questions",
        description="Decompose research questions into search queries",
        safety=ToolSafety.SAFE,
        parameters={
            "topic": "Research topic",
            "questions": "Research questions",
            "sections": "Target sections",
        },
    )
    async def decompose_questions(
        self,
        topic: str,
        questions: list[str],
        sections: list[str],
    ) -> list[ResearchQuery]:
        """Decompose questions into queries using LLM."""
        from harness.domain.prompts import PromptTemplates

        prompt = PromptTemplates.decompose_questions(topic, questions, sections)

        try:
            response = self.llm_client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            result_text = response.choices[0].message.content
            json_match = re.search(r'\[[\s\S]*\]', result_text)

            if json_match:
                query_dicts = json.loads(json_match.group())
                queries = []
                for i, qd in enumerate(query_dicts):
                    query = ResearchQuery(
                        id=f"q_{i}",
                        original_question_index=qd.get("question_index", 0),
                        query_text=qd.get("query_text", ""),
                        target_section=qd.get("target_section", sections[0] if sections else ""),
                    )
                    queries.append(query)
                return queries

        except Exception as e:
            queries = []
            for i, q in enumerate(questions):
                query = ResearchQuery(
                    id=f"q_{i}",
                    original_question_index=i,
                    query_text=q,
                    target_section=sections[min(i, len(sections)-1)] if sections else "",
                )
                queries.append(query)
            return queries

        return []

    @tool(
        name="analyze_gap",
        description="Analyze information gaps for a section",
        safety=ToolSafety.SAFE,
        parameters={
            "section": "Section name",
            "evidence": "Current evidence",
            "questions": "Research questions",
        },
    )
    async def analyze_gap(
        self,
        section: str,
        evidence: list[Any],
        questions: list[str],
    ) -> dict:
        """Analyze gaps in evidence coverage."""
        from harness.domain.prompts import PromptTemplates

        evidence_summaries = [
            {"content": e.content[:200] if hasattr(e, 'content') else str(e)[:200]}
            for e in evidence
        ]

        prompt = PromptTemplates.analyze_gap(section, evidence_summaries, questions)

        try:
            response = self.llm_client.chat.completions.create(
                model=get_model_name(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            result_text = response.choices[0].message.content
            json_match = re.search(r'\{[\s\S]*\}', result_text)

            if json_match:
                return json.loads(json_match.group())

        except Exception:
            pass

        return {
            "missing_topics": [],
            "suggested_queries": [],
        }

    @tool(
        name="generate_gap_queries",
        description="Generate queries to fill information gaps",
        safety=ToolSafety.SAFE,
        parameters={
            "section": "Section name",
            "existing_evidence": "Existing evidence",
            "questions": "Research questions",
        },
    )
    async def generate_gap_queries(
        self,
        section: str,
        existing_evidence: list[Any],
        questions: list[str],
    ) -> list[dict]:
        """Generate queries to fill gaps."""
        gap_analysis = await self.analyze_gap(section, existing_evidence, questions)

        queries = []
        for query_text in gap_analysis.get("suggested_queries", []):
            queries.append({
                "query_text": query_text,
                "target_section": section,
            })

        return queries


def create_domain_tools() -> DomainTools:
    """Factory function to create domain tools instance."""
    return DomainTools()
