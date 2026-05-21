"""
Tool Registry (T) - Manages registration and execution of tools.

Responsibilities:
- Tool registration with input/output schemas
- File read/write operations
- Code search (keyword/pattern)
- Command execution
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypedDict


class ToolSchema(TypedDict, total=False):
    """Schema definition for a tool."""
    name: str
    description: str
    parameters: dict[str, Any]
    returns: dict[str, Any]


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    output: Any
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    """A registered tool with schema and implementation."""
    name: str
    description: str
    parameters: dict[str, Any]
    returns: dict[str, Any]
    handler: Callable[..., ToolResult]

    def to_schema(self) -> ToolSchema:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
        }


class ToolRegistry:
    """Registry for managing and executing tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_builtin_tools()

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        returns: dict[str, Any],
        handler: Callable[..., ToolResult],
    ) -> None:
        """Register a new tool."""
        self._tools[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            returns=returns,
            handler=handler,
        )

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSchema]:
        """List all registered tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool '{tool_name}' not found",
            )

        try:
            return tool.handler(**kwargs)
        except Exception as e:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool execution failed: {str(e)}",
            )

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        """Get tool definitions formatted for LLM function calling."""
        tools = []
        for tool in self._tools.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": tool.parameters,
                        "required": [k for k, v in tool.parameters.items() if v.get("required", False)],
                    },
                },
            })
        return tools

    def _register_builtin_tools(self) -> None:
        """Register built-in tools."""
        self.register(
            name="read_file",
            description="Read the contents of a file. Returns file content with line numbers.",
            parameters={
                "path": {"type": "string", "description": "Path to the file to read", "required": True},
                "start_line": {"type": "integer", "description": "Starting line number (1-indexed)", "required": False},
                "end_line": {"type": "integer", "description": "Ending line number (inclusive)", "required": False},
            },
            returns={"type": "object", "properties": {"content": {"type": "string"}, "lines": {"type": "integer"}}},
            handler=self._read_file,
        )

        self.register(
            name="write_file",
            description="Write content to a file, creating directories if needed.",
            parameters={
                "path": {"type": "string", "description": "Path to the file to write", "required": True},
                "content": {"type": "string", "description": "Content to write to the file", "required": True},
            },
            returns={"type": "object", "properties": {"bytes_written": {"type": "integer"}}},
            handler=self._write_file,
        )

        self.register(
            name="edit_file",
            description="Edit a file by replacing specific content. More precise than write_file for modifications.",
            parameters={
                "path": {"type": "string", "description": "Path to the file to edit", "required": True},
                "old_content": {"type": "string", "description": "Content to find and replace", "required": True},
                "new_content": {"type": "string", "description": "New content to insert", "required": True},
            },
            returns={"type": "object", "properties": {"success": {"type": "boolean"}, "replacements": {"type": "integer"}}},
            handler=self._edit_file,
        )

        self.register(
            name="search_code",
            description="Search for patterns in code files using regex or keywords.",
            parameters={
                "pattern": {"type": "string", "description": "Search pattern (regex supported)", "required": True},
                "path": {"type": "string", "description": "Directory or file to search in", "required": False},
                "file_pattern": {"type": "string", "description": "Glob pattern to filter files (e.g., '*.py')", "required": False},
                "max_results": {"type": "integer", "description": "Maximum number of results to return", "required": False},
            },
            returns={"type": "array", "items": {"type": "object", "properties": {"file": {"type": "string"}, "line": {"type": "integer"}, "content": {"type": "string"}}}},
            handler=self._search_code,
        )

        self.register(
            name="list_directory",
            description="List files and directories in a path.",
            parameters={
                "path": {"type": "string", "description": "Directory path to list", "required": True},
                "recursive": {"type": "boolean", "description": "List recursively", "required": False},
                "pattern": {"type": "string", "description": "Glob pattern to filter results", "required": False},
            },
            returns={"type": "array", "items": {"type": "string"}},
            handler=self._list_directory,
        )

        self.register(
            name="execute_command",
            description="Execute a shell command and return the output.",
            parameters={
                "command": {"type": "string", "description": "Command to execute", "required": True},
                "cwd": {"type": "string", "description": "Working directory for the command", "required": False},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
            },
            returns={"type": "object", "properties": {"stdout": {"type": "string"}, "stderr": {"type": "string"}, "returncode": {"type": "integer"}}},
            handler=self._execute_command,
        )

        self.register(
            name="find_definition",
            description="Find the definition of a function, class, or variable in the codebase.",
            parameters={
                "name": {"type": "string", "description": "Name of the symbol to find", "required": True},
                "path": {"type": "string", "description": "Directory to search in", "required": False},
                "symbol_type": {"type": "string", "description": "Type: 'function', 'class', 'variable', or 'any'", "required": False},
            },
            returns={"type": "array", "items": {"type": "object", "properties": {"file": {"type": "string"}, "line": {"type": "integer"}, "definition": {"type": "string"}}}},
            handler=self._find_definition,
        )

        self.register(
            name="get_file_structure",
            description="Get the structure of a Python file (classes, functions, imports).",
            parameters={
                "path": {"type": "string", "description": "Path to the Python file", "required": True},
            },
            returns={"type": "object", "properties": {"imports": {"type": "array"}, "classes": {"type": "array"}, "functions": {"type": "array"}}},
            handler=self._get_file_structure,
        )

    @staticmethod
    def _read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> ToolResult:
        """Read a file with optional line range."""
        try:
            file_path = Path(path)
            if not file_path.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {path}")

            content = file_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            total_lines = len(lines)

            if start_line is not None or end_line is not None:
                start = (start_line or 1) - 1
                end = end_line or total_lines
                lines = lines[start:end]
                numbered = [f"{i + start + 1}: {line}" for i, line in enumerate(lines)]
            else:
                numbered = [f"{i + 1}: {line}" for i, line in enumerate(lines)]

            return ToolResult(
                success=True,
                output={"content": "\n".join(numbered), "lines": total_lines},
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _write_file(path: str, content: str) -> ToolResult:
        """Write content to a file."""
        try:
            file_path = Path(path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                output={"bytes_written": len(content.encode("utf-8"))},
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _edit_file(path: str, old_content: str, new_content: str) -> ToolResult:
        """Edit a file by replacing content."""
        try:
            file_path = Path(path)
            if not file_path.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {path}")

            content = file_path.read_text(encoding="utf-8")
            if old_content not in content:
                return ToolResult(
                    success=False,
                    output={"replacements": 0},
                    error="Old content not found in file",
                )

            new_file_content = content.replace(old_content, new_content, 1)
            file_path.write_text(new_file_content, encoding="utf-8")

            return ToolResult(
                success=True,
                output={"success": True, "replacements": 1},
            )
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _search_code(
        pattern: str,
        path: str | None = None,
        file_pattern: str | None = None,
        max_results: int | None = None,
    ) -> ToolResult:
        """Search for patterns in code."""
        try:
            search_path = Path(path) if path else Path.cwd()
            if not search_path.exists():
                return ToolResult(success=False, output=None, error=f"Path not found: {search_path}")

            results = []
            regex = re.compile(pattern, re.IGNORECASE)
            max_results = max_results or 100

            if search_path.is_file():
                files = [search_path]
            else:
                glob_pattern = file_pattern or "**/*"
                files = [f for f in search_path.glob(glob_pattern) if f.is_file()]

            for file_path in files:
                if len(results) >= max_results:
                    break

                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            results.append({
                                "file": str(file_path),
                                "line": i,
                                "content": line.strip()[:200],
                            })
                            if len(results) >= max_results:
                                break
                except (OSError, UnicodeDecodeError):
                    continue

            return ToolResult(success=True, output=results)
        except re.error as e:
            return ToolResult(success=False, output=None, error=f"Invalid regex pattern: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _list_directory(
        path: str,
        recursive: bool = False,
        pattern: str | None = None,
    ) -> ToolResult:
        """List directory contents."""
        try:
            dir_path = Path(path)
            if not dir_path.exists():
                return ToolResult(success=False, output=None, error=f"Directory not found: {path}")

            if not dir_path.is_dir():
                return ToolResult(success=False, output=None, error=f"Not a directory: {path}")

            if recursive:
                glob_pattern = pattern or "**/*"
                items = [str(p.relative_to(dir_path)) for p in dir_path.glob(glob_pattern)]
            else:
                items = [p.name for p in dir_path.iterdir()]
                if pattern:
                    items = [i for i in items if fnmatch.fnmatch(i, pattern)]

            return ToolResult(success=True, output=sorted(items)[:500])
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _execute_command(
        command: str,
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> ToolResult:
        """Execute a shell command."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout or 120,
            )
            return ToolResult(
                success=result.returncode == 0,
                output={
                    "stdout": result.stdout[:10000],
                    "stderr": result.stderr[:5000],
                    "returncode": result.returncode,
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output=None, error="Command timed out")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _find_definition(
        name: str,
        path: str | None = None,
        symbol_type: str | None = None,
    ) -> ToolResult:
        """Find symbol definitions in Python code."""
        try:
            search_path = Path(path) if path else Path.cwd()
            results = []

            patterns = {
                "function": rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(",
                "class": rf"^\s*class\s+{re.escape(name)}\s*[:\(]",
                "variable": rf"^\s*{re.escape(name)}\s*=",
            }

            if symbol_type and symbol_type != "any":
                search_patterns = {symbol_type: patterns.get(symbol_type, patterns["variable"])}
            else:
                search_patterns = patterns

            files = search_path.glob("**/*.py") if search_path.is_dir() else [search_path]

            for file_path in files:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(content.splitlines(), 1):
                        for stype, pattern in search_patterns.items():
                            if re.match(pattern, line):
                                results.append({
                                    "file": str(file_path),
                                    "line": i,
                                    "type": stype,
                                    "definition": line.strip()[:200],
                                })
                except (OSError, UnicodeDecodeError):
                    continue

            return ToolResult(success=True, output=results[:50])
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))

    @staticmethod
    def _get_file_structure(path: str) -> ToolResult:
        """Parse Python file structure using AST."""
        import ast

        try:
            file_path = Path(path)
            if not file_path.exists():
                return ToolResult(success=False, output=None, error=f"File not found: {path}")

            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)

            imports = []
            classes = []
            functions = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({"name": alias.name, "alias": alias.asname, "line": node.lineno})
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        imports.append({
                            "name": f"{module}.{alias.name}",
                            "alias": alias.asname,
                            "line": node.lineno,
                        })
                elif isinstance(node, ast.ClassDef):
                    classes.append({
                        "name": node.name,
                        "line": node.lineno,
                        "bases": [ast.unparse(b) if hasattr(ast, "unparse") else str(b) for b in node.bases],
                        "methods": [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))],
                    })
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not any(node.lineno >= c["line"] for c in classes if "line" in c):
                        functions.append({
                            "name": node.name,
                            "line": node.lineno,
                            "args": [a.arg for a in node.args.args],
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                        })

            return ToolResult(
                success=True,
                output={"imports": imports, "classes": classes, "functions": functions},
            )
        except SyntaxError as e:
            return ToolResult(success=False, output=None, error=f"Syntax error: {e}")
        except Exception as e:
            return ToolResult(success=False, output=None, error=str(e))
