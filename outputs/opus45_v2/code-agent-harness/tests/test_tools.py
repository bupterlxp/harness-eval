"""Tests for the tools module."""

import tempfile
from pathlib import Path

import pytest

from harness.tools import Tool, ToolRegistry


class TestTool:
    """Tests for Tool class."""

    def test_tool_creation(self) -> None:
        """Test creating a tool."""
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters={"param1": {"type": "string"}},
            required=["param1"],
            handler=lambda param1: {"result": param1},
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert "param1" in tool.parameters

    def test_tool_validation_passes(self) -> None:
        """Test validation passes with correct params."""
        tool = Tool(
            name="test",
            description="test",
            parameters={"param1": {"type": "string"}},
            required=["param1"],
            handler=lambda param1: {},
        )

        errors = tool.validate_input({"param1": "value"})
        assert errors == []

    def test_tool_validation_fails_missing_required(self) -> None:
        """Test validation fails with missing required param."""
        tool = Tool(
            name="test",
            description="test",
            parameters={"param1": {"type": "string"}},
            required=["param1"],
            handler=lambda param1: {},
        )

        errors = tool.validate_input({})
        assert len(errors) == 1
        assert "param1" in errors[0]

    def test_tool_to_schema(self) -> None:
        """Test exporting tool as schema."""
        tool = Tool(
            name="test",
            description="A test",
            parameters={"p": {"type": "string"}},
            required=["p"],
            handler=lambda p: {},
        )

        schema = tool.to_schema()
        assert schema["name"] == "test"
        assert schema["description"] == "A test"
        assert schema["required"] == ["p"]


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_registry_has_builtin_tools(self) -> None:
        """Test registry includes builtin tools."""
        registry = ToolRegistry()
        tools = registry.list_tools()

        assert "read_file" in tools
        assert "write_file" in tools
        assert "scan_repo" in tools
        assert "search_code" in tools
        assert "run_command" in tools
        assert "generate_diff" in tools

    def test_register_custom_tool(self) -> None:
        """Test registering a custom tool."""
        registry = ToolRegistry()
        registry.register(
            name="custom_tool",
            description="Custom tool",
            parameters={"input": {"type": "string"}},
            required=["input"],
            handler=lambda input: {"output": input.upper()},
        )

        assert "custom_tool" in registry.list_tools()
        result = registry.call("custom_tool", {"input": "hello"})
        assert result["output"] == "HELLO"

    def test_call_unknown_tool(self) -> None:
        """Test calling unknown tool returns error."""
        registry = ToolRegistry()
        result = registry.call("nonexistent", {})
        assert "error" in result

    def test_read_file_tool(self) -> None:
        """Test read_file tool."""
        registry = ToolRegistry()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Hello, World!")
            f.flush()

            result = registry.call("read_file", {"path": f.name})
            assert result["content"] == "Hello, World!"

    def test_write_file_tool(self) -> None:
        """Test write_file tool."""
        registry = ToolRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            result = registry.call("write_file", {
                "path": str(file_path),
                "content": "Test content",
            })

            assert result["success"]
            assert file_path.read_text() == "Test content"

    def test_scan_repo_tool(self) -> None:
        """Test scan_repo tool."""
        registry = ToolRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("print('hello')")
            (Path(tmpdir) / "utils.py").write_text("def helper(): pass")

            result = registry.call("scan_repo", {"path": tmpdir})

            assert "files" in result
            assert "main.py" in result["files"]
            assert "utils.py" in result["files"]

    def test_search_code_tool(self) -> None:
        """Test search_code tool."""
        registry = ToolRegistry()

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("def hello():\n    print('world')")

            result = registry.call("search_code", {
                "path": tmpdir,
                "pattern": "hello",
            })

            assert len(result["matches"]) > 0
            assert result["files"][0] == "main.py"

    def test_run_command_tool(self) -> None:
        """Test run_command tool."""
        registry = ToolRegistry()

        result = registry.call("run_command", {"command": "echo test"})

        assert result["exit_code"] == 0
        assert "test" in result["stdout"]

    def test_generate_diff_tool(self) -> None:
        """Test generate_diff tool."""
        registry = ToolRegistry()

        result = registry.call("generate_diff", {
            "old_content": "line1\nline2\n",
            "new_content": "line1\nline2_modified\n",
            "file_path": "test.txt",
        })

        assert "diff" in result
        assert "-line2" in result["diff"]
        assert "+line2_modified" in result["diff"]

    def test_call_history_tracking(self) -> None:
        """Test that call history is tracked."""
        registry = ToolRegistry()
        registry.clear_history()

        registry.call("run_command", {"command": "echo 1"})
        registry.call("run_command", {"command": "echo 2"})

        history = registry.get_call_history()
        assert len(history) == 2
        assert history[0]["tool"] == "run_command"

    def test_get_schemas(self) -> None:
        """Test getting all tool schemas."""
        registry = ToolRegistry()
        schemas = registry.get_schemas()

        assert len(schemas) > 0
        assert all("name" in s for s in schemas)
        assert all("description" in s for s in schemas)
