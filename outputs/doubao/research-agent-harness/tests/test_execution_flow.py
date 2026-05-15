import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from harness.execution import ResearchExecutionLoop


class TestResearchExecutionLoop:
    """测试研究执行循环"""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """测试执行循环初始化"""
        topic = "测试主题"
        questions = ["问题1", "问题2"]
        loop = ResearchExecutionLoop(topic, questions, max_hops=2)

        assert loop.topic == topic
        assert loop.original_questions == questions
        assert loop.current_state == loop.STATE_DECOMPOSE
        assert loop.max_hops == 2
        assert loop.loop_count == 0

    @pytest.mark.asyncio
    @patch('harness.tools.LLMClient.generate')
    async def test_decompose_step(self, mock_generate):
        """测试问题分解步骤"""
        # 模拟LLM响应
        mock_generate.return_value = '["query1", "query2", "query3", "query4", "query5"]'

        topic = "测试主题"
        questions = ["主要问题"]
        loop = ResearchExecutionLoop(topic, questions)

        await loop._handle_decompose()
        assert loop.current_state == loop.STATE_SEARCH
        assert hasattr(loop, 'research_queries')
        assert len(loop.research_queries) >= 10  # 应该至少有10个查询

    @pytest.mark.asyncio
    @patch('harness.tools.WebSearchTool.search')
    async def test_search_step(self, mock_search):
        """测试搜索步骤"""
        mock_search.return_value = [
            {"title": "测试结果1", "url": "https://example.com/1", "snippet": "测试片段1"},
            {"title": "测试结果2", "url": "https://example.com/2", "snippet": "测试片段2"}
        ]

        topic = "测试主题"
        questions = ["问题1"]
        loop = ResearchExecutionLoop(topic, questions)
        await loop._handle_decompose()

        # 执行搜索步骤
        initial_sources_count = len(loop.state_store.state.all_sources)
        await loop._handle_search()

        assert loop.current_query_index == 1
        assert loop.current_state == loop.STATE_SEARCH

    @pytest.mark.asyncio
    async def test_organize_step(self):
        """测试证据组织步骤"""
        topic = "测试主题"
        questions = ["问题1"]
        loop = ResearchExecutionLoop(topic, questions)

        # 添加一些测试证据
        source = Source(url="https://example.com/paper", title="测试论文")
        loop.state_store.add_source(source)

        evidence = Evidence(
            source_url="https://example.com/paper",
            claim="代码生成模型在HumanEval上表现很好"
        )
        loop.state_store.add_evidence(evidence)

        await loop._handle_organize()

        # 检查证据是否被正确分类
        assert len(loop.context.outline_context.section_evidence) > 0

    @pytest.mark.asyncio
    async def test_gap_fill_step(self):
        """测试缺口填补步骤"""
        topic = "测试主题"
        questions = ["问题1"]
        loop = ResearchExecutionLoop(topic, questions)
        loop.state_store.state.hop_count = 0

        # 手动创建一个缺口
        loop.context.outline_context.section_progress["摘要"] = False

        await loop._handle_gap_fill()

        # 检查是否创建了新的查询
        assert loop.current_state == loop.STATE_SEARCH
        assert loop.current_query_index == 0
        assert loop.state_store.state.hop_count == 1

    @pytest.mark.asyncio
    @patch('harness.tools.LLMClient.generate')
    async def test_draft_step(self, mock_generate):
        """测试草稿撰写步骤"""
        mock_generate.return_value = "这是生成的章节内容"

        topic = "测试主题"
        questions = ["问题1"]
        loop = ResearchExecutionLoop(topic, questions)

        # 添加一些测试证据
        source = Source(url="https://example.com/paper", title="测试论文")
        loop.state_store.add_source(source)

        evidence = Evidence(
            source_url="https://example.com/paper",
            claim="代码生成模型在HumanEval上表现很好"
        )
        loop.state_store.add_evidence(evidence)

        # 组织证据
        await loop._handle_organize()

        # 测试草稿撰写
        await loop._handle_draft()

        # 检查章节是否被创建
        assert loop.state_store.draft_manager.get_section("摘要") is not None


def test_cli_commands():
    """测试CLI命令"""
    from harness.cli import ResearchCLI
    cli = ResearchCLI()

    # 测试帮助命令
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        cli.print_help()
    output = f.getvalue()
    assert "可用命令:" in output
    assert "new <topic>" in output
    assert "exit/quit" in output


class TestIntegration:
    """完整集成测试"""

    @pytest.mark.asyncio
    async def test_full_research_task(self):
        """测试完整研究任务流程"""
        from harness.core import ResearchHarness

        harness = ResearchHarness(output_dir="./test_output")

        # 测试创建研究任务
        topic = "大语言模型在代码生成领域的进展"
        questions = [
            "主流代码生成模型有哪些?",
            "它们的性能如何?"
        ]

        task = await harness.create_research_task(topic, questions)
        assert task is not None
        assert task.topic == topic
        assert task.original_questions == questions

        # 清理测试目录
        import shutil
        shutil.rmtree("./test_output", ignore_errors=True)


if __name__ == "__main__":
    import sys
    pytest.main([__file__, "-v"])