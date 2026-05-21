"""Tests for harness.context module."""

import pytest

from harness.context import (
    ContextManager,
    ContextRole,
    ContextMessage,
    estimate_tokens,
    summarize_code,
    summarize_text,
    extract_code_region,
)


class TestTokenEstimation:
    """Tests for token estimation."""

    def test_basic_estimation(self):
        """Test basic token count estimation."""
        text = "This is a test string"
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert tokens == len(text) // 4 + 1

    def test_empty_string(self):
        """Test estimation for empty string."""
        assert estimate_tokens("") == 1


class TestCodeSummarization:
    """Tests for code summarization."""

    def test_short_code_unchanged(self):
        """Test that short code is returned unchanged."""
        code = "def foo():\n    return 1"
        result = summarize_code(code, max_lines=50)
        assert result == code

    def test_long_code_summarized(self):
        """Test that long code is summarized."""
        code = "\n".join([f"line_{i}" for i in range(100)])
        result = summarize_code(code, max_lines=20)
        assert len(result.split("\n")) <= 21

    def test_extracts_imports(self):
        """Test that imports are preserved."""
        code = """import os
import sys
from pathlib import Path

def some_function():
    pass

class SomeClass:
    pass
"""
        result = summarize_code(code, max_lines=10)
        assert "import os" in result
        assert "import sys" in result
        assert "from pathlib import Path" in result

    def test_extracts_definitions(self):
        """Test that class/function definitions are preserved."""
        code = """
class MyClass:
    def method1(self):
        return 1

    def method2(self, arg):
        return arg * 2

def standalone_function():
    return 42
"""
        result = summarize_code(code, max_lines=20)
        assert "class MyClass:" in result
        assert "def method1" in result
        assert "def standalone_function" in result


class TestTextSummarization:
    """Tests for text summarization."""

    def test_short_text_unchanged(self):
        """Test that short text is returned unchanged."""
        text = "This is short text."
        result = summarize_text(text, max_chars=1000)
        assert result == text

    def test_long_text_truncated(self):
        """Test that long text is truncated."""
        text = "A" * 5000
        result = summarize_text(text, max_chars=100)
        assert len(result) <= 110


class TestCodeRegionExtraction:
    """Tests for code region extraction."""

    def test_extracts_region(self):
        """Test extraction of specific line range."""
        code = "\n".join([f"line {i}" for i in range(1, 21)])
        result = extract_code_region(code, 5, 10, context_lines=2)
        assert ">>> " in result
        assert "line 5" in result
        assert "line 10" in result


class TestContextManager:
    """Tests for ContextManager."""

    @pytest.fixture
    def ctx(self):
        """Create a ContextManager instance."""
        return ContextManager(max_tokens=1000, reserve_tokens=200)

    def test_add_message(self, ctx):
        """Test adding a message."""
        msg = ctx.add_message(ContextRole.USER, "Hello")
        assert msg.role == ContextRole.USER
        assert msg.content == "Hello"
        assert len(ctx.messages) == 1

    def test_system_prompt(self):
        """Test system prompt initialization."""
        ctx = ContextManager(system_prompt="You are a helper.")
        assert ctx.system_message is not None
        assert ctx.system_message.content == "You are a helper."

    def test_get_messages_for_llm(self, ctx):
        """Test formatting messages for LLM API."""
        ctx.add_message(ContextRole.USER, "Question")
        ctx.add_message(ContextRole.ASSISTANT, "Answer")

        messages = ctx.get_messages_for_llm()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_tool_result_truncation(self, ctx):
        """Test tool result automatic truncation."""
        long_result = "x" * 5000
        ctx.add_tool_result("test_tool", long_result, max_chars=500)

        assert len(ctx.messages) == 1
        assert len(ctx.messages[0].content) < 600

    def test_code_context_summarization(self, ctx):
        """Test adding code context with summarization."""
        long_code = "\n".join([f"line_{i} = {i}" for i in range(200)])
        result = ctx.add_code_context("test.py", long_code, summarize=True)
        assert "Structure of test.py" in result
        assert len(result) < len(long_code)

    def test_code_context_region(self, ctx):
        """Test adding code context with specific region."""
        code = "\n".join([f"line {i}" for i in range(1, 51)])
        result = ctx.add_code_context("test.py", code, region=(10, 15))
        assert "lines 10-15" in result
        assert ">>> " in result

    def test_context_compression(self):
        """Test automatic context compression."""
        ctx = ContextManager(max_tokens=500, reserve_tokens=100)

        for i in range(10):
            ctx.add_message(ContextRole.USER, f"Message {i} " * 50)

        assert ctx._current_token_count() <= ctx.available_tokens

    def test_token_usage_tracking(self, ctx):
        """Test token usage statistics."""
        ctx.add_message(ContextRole.USER, "Test message")
        usage = ctx.get_token_usage()

        assert "used" in usage
        assert "available" in usage
        assert "max" in usage
        assert "message_count" in usage
        assert usage["message_count"] == 1

    def test_clear(self, ctx):
        """Test clearing context."""
        ctx.add_message(ContextRole.USER, "Message 1")
        ctx.add_message(ContextRole.ASSISTANT, "Message 2")
        ctx.code_cache["test.py"] = "content"

        ctx.clear()
        assert len(ctx.messages) == 0
        assert len(ctx.code_cache) == 0


class TestContextMessage:
    """Tests for ContextMessage."""

    def test_auto_token_estimation(self):
        """Test automatic token estimation on creation."""
        msg = ContextMessage(role=ContextRole.USER, content="Test content")
        assert msg.token_estimate > 0

    def test_explicit_token_count(self):
        """Test explicit token count."""
        msg = ContextMessage(
            role=ContextRole.USER,
            content="Test",
            token_estimate=100
        )
        assert msg.token_estimate == 100
