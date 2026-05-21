"""Tests for harness.tools module."""

import tempfile
import shutil
from pathlib import Path

import pytest

from harness.tools import ToolRegistry, ToolResult, ToolSchema


class TestToolRegistry:
    """Tests for ToolRegistry functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        d = tempfile.mkdtemp()
        yield Path(d)
        shutil.rmtree(d)

    @pytest.fixture
    def registry(self, temp_dir):
        """Create a ToolRegistry instance."""
        return ToolRegistry(temp_dir)

    def test_builtin_tools_registered(self, registry):
        """Test that built-in tools are registered."""
        tools = registry.list_tools()
        tool_names = [t.name for t in tools]

        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names
        assert "list_directory" in tool_names
        assert "search_code" in tool_names
        assert "run_command" in tool_names

    def test_get_schema(self, registry):
        """Test getting tool schema."""
        schema = registry.get_schema("read_file")
        assert schema is not None
        assert schema.name == "read_file"
        assert "path" in schema.parameters

    def test_unknown_tool_returns_error(self, registry):
        """Test invoking unknown tool returns error."""
        result = registry.invoke("nonexistent_tool")
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_read_file(self, registry, temp_dir):
        """Test reading a file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello World")

        result = registry.invoke("read_file", path="test.txt")
        assert result.success is True
        assert result.output == "Hello World"

    def test_read_file_with_lines(self, registry, temp_dir):
        """Test reading specific lines from a file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        result = registry.invoke("read_file", path="test.txt", start_line=2, end_line=4)
        assert result.success is True
        assert result.output == "line2\nline3\nline4"

    def test_read_file_not_found(self, registry):
        """Test reading nonexistent file."""
        result = registry.invoke("read_file", path="nonexistent.txt")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_write_file(self, registry, temp_dir):
        """Test writing a file."""
        result = registry.invoke("write_file", path="new.txt", content="New content")
        assert result.success is True

        written = (temp_dir / "new.txt").read_text()
        assert written == "New content"

    def test_write_file_creates_dirs(self, registry, temp_dir):
        """Test that write_file creates parent directories."""
        result = registry.invoke("write_file", path="subdir/new.txt", content="Content")
        assert result.success is True
        assert (temp_dir / "subdir" / "new.txt").exists()

    def test_edit_file(self, registry, temp_dir):
        """Test editing a file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello World")

        result = registry.invoke(
            "edit_file",
            path="test.txt",
            old_content="World",
            new_content="Universe"
        )
        assert result.success is True
        assert test_file.read_text() == "Hello Universe"

    def test_edit_file_content_not_found(self, registry, temp_dir):
        """Test edit fails when content not found."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello World")

        result = registry.invoke(
            "edit_file",
            path="test.txt",
            old_content="Nonexistent",
            new_content="New"
        )
        assert result.success is False

    def test_list_directory(self, registry, temp_dir):
        """Test listing directory contents."""
        (temp_dir / "file1.txt").write_text("1")
        (temp_dir / "file2.py").write_text("2")
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "file3.txt").write_text("3")

        result = registry.invoke("list_directory")
        assert result.success is True
        assert "file1.txt" in result.output
        assert "file2.py" in result.output

    def test_list_directory_recursive(self, registry, temp_dir):
        """Test recursive directory listing."""
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "nested.txt").write_text("nested")

        result = registry.invoke("list_directory", recursive=True)
        assert result.success is True

    def test_list_directory_pattern(self, registry, temp_dir):
        """Test directory listing with pattern filter."""
        (temp_dir / "file1.txt").write_text("1")
        (temp_dir / "file2.py").write_text("2")

        result = registry.invoke("list_directory", pattern="*.py")
        assert result.success is True
        assert "file2.py" in result.output
        assert "file1.txt" not in result.output

    def test_search_code(self, registry, temp_dir):
        """Test searching for patterns in code."""
        (temp_dir / "code.py").write_text("def hello():\n    return 'world'\n")
        (temp_dir / "other.py").write_text("x = 1\n")

        result = registry.invoke("search_code", pattern="def hello")
        assert result.success is True
        assert len(result.output) == 1
        assert result.output[0]["file"] == "code.py"

    def test_search_code_regex(self, registry, temp_dir):
        """Test regex pattern in search."""
        (temp_dir / "code.py").write_text("def func1():\n    pass\ndef func2():\n    pass\n")

        result = registry.invoke("search_code", pattern=r"def func\d")
        assert result.success is True
        assert len(result.output) == 2

    def test_run_command(self, registry, temp_dir):
        """Test running a shell command."""
        result = registry.invoke("run_command", command="echo 'hello'")
        assert result.success is True
        assert "hello" in result.output["stdout"]
        assert result.output["returncode"] == 0

    def test_run_command_failure(self, registry):
        """Test command failure handling."""
        result = registry.invoke("run_command", command="exit 1")
        assert result.success is True
        assert result.output["returncode"] == 1

    def test_get_repo_structure(self, registry, temp_dir):
        """Test getting repository structure."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "main.py").write_text("main")
        (temp_dir / "tests").mkdir()
        (temp_dir / "tests" / "test_main.py").write_text("test")

        result = registry.invoke("get_repo_structure", max_depth=2)
        assert result.success is True
        assert "src" in result.output
        assert "tests" in result.output

    def test_get_tools_description(self, registry):
        """Test getting formatted tools description."""
        desc = registry.get_tools_description()
        assert "Available tools:" in desc
        assert "read_file" in desc
        assert "write_file" in desc


class TestToolResult:
    """Tests for ToolResult."""

    def test_success_result(self):
        """Test successful result."""
        result = ToolResult(success=True, output="data")
        assert result.success is True
        assert result.output == "data"
        assert result.error is None

    def test_error_result(self):
        """Test error result."""
        result = ToolResult(success=False, output=None, error="Failed")
        assert result.success is False
        assert result.error == "Failed"

    def test_to_dict(self):
        """Test serialization to dict."""
        result = ToolResult(success=True, output="test", metadata={"key": "value"})
        d = result.to_dict()
        assert d["success"] is True
        assert d["output"] == "test"
        assert d["metadata"] == {"key": "value"}


class TestCustomToolRegistration:
    """Tests for custom tool registration."""

    def test_register_custom_tool(self, tmp_path):
        """Test registering a custom tool."""
        registry = ToolRegistry(tmp_path)

        @registry.register(
            name="custom_tool",
            description="A custom tool",
            parameters={"value": {"type": "integer"}},
            required=["value"]
        )
        def custom_tool(value: int) -> int:
            return value * 2

        result = registry.invoke("custom_tool", value=5)
        assert result.success is True
        assert result.output == 10

    def test_missing_required_parameter(self, tmp_path):
        """Test error on missing required parameter."""
        registry = ToolRegistry(tmp_path)

        @registry.register(
            name="required_param_tool",
            description="Test tool",
            parameters={"required_val": {"type": "string"}},
            required=["required_val"]
        )
        def required_param_tool(required_val: str) -> str:
            return required_val

        result = registry.invoke("required_param_tool")
        assert result.success is False
        assert "Missing required parameter" in result.error
