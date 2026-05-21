"""Tests for the Tools module."""

import pytest

from harness.tools import (
    ToolRegistry,
    Tool,
    WebSearchTool,
    AcademicSearchTool,
    ContentExtractorTool,
    SourceEvaluatorTool,
    LLMTool,
    RetryStrategy,
    SearchResult,
    ExtractedContent,
    SourceEvaluation,
    CredibilityLevel,
)


class TestRetryStrategy:
    def test_default_values(self):
        strategy = RetryStrategy()
        assert strategy.max_retries == 3
        assert strategy.base_delay == 1.0

    def test_get_delay_exponential(self):
        strategy = RetryStrategy(base_delay=1.0, exponential_base=2.0)
        assert strategy.get_delay(0) == 1.0
        assert strategy.get_delay(1) == 2.0
        assert strategy.get_delay(2) == 4.0

    def test_get_delay_max_cap(self):
        strategy = RetryStrategy(base_delay=1.0, max_delay=5.0, exponential_base=2.0)
        assert strategy.get_delay(10) == 5.0


class TestSearchResult:
    def test_search_result_creation(self):
        result = SearchResult(
            url="https://example.com",
            title="Example",
            snippet="A test snippet",
            source_type="web",
        )
        assert result.url == "https://example.com"
        assert result.source_type == "web"

    def test_search_result_to_dict(self):
        result = SearchResult(
            url="https://example.com",
            title="Example",
            snippet="A test snippet",
        )
        d = result.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Example"


class TestExtractedContent:
    def test_extracted_content_creation(self):
        content = ExtractedContent(
            url="https://example.com",
            title="Example",
            content="Test content",
            facts=["Fact 1", "Fact 2"],
        )
        assert content.url == "https://example.com"
        assert len(content.facts) == 2


class TestSourceEvaluation:
    def test_source_evaluation_creation(self):
        evaluation = SourceEvaluation(
            url="https://arxiv.org/paper",
            credibility=CredibilityLevel.HIGH,
            source_type="academic_paper",
            timeliness_score=0.9,
            relevance_score=0.85,
            reasoning="High credibility domain",
        )
        assert evaluation.credibility == CredibilityLevel.HIGH
        assert evaluation.source_type == "academic_paper"


class TestSourceEvaluatorTool:
    def test_credibility_assessment_high(self):
        tool = SourceEvaluatorTool()
        cred = tool._assess_credibility("https://arxiv.org/abs/12345")
        assert cred == CredibilityLevel.HIGH

    def test_credibility_assessment_medium(self):
        tool = SourceEvaluatorTool()
        cred = tool._assess_credibility("https://en.wikipedia.org/wiki/Test")
        assert cred == CredibilityLevel.MEDIUM

    def test_credibility_assessment_low(self):
        tool = SourceEvaluatorTool()
        cred = tool._assess_credibility("https://twitter.com/user/status")
        assert cred == CredibilityLevel.LOW

    def test_source_type_determination(self):
        tool = SourceEvaluatorTool()
        assert tool._determine_source_type("https://arxiv.org/paper") == "academic_paper"
        assert tool._determine_source_type("https://docs.python.org/3/") == "official_documentation"
        assert tool._determine_source_type("https://random-site.com") == "web_page"

    def test_timeliness_assessment(self):
        tool = SourceEvaluatorTool()
        recent_content = "Published in 2024, this study shows..."
        score = tool._assess_timeliness(recent_content)
        assert score >= 0.5

    def test_relevance_assessment(self):
        tool = SourceEvaluatorTool()
        content = "machine learning artificial intelligence neural networks"
        query = "machine learning"
        score = tool._assess_relevance(content, query)
        assert score > 0


class TestContentExtractorTool:
    def test_extract_title(self):
        tool = ContentExtractorTool()
        html = "<html><head><title>Test Title</title></head><body></body></html>"
        title = tool._extract_title(html)
        assert title == "Test Title"

    def test_extract_text_content(self):
        tool = ContentExtractorTool()
        html = "<html><body><p>Hello World</p><script>alert('test')</script></body></html>"
        text = tool._extract_text_content(html)
        assert "Hello World" in text
        assert "alert" not in text

    def test_extract_potential_facts(self):
        tool = ContentExtractorTool()
        content = "According to research, 50 percent of users prefer this approach. The study found significant results."
        facts = tool._extract_potential_facts(content)
        assert len(facts) > 0


class TestToolRegistry:
    def test_default_tools_registered(self):
        registry = ToolRegistry()
        tools = registry.list_tools()
        assert "web_search" in tools
        assert "academic_search" in tools
        assert "content_extractor" in tools
        assert "source_evaluator" in tools
        assert "llm" in tools

    def test_get_tool(self):
        registry = ToolRegistry()
        tool = registry.get("web_search")
        assert tool is not None
        assert isinstance(tool, WebSearchTool)

    def test_get_nonexistent_tool(self):
        registry = ToolRegistry()
        tool = registry.get("nonexistent")
        assert tool is None

    def test_register_custom_tool(self):
        class CustomTool(Tool):
            async def execute(self, **kwargs):
                return "custom result"

        registry = ToolRegistry()
        custom = CustomTool("custom", "A custom tool")
        registry.register(custom)

        assert "custom" in registry.list_tools()
        assert registry.get("custom") is custom

    def test_property_accessors(self):
        registry = ToolRegistry()
        assert isinstance(registry.web_search, WebSearchTool)
        assert isinstance(registry.academic_search, AcademicSearchTool)
        assert isinstance(registry.content_extractor, ContentExtractorTool)
        assert isinstance(registry.source_evaluator, SourceEvaluatorTool)
        assert isinstance(registry.llm, LLMTool)


class TestWebSearchTool:
    def test_tool_initialization(self):
        tool = WebSearchTool(api_key="test_key")
        assert tool.name == "web_search"
        assert tool.api_key == "test_key"


class TestAcademicSearchTool:
    def test_tool_initialization(self):
        tool = AcademicSearchTool(api_key="test_key")
        assert tool.name == "academic_search"
        assert tool.api_key == "test_key"


class TestLLMTool:
    def test_tool_initialization(self):
        tool = LLMTool(api_key="test_key", model="gpt-4")
        assert tool.name == "llm"
        assert tool.api_key == "test_key"
        assert tool.model == "gpt-4"
