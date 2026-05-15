import pytest
import asyncio
from typing import List, Dict, Any
from harness.schemas import Source, Evidence, Citation, Section, ResearchQuery, ValidationResult, SourceReliability
from harness.state import EvidenceStore, CitationMapper, DraftManager
from harness.context import EvidenceContext, OutlineContext, QueryHistory, ResearchContext
from harness.tools import WebSearchTool, PageFetcherTool, SourceEvaluatorTool, CitationFormatterTool, LLMClient
from harness.lifecycle import LifecycleHooks
from harness.evaluation import EvaluationTrajectory


class TestSchemas:
    """测试数据结构模块"""

    def test_source_creation(self):
        """测试Source对象创建"""
        source = Source(
            url="https://example.com/paper",
            title="Test Paper",
            authors=["John Doe", "Jane Smith"],
            year=2024,
            reliability=SourceReliability.ACADEMIC
        )
        assert source.url == "https://example.com/paper"
        assert source.title == "Test Paper"
        assert source.authors == ["John Doe", "Jane Smith"]
        assert source.year == 2024
        assert source.reliability == SourceReliability.ACADEMIC

    def test_evidence_creation(self):
        """测试Evidence对象创建"""
        evidence = Evidence(
            source_url="https://example.com/paper",
            claim="This is a test fact",
            confidence=0.9
        )
        assert evidence.source_url == "https://example.com/paper"
        assert evidence.claim == "This is a test fact"
        assert evidence.confidence == 0.9


class TestStateModule:
    """测试状态管理模块"""

    def test_evidence_store(self):
        """测试证据存储"""
        store = EvidenceStore()
        evidence1 = Evidence(source_url="url1", claim="Fact 1")
        evidence2 = Evidence(source_url="url2", claim="Fact 2")

        store.add_evidence(evidence1)
        store.add_evidence(evidence2)

        assert len(store.get_all_evidence()) == 2
        assert len(store.get_evidence_for_source("url1")) == 1
        assert store.get_evidence_for_source("nonexistent") == []

    def test_citation_mapper(self):
        """测试引用映射器"""
        mapper = CitationMapper()
        source = Source(url="https://example.com/paper", title="Test Paper", year=2024)

        citation_key = mapper.add_source(source)
        assert citation_key == "[1]"
        assert mapper.get_citation_key("https://example.com/paper") == "[1]"

        citation = mapper.get_citation("[1]")
        assert citation is not None
        assert citation.key == "[1]"
        assert "Test Paper" in citation.formatted

    def test_draft_manager(self):
        """测试草稿管理器"""
        required_sections = ["摘要", "背景与动机", "结论"]
        manager = DraftManager(required_sections)

        # 测试初始状态
        for section in required_sections:
            assert manager.get_section(section) is not None
            assert manager.get_section(section).content == ""

        # 测试更新章节
        manager.update_section("摘要", "这是摘要", [])
        assert manager.get_section("摘要").content == "这是摘要"

        # 测试生成完整报告
        manager.update_section("背景与动机", "这是背景", [])
        manager.update_section("结论", "这是结论", [])
        report = manager.generate_full_report()
        assert "# 摘要" in report
        assert "# 背景与动机" in report
        assert "# 结论" in report


class TestContextModule:
    """测试上下文管理模块"""

    def test_query_history(self):
        """测试查询历史"""
        history = QueryHistory()
        history.add_query("test query")

        assert history.has_been_searched("TEST QUERY") is True
        assert history.has_been_searched("different query") is False

    def test_outline_context(self):
        """测试大纲上下文"""
        required_sections = ["摘要", "方法", "结果"]
        context = OutlineContext(required_sections)

        context.update_section("摘要", "摘要内容", [])
        assert context.is_section_complete("摘要") is True
        assert context.is_all_complete() is False

        context.update_section("方法", "方法内容", [])
        context.update_section("结果", "结果内容", [])
        assert context.is_all_complete() is True


class TestToolsModule:
    """测试工具模块"""

    def test_source_evaluator(self):
        """测试源评估器"""
        evaluator = SourceEvaluatorTool()
        source = Source(url="https://arxiv.org/abs/2401.01234", title="Test Paper")

        reliability, relevance = evaluator.evaluate(source, "some content")
        assert reliability == SourceReliability.ACADEMIC
        assert relevance >= 0.0

        # 测试非学术来源
        source2 = Source(url="https://medium.com/blog-post", title="Test Blog")
        reliability2, _ = evaluator.evaluate(source2, "")
        assert reliability2 == SourceReliability.TECHNICAL_BLOG

    def test_citation_formatter(self):
        """测试引用格式化器"""
        formatter = CitationFormatterTool()
        source = Source(
            url="https://example.com/paper",
            title="Test Paper",
            authors=["John Doe"],
            year=2024
        )

        formatted = formatter.format(source)
        assert "John Doe(2024)" in formatted
        assert "Test Paper" in formatted
        assert "https://example.com/paper" in formatted


class TestLifecycleModule:
    """测试生命周期钩子"""

    @pytest.mark.asyncio
    async def test_pre_search(self):
        """测试搜索前钩子"""
        lifecycle = LifecycleHooks()
        valid, message = await lifecycle.pre_search("test query", set())
        assert valid is True
        assert message == "Query is valid"

        # 测试重复查询
        valid, message = await lifecycle.pre_search("test query", {"test query"})
        assert valid is False

    def test_should_continue_searching(self):
        """测试是否继续搜索"""
        lifecycle = LifecycleHooks(max_hops=3)
        assert lifecycle.should_continue_searching(0) is True
        assert lifecycle.should_continue_searching(2) is True
        assert lifecycle.should_continue_searching(3) is False


class TestEvaluationTrajectory:
    """测试评估轨迹"""

    def test_trajectory_logging(self, tmp_path):
        """测试轨迹日志"""
        trajectory_file = tmp_path / "test_trajectory.jsonl"
        trajectory = EvaluationTrajectory(str(trajectory_file))

        trajectory.log_step("TEST_STEP", {"data": "test"})
        assert len(trajectory.trajectory) == 1
        assert trajectory.trajectory[0]["step"] == "TEST_STEP"
        assert trajectory.trajectory[0]["data"] == {"data": "test"}

        # 验证文件已创建
        assert trajectory_file.exists()


class TestExecutionFlow:
    """测试完整执行流程"""

    @pytest.mark.asyncio
    async def test_simple_execution(self):
        """测试简单执行流程"""
        from harness.execution import ResearchExecutionLoop

        # 模拟一个简单的研究任务
        topic = "测试研究主题"
        questions = ["测试问题1", "测试问题2"]

        # 我们不会真正运行完整流程，只是测试初始化
        loop = ResearchExecutionLoop(topic, questions, max_hops=1)
        assert loop.topic == topic
        assert loop.original_questions == questions
        assert loop.current_state == ResearchExecutionLoop.STATE_DECOMPOSE


def test_domain_integration():
    """测试领域集成"""
    from harness.domain import CodeGenerationDomain, CitationFormatter

    # 测试模型提取
    models = CodeGenerationDomain.extract_model_names("GPT-4和Codex是流行的代码生成模型")
    assert "GPT-4" in models
    assert "Codex" in models

    # 测试引用格式化
    citation = CitationFormatter.format_arXiv(
        "https://arxiv.org/abs/2401.01234",
        ["John Doe", "Jane Smith"],
        2024,
        "测试论文"
    )
    assert "John Doe, Jane Smith(2024)" in citation
    assert "测试论文" in citation
    assert "https://arxiv.org/abs/2401.01234" in citation


if __name__ == "__main__":
    # 运行所有测试
    import sys
    pytest.main([__file__, "-v"])