"""
Tool registry and base tool classes.
"""

import abc
import subprocess
import os
from typing import Dict, List, Optional, Any, Tuple
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Result of a tool execution."""
    success: bool
    output: str = ""
    error: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTool(abc.ABC):
    """Abstract base class for all tools."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abc.abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        pass

    def __repr__(self) -> str:
        return f"{self.name}(description={self.description})"


class ToolRegistry:
    """Registry for all available tools."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool in the registry."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool by name with given parameters."""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' not found in registry"
            )
        return tool.execute(**kwargs)


class FileSearchTool(BaseTool):
    """Tool for searching files in the codebase."""

    def __init__(self):
        super().__init__(
            name="file_search",
            description="Search for files matching a pattern in the codebase"
        )

    def execute(self, path: str = ".", pattern: str = "**/*") -> ToolResult:
        """
        Search for files matching a glob pattern.

        Args:
            path: Directory to search in
            pattern: Glob pattern to match
        """
        import glob
        try:
            files = glob.glob(pattern, recursive=True, root_dir=path)
            return ToolResult(
                success=True,
                output=json.dumps(files),
                metadata={"count": len(files)}
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"File search failed: {str(e)}"
            )


class FileEditorTool(BaseTool):
    """Tool for editing files."""

    def __init__(self):
        super().__init__(
            name="file_editor",
            description="Edit files by replacing content"
        )

    def execute(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> ToolResult:
        """
        Edit a file by replacing old_string with new_string.

        Args:
            file_path: Path to the file to edit
            old_string: Text to replace
            new_string: Text to replace with
            replace_all: Replace all occurrences
        """
        try:
            with open(file_path, 'r') as f:
                content = f.read()

            if old_string not in content:
                return ToolResult(
                    success=False,
                    error=f"Pattern not found in file: {file_path}"
                )

            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)

            with open(file_path, 'w') as f:
                f.write(new_content)

            return ToolResult(
                success=True,
                output=f"Successfully edited {file_path}",
                metadata={
                    "file": file_path,
                    "replaced": 1 if not replace_all else content.count(old_string),
                    "old_length": len(old_string),
                    "new_length": len(new_string)
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"File edit failed: {str(e)}"
            )


class TestRunnerTool(BaseTool):
    """Tool for running tests."""

    def __init__(self):
        super().__init__(
            name="test_runner",
            description="Run test suite and return results"
        )

    def execute(self, test_file: str = "test_server.py", pattern: Optional[str] = None) -> ToolResult:
        """
        Run tests using pytest.

        Args:
            test_file: Path to test file or directory
            pattern: Optional test name pattern to run
        """
        try:
            cmd = ["python", "-m", "pytest", test_file]
            if pattern:
                cmd.extend(["-k", pattern])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )

            return ToolResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                metadata={
                    "return_code": result.returncode,
                    "test_file": test_file,
                    "pattern": pattern
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Test runner failed: {str(e)}"
            )


class GitTool(BaseTool):
    """Tool for git operations."""

    def __init__(self):
        super().__init__(
            name="git_tool",
            description="Perform git operations"
        )

    def execute(self, command: str, args: Optional[List[str]] = None) -> ToolResult:
        """
        Execute a git command.

        Args:
            command: Git subcommand (e.g., "status", "commit")
            args: List of additional arguments
        """
        try:
            cmd = ["git", command]
            if args:
                cmd.extend(args)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )

            return ToolResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                metadata={
                    "command": " ".join(cmd),
                    "return_code": result.returncode
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Git operation failed: {str(e)}"
            )


class StaticAnalysisTool(BaseTool):
    """Tool for static code analysis."""

    def __init__(self):
        super().__init__(
            name="static_analysis",
            description="Perform static code analysis"
        )

    def execute(self, file_path: str) -> ToolResult:
        """
        Analyze a file for common issues.

        Args:
            file_path: Path to file to analyze
        """
        try:
            import ast
            with open(file_path, 'r') as f:
                tree = ast.parse(f.read())

            # Simple analysis example - look for unsafe SQL execution
            issues = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            if "%s" in node.args[0].value or "?" not in node.args[0].value:
                                issues.append({
                                    "line": node.lineno,
                                    "issue": "Potential SQL injection vulnerability"
                                })

            return ToolResult(
                success=True,
                output=json.dumps(issues),
                metadata={
                    "file": file_path,
                    "issues_found": len(issues)
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Static analysis failed: {str(e)}"
            )