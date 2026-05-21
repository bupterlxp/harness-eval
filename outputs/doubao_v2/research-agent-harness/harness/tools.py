"""
Core components of the research agent harness
"""

import os
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum


class SourceType(Enum):
    """Type of source for credibility scoring"""
    ACADEMIC = 3
    OFFICIAL = 2
    BLOG = 1
    SOCIAL = 0


@dataclass
class Source:
    """Represents a source with metadata"""
    id: int
    url: str
    title: str
    credibility: str  # "high" | "medium" | "low"
    source_type: SourceType
    retrieved_at: float
    content: Optional[str] = None
    facts: List[str] = None

    def __post_init__(self):
        if self.facts is None:
            self.facts = []


@dataclass
class Fact:
    """Represents a factual statement with attribution"""
    content: str
    source_ids: List[int]
    confidence: float = 1.0


@dataclass
class Citation:
    """Represents a citation in the report"""
    source_id: int
    page: Optional[int] = None
    quote: Optional[str] = None


class ToolRegistry:
    """Registry for research tools"""

    def __init__(self):
        self.tools = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Register default research tools"""
        # TODO: Implement actual search tools
        self.tools["search_web"] = self._mock_web_search
        self.tools["extract_content"] = self._mock_content_extraction
        self.tools["evaluate_source"] = self._mock_source_evaluation

    def register_tool(self, name: str, func):
        """Register a new tool"""
        self.tools[name] = func

    def get_tool(self, name: str):
        """Get a tool by name"""
        return self.tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tools"""
        return list(self.tools.keys())

    def _mock_web_search(self, query: str, num_results: int = 10) -> List[Dict[str, Any]]:
        """Mock web search tool"""
        time.sleep(0.5)
        return [
            {
                "id": i + 1,
                "url": f"https://example.com/search/result/{i+1}",
                "title": f"Result {i+1} for query: {query}",
                "snippet": f"This is a mock result for query: {query}"
            } for i in range(num_results)
        ]

    def _mock_content_extraction(self, url: str) -> str:
        """Mock content extraction tool"""
        time.sleep(0.3)
        return f"Full content from {url}\n\nThis is mock extracted content for demonstration purposes.\n\nIt contains key information relevant to the research query."

    def _mock_source_evaluation(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Mock source evaluation tool"""
        time.sleep(0.2)
        url = source.get("url", "")

        # Simple credibility scoring based on URL patterns
        if any(domain in url for domain in [".edu", ".gov", ".org"]):
            credibility = "high"
            source_type = SourceType.ACADEMIC
        elif any(domain in url for domain in [".com", ".net"]):
            if "blog" in url or "medium.com" in url:
                credibility = "medium"
                source_type = SourceType.BLOG
            else:
                credibility = "medium"
                source_type = SourceType.OFFICIAL
        else:
            credibility = "low"
            source_type = SourceType.SOCIAL

        return {
            "credibility": credibility,
            "source_type": source_type.value,
            "score": {
                "high": 3,
                "medium": 2,
                "low": 1
            }[credibility]
        }