"""Tests for the Tools module."""

import tempfile
from pathlib import Path

import pytest

from harness.tools import Tool, ToolRegistry, ToolResult, ToolSchema


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_success_result(self):
        result = ToolResult(success=True, output={"data": "value"})
        assert result.success
        assert result.output == {"data": "value"}
        assert result.error is None

    def test_error_result(self):
        result = ToolResult(success=False, output=None, error="Something failed")
        assert not result.success
        assert result.error == "Something failed"


class TestTool:
    """Tests for Tool dataclass."""

    def test_to_schema(self):
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters={"arg1": {"type": "string"}},
            returns={"type": "object"},
            handler=lambda: ToolResult(success=True, output=None),
        )
        schema = tool.to_schema()
        assert schema["name"] == "test_tool"
        assert schema["description"] == "A test tool"


class TestToolRegistry:
    """Tests for ToolRegistry."""

    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_builtin_tools_registered(self, registry):
        tools = registry.list_tools()
        tool_names = [t["name"] for t in tools]

        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names
        assert "search_code" in tool_names
        assert "list_directory" in tool_names
        assert "execute_command" in tool_names
        assert "find_definition" in tool_names
        assert "get_file_structure" in tool_names

    def test_register_custom_tool(self, registry):
        def custom_handler(x: int) -> ToolResult:
            return ToolResult(success=True, output=x * 2)

        registry.register(
            name="custom",
            description="Custom tool",
            parameters={"x": {"type": "integer"}},
            returns={"type": "integer"},
            handler=custom_handler,
        )

        result = registry.execute("custom", x=5)
        assert result.success
        assert result.output == 10

    def test_get_tool(self, registry):
        tool = registry.get_tool("read_file")
        assert tool is not None
        assert tool.name == "read_file"

    def test_get_nonexistent_tool(self, registry):
        tool = registry.get_tool("nonexistent")
        assert tool is None

    def test_execute_nonexistent_tool(self, registry):
        result = registry.execute("nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()

    def test_get_tools_for_llm(self, registry):
        tools = registry.get_tools_for_llm()
        assert isinstance(tools, list)
        assert all(t["type"] == "function" for t in tools)
        assert all("function" in t for t in tools)

    def test_read_file(self, registry, temp_dir):
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = registry.execute("read_file", path=str(test_file))

        assert result.success
        assert "line1" in result.output["content"]
        assert result.output["lines"] == 3

    def test_read_file_with_range(self, registry, temp_dir):
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("\n".join(f"line{i}" for i in range(1, 11)))

        result = registry.execute("read_file", path=str(test_file), start_line=3, end_line=5)

        assert result.success
        assert "line3" in result.output["content"]
        assert "line5" in result.output["content"]
        assert "line1" not in result.output["content"]

    def test_read_nonexistent_file(self, registry):
        result = registry.execute("read_file", path="/nonexistent/path.txt")
        assert not result.success
        assert "not found" in result.error.lower()

    def test_write_file(self, registry, temp_dir):
        test_file = Path(temp_dir) / "new_file.txt"

        result = registry.execute("write_file", path=str(test_file), content="new content")

        assert result.success
        assert test_file.exists()
        assert test_file.read_text() == "new content"

    def test_write_file_creates_dirs(self, registry, temp_dir):
        test_file = Path(temp_dir) / "nested" / "dir" / "file.txt"

        result = registry.execute("write_file", path=str(test_file), content="content")

        assert result.success
        assert test_file.exists()

    def test_edit_file(self, registry, temp_dir):
        test_file = Path(temp_dir) / "edit_test.py"
        test_file.write_text("def foo():\n    pass")

        result = registry.execute(
            "edit_file",
            path=str(test_file),
            old_content="pass",
            new_content="return 42",
        )

        assert result.success
        assert "return 42" in test_file.read_text()

    def test_edit_file_not_found(self, registry, temp_dir):
        result = registry.execute(
            "edit_file",
            path=str(Path(temp_dir) / "nonexistent.py"),
            old_content="x",
            new_content="y",
        )
        assert not result.success

    def test_search_code(self, registry, temp_dir):
        file1 = Path(temp_dir) / "file1.py"
        file1.write_text("def hello():\n    print('hello')")

        file2 = Path(temp_dir) / "file2.py"
        file2.write_text("def world():\n    print('world')")

        result = registry.execute("search_code", pattern="def.*\\(", path=temp_dir)

        assert result.success
        assert len(result.output) >= 2

    def test_search_code_with_file_pattern(self, registry, temp_dir):
        py_file = Path(temp_dir) / "code.py"
        py_file.write_text("python code")

        txt_file = Path(temp_dir) / "text.txt"
        txt_file.write_text("text file")

        result = registry.execute(
            "search_code",
            pattern="code",
            path=temp_dir,
            file_pattern="*.py",
        )

        assert result.success
        assert all("code.py" in r["file"] for r in result.output)

    def test_list_directory(self, registry, temp_dir):
        (Path(temp_dir) / "file1.py").touch()
        (Path(temp_dir) / "file2.txt").touch()
        (Path(temp_dir) / "subdir").mkdir()

        result = registry.execute("list_directory", path=temp_dir)

        assert result.success
        assert "file1.py" in result.output
        assert "subdir" in result.output

    def test_list_directory_recursive(self, registry, temp_dir):
        subdir = Path(temp_dir) / "subdir"
        subdir.mkdir()
        (subdir / "nested.py").touch()

        result = registry.execute("list_directory", path=temp_dir, recursive=True)

        assert result.success
        assert any("nested.py" in item for item in result.output)

    def test_execute_command(self, registry):
        result = registry.execute("execute_command", command="echo 'hello'")

        assert result.success
        assert "hello" in result.output["stdout"]
        assert result.output["returncode"] == 0

    def test_execute_command_failure(self, registry):
        result = registry.execute("execute_command", command="exit 1")

        assert not result.success
        assert result.output["returncode"] == 1

    def test_find_definition(self, registry, temp_dir):
        test_file = Path(temp_dir) / "module.py"
        test_file.write_text("""
def my_function():
    pass

class MyClass:
    def method(self):
        pass
""")

        result = registry.execute("find_definition", name="my_function", path=temp_dir)
        assert result.success
        assert len(result.output) >= 1
        assert any("my_function" in r["definition"] for r in result.output)

    def test_get_file_structure(self, registry, temp_dir):
        test_file = Path(temp_dir) / "structured.py"
        test_file.write_text("""
import os
from pathlib import Path

class Parser:
    def parse(self):
        pass

def main():
    pass
""")

        result = registry.execute("get_file_structure", path=str(test_file))

        assert result.success
        assert "imports" in result.output
        assert "classes" in result.output
        assert "functions" in result.output
