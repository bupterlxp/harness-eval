"""Tests for the Context module."""

import pytest

from harness.context import ContextEntry, ContextManager, FileContext


class TestContextEntry:
    """Tests for ContextEntry."""

    def test_token_estimation(self):
        entry = ContextEntry(role="user", content="Hello world")
        assert entry.token_estimate > 0
        assert entry.token_estimate == len("Hello world") // 4 + 1

    def test_long_content_estimation(self):
        content = "x" * 1000
        entry = ContextEntry(role="user", content=content)
        assert entry.token_estimate == 251  # 1000 / 4 + 1


class TestContextManager:
    """Tests for ContextManager."""

    @pytest.fixture
    def context(self):
        return ContextManager()

    def test_set_system_prompt(self, context):
        context.set_system_prompt("You are a helpful assistant")
        messages = context.get_messages()
        assert messages[0]["role"] == "system"
        assert "helpful assistant" in messages[0]["content"]

    def test_add_message(self, context):
        context.add_message("user", "Hello")
        context.add_message("assistant", "Hi there")

        messages = context.get_messages()
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_summarize_short_file(self, context):
        content = "line1\nline2\nline3"
        summary = context.summarize_file_content("/test/file.py", content)

        assert "/test/file.py" in summary
        assert "line1" in summary
        assert "line2" in summary

    def test_summarize_long_file(self, context):
        lines = [f"line{i}" for i in range(200)]
        content = "\n".join(lines)

        summary = context.summarize_file_content("/test/long.py", content)

        assert "200 lines" in summary
        assert "line0" in summary or "line1" in summary  # First lines
        assert "Structure summary" in summary

    def test_summarize_file_with_focus_lines(self, context):
        lines = [f"line{i}" for i in range(100)]
        content = "\n".join(lines)

        summary = context.summarize_file_content("/test/file.py", content, focus_lines=[50, 51, 52])

        assert "Relevant sections" in summary
        assert "line50" in summary or "line49" in summary  # Focus area

    def test_summarize_search_results_short(self, context):
        results = [
            {"file": "a.py", "line": 1, "content": "match1"},
            {"file": "b.py", "line": 2, "content": "match2"},
        ]

        summary = context.summarize_search_results(results)

        assert "2 matches" in summary
        assert "a.py" in summary
        assert "b.py" in summary

    def test_summarize_search_results_long(self, context):
        results = [
            {"file": f"file{i}.py", "line": i, "content": f"match{i}"}
            for i in range(50)
        ]

        summary = context.summarize_search_results(results)

        assert "50 matches" in summary
        assert "..." in summary or "more" in summary

    def test_summarize_command_output(self, context):
        stdout = "\n".join([f"output{i}" for i in range(50)])
        stderr = "warning: something"

        summary = context.summarize_command_output(stdout, stderr, 0)

        assert "Exit code: 0" in summary
        assert "stdout" in summary
        assert "stderr" in summary

    def test_get_context_summary(self, context):
        context.add_message("user", "Hello")
        context.add_message("assistant", "Hi")

        summary = context.get_context_summary()

        assert "Messages: 2" in summary
        assert "Recent context" in summary

    def test_compression(self, context):
        context.max_tokens = 2000

        for i in range(20):
            context.add_message("user", f"Message {i} " * 50)

        # Should have compressed significantly
        assert context._total_tokens <= context.max_tokens * 2
        # Should have removed or compressed some messages
        assert len(context._messages) < 20

    def test_clear(self, context):
        context.add_message("user", "Hello")
        context.add_message("assistant", "Hi")

        context.clear()

        assert len(context._messages) == 0
        assert context._total_tokens == 0

    def test_group_consecutive(self, context):
        numbers = [1, 2, 3, 10, 11, 12, 20]
        groups = context._group_consecutive(numbers, gap=3)

        assert len(groups) == 3
        assert groups[0] == (1, 3)
        assert groups[1] == (10, 12)
        assert groups[2] == (20, 20)

    def test_extract_structure(self, context):
        code = """
import os
from pathlib import Path

class MyClass:
    pass

def my_function():
    pass
"""
        structure = context._extract_structure(code)

        assert "Imports" in structure
        assert "Classes" in structure or "MyClass" in structure
        assert "Functions" in structure or "my_function" in structure
