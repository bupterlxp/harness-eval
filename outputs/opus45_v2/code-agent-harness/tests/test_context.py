"""Tests for the context module."""

import pytest

from harness.context import ContextManager, ContentChunk, FileSummary


class TestContentChunk:
    """Tests for ContentChunk class."""

    def test_chunk_creation(self) -> None:
        """Test creating a content chunk."""
        chunk = ContentChunk(
            content="Some code content",
            source="file.py",
            chunk_type="code",
        )

        assert chunk.content == "Some code content"
        assert chunk.source == "file.py"
        assert chunk.chunk_type == "code"

    def test_token_estimation(self) -> None:
        """Test token estimation."""
        chunk = ContentChunk(
            content="x" * 100,
            source="test",
            chunk_type="test",
        )

        assert chunk.token_estimate == 25

    def test_importance_default(self) -> None:
        """Test default importance value."""
        chunk = ContentChunk(
            content="test",
            source="test",
            chunk_type="test",
        )

        assert chunk.importance == 1.0


class TestContextManager:
    """Tests for ContextManager."""

    def test_build_prompt_understand(self) -> None:
        """Test building understand prompt."""
        cm = ContextManager()
        prompt = cm.build_prompt(
            "understand",
            task_type="bug_fix",
            task_description="Fix login bug",
            repo_structure={"files": ["main.py"]},
            constraints=["no breaking changes"],
        )

        assert "bug_fix" in prompt
        assert "Fix login bug" in prompt

    def test_build_prompt_plan(self) -> None:
        """Test building plan prompt."""
        cm = ContextManager()
        prompt = cm.build_prompt(
            "plan",
            task_type="feature",
            task_description="Add logout",
            understanding={"summary": "Need to add logout"},
            file_summaries={"app.py": "Main app"},
            constraints=[],
            previous_errors=None,
        )

        assert "Add logout" in prompt

    def test_build_prompt_edit(self) -> None:
        """Test building edit prompt."""
        cm = ContextManager()
        prompt = cm.build_prompt(
            "edit",
            task_description="Add function",
            file_path="main.py",
            current_content="def main(): pass",
            edit_instruction="Add logging",
            constraints=[],
        )

        assert "main.py" in prompt
        assert "Add logging" in prompt

    def test_summarize_file_python(self) -> None:
        """Test file summarization for Python."""
        cm = ContextManager()
        content = '''
import os
from pathlib import Path

class MyClass:
    pass

def my_function():
    pass

async def async_func():
    pass
'''
        summary = cm.summarize_file("test.py", content)

        assert summary.language == "python"
        assert "MyClass" in summary.classes
        assert "my_function" in summary.functions
        assert "async_func" in summary.functions
        assert any("import os" in imp for imp in summary.imports)

    def test_summarize_file_caching(self) -> None:
        """Test that file summaries are cached."""
        cm = ContextManager()
        content = "def foo(): pass"

        summary1 = cm.summarize_file("test.py", content)
        summary2 = cm.summarize_file("test.py", content)

        assert summary1.content_hash == summary2.content_hash

    def test_truncate_content(self) -> None:
        """Test content truncation."""
        cm = ContextManager(max_file_tokens=100)
        long_content = "\n".join([f"line {i}" for i in range(1000)])

        truncated = cm.truncate_content(long_content)

        assert len(truncated) < len(long_content)
        assert "truncated" in truncated

    def test_truncate_content_preserves_short(self) -> None:
        """Test that short content is not truncated."""
        cm = ContextManager(max_file_tokens=1000)
        short_content = "def foo(): pass"

        result = cm.truncate_content(short_content)

        assert result == short_content

    def test_add_and_get_context(self) -> None:
        """Test adding and retrieving context chunks."""
        cm = ContextManager()
        cm.clear_context()

        cm.add_chunk("Code A", "file_a.py", "code", importance=1.0)
        cm.add_chunk("Code B", "file_b.py", "code", importance=0.5)

        context = cm.get_context()

        assert "Code A" in context
        assert "Code B" in context

    def test_context_prioritization(self) -> None:
        """Test that higher importance chunks are prioritized."""
        cm = ContextManager(max_context_tokens=50)

        cm.add_chunk("Low importance", "low.py", "code", importance=0.1)
        cm.add_chunk("High importance", "high.py", "code", importance=1.0)

        context = cm.get_context()

        assert "High importance" in context

    def test_detect_language(self) -> None:
        """Test language detection from file extension."""
        cm = ContextManager()

        assert cm._detect_language("file.py") == "python"
        assert cm._detect_language("file.js") == "javascript"
        assert cm._detect_language("file.ts") == "typescript"
        assert cm._detect_language("file.go") == "go"
        assert cm._detect_language("file.unknown") == "unknown"

    def test_clear_context(self) -> None:
        """Test clearing context."""
        cm = ContextManager()
        cm.add_chunk("Test", "test.py", "code")
        cm.clear_context()

        assert cm.get_context() == ""
