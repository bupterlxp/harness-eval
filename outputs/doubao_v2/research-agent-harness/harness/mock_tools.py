#!/usr/bin/env python3
"""
Mock implementation for search and LLM tools to complete the harness
"""

import os
import json
from typing import List, Dict, Any


def mock_llm_call(prompt: str, model: str = "gpt-3.5-turbo") -> Dict[str, Any]:
    """Mock LLM call for testing"""
    # Simple response generation
    return {
        "choices": [{
            "message": {
                "content": f"Mock response for prompt: {prompt[:50]}..."
            }
        }]
    }


def mock_web_search(query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    """Mock web search implementation"""
    results = []
    for i in range(num_results):
        results.append({
            "id": i + 1,
            "url": f"https://example.com/search/result/{i+1}",
            "title": f"Result {i+1} for query: {query}",
            "snippet": f"This is a mock result for query: {query}"
        })
    return results


def mock_content_extraction(url: str) -> str:
    """Mock content extraction"""
    return f"""Full content from {url}

This is a comprehensive article about the topic being researched.

Key points:
- First important fact about the research topic
- Second significant finding
- Third critical piece of information

Conclusion: The research topic has important implications in many areas.
"""


def mock_source_evaluation(source: Dict[str, Any]) -> Dict[str, Any]:
    """Mock source evaluation"""
    url = source.get("url", "")
    title = source.get("title", "")

    # Simple credibility scoring
    if any(domain in url for domain in [".edu", ".gov", ".org"]):
        credibility = "high"
    elif any(domain in url for domain in [".com"]):
        if "blog" in url or "medium.com" in url:
            credibility = "medium"
        else:
            credibility = "medium"
    else:
        credibility = "low"

    return {
        "credibility": credibility,
        "score": {"high": 3, "medium": 2, "low": 1}[credibility]
    }


if __name__ == "__main__":
    # Test the mock functions
    print("Testing mock tools...")

    # Test search
    results = mock_web_search("test query", 3)
    print(f"Search returned {len(results)} results")

    # Test evaluation
    eval_result = mock_source_evaluation({"url": "https://example.com/test"})
    print(f"Source evaluation: {eval_result['credibility']}")

    print("Mock tools test complete!")