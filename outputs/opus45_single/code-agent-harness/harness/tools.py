"""
Tool Registry (T) - Register and invoke tools with schema validation.

Provides:
- File read/write operations
- Code search (keyword, pattern, AST-based)
- Command execution
- Git operations
- Extensible tool registration
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from functools import wraps


@dataclass
class ToolSchema:
    """Schema definition for a tool's input/output."""
    name: str
    description: str
    parameters: dict[str, dict[str, Any]]
    required: list[str] = field(default_factory=list)
    returns: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result of a tool invocation."""
    success: bool
    output: Any
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata
        }


class ToolRegistry:
    """
    Central registry for all available tools.

    Each tool has:
    - A schema defining inputs and outputs
    - A callable implementation
    - Optional validation
    """

    def __init__(self, work_dir: Path | None = None):
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self._tools: dict[str, tuple[ToolSchema, Callable]] = {}
        self._register_builtin_tools()

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, dict[str, Any]],
        required: list[str] | None = None,
        returns: dict[str, Any] | None = None
    ) -> Callable:
        """Decorator to register a tool."""
        def decorator(func: Callable) -> Callable:
            schema = ToolSchema(
                name=name,
                description=description,
                parameters=parameters,
                required=required or [],
                returns=returns or {"type": "any"}
            )

            @wraps(func)
            def wrapper(**kwargs) -> ToolResult:
                try:
                    for param in schema.required:
                        if param not in kwargs:
                            return ToolResult(
                                success=False,
                                output=None,
                                error=f"Missing required parameter: {param}"
                            )
                    result = func(**kwargs)
                    return ToolResult(success=True, output=result)
                except Exception as e:
                    return ToolResult(success=False, output=None, error=str(e))

            self._tools[name] = (schema, wrapper)
            return wrapper

        return decorator

    def invoke(self, tool_name: str, **kwargs) -> ToolResult:
        """Invoke a tool by name with given arguments."""
        name = tool_name
        if name not in self._tools:
            return ToolResult(
                success=False,
                output=None,
                error=f"Unknown tool: {name}"
            )

        _, tool_func = self._tools[name]
        return tool_func(**kwargs)

    def get_schema(self, name: str) -> ToolSchema | None:
        """Get schema for a specific tool."""
        if name in self._tools:
            return self._tools[name][0]
        return None

    def list_tools(self) -> list[ToolSchema]:
        """List all registered tools."""
        return [schema for schema, _ in self._tools.values()]

    def get_tools_description(self) -> str:
        """Get formatted description of all tools for LLM."""
        lines = ["Available tools:\n"]
        for schema, _ in self._tools.values():
            lines.append(f"- {schema.name}: {schema.description}")
            if schema.parameters:
                lines.append(f"  Parameters: {json.dumps(schema.parameters, indent=4)}")
            if schema.required:
                lines.append(f"  Required: {schema.required}")
        return "\n".join(lines)

    def _register_builtin_tools(self) -> None:
        """Register all built-in tools."""

        @self.register(
            name="read_file",
            description="Read contents of a file",
            parameters={
                "path": {"type": "string", "description": "File path relative to work dir"},
                "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                "end_line": {"type": "integer", "description": "End line (1-indexed)"}
            },
            required=["path"],
            returns={"type": "string", "description": "File contents"}
        )
        def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
            full_path = self.work_dir / path
            if not full_path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            content = full_path.read_text()

            if start_line is not None or end_line is not None:
                lines = content.split("\n")
                start = (start_line or 1) - 1
                end = end_line or len(lines)
                content = "\n".join(lines[start:end])

            return content

        @self.register(
            name="write_file",
            description="Write contents to a file",
            parameters={
                "path": {"type": "string", "description": "File path relative to work dir"},
                "content": {"type": "string", "description": "Content to write"}
            },
            required=["path", "content"],
            returns={"type": "boolean", "description": "Success status"}
        )
        def write_file(path: str, content: str) -> bool:
            full_path = self.work_dir / path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            return True

        @self.register(
            name="edit_file",
            description="Apply a patch/edit to a file",
            parameters={
                "path": {"type": "string", "description": "File path"},
                "old_content": {"type": "string", "description": "Content to replace"},
                "new_content": {"type": "string", "description": "Replacement content"}
            },
            required=["path", "old_content", "new_content"],
            returns={"type": "boolean", "description": "Success status"}
        )
        def edit_file(path: str, old_content: str, new_content: str) -> bool:
            full_path = self.work_dir / path
            if not full_path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            content = full_path.read_text()
            if old_content not in content:
                raise ValueError("Old content not found in file")

            new_file_content = content.replace(old_content, new_content, 1)
            full_path.write_text(new_file_content)
            return True

        @self.register(
            name="list_directory",
            description="List files in a directory",
            parameters={
                "path": {"type": "string", "description": "Directory path"},
                "recursive": {"type": "boolean", "description": "Recurse into subdirectories"},
                "pattern": {"type": "string", "description": "Glob pattern filter"}
            },
            required=[],
            returns={"type": "array", "items": {"type": "string"}}
        )
        def list_directory(
            path: str = ".",
            recursive: bool = False,
            pattern: str | None = None
        ) -> list[str]:
            full_path = self.work_dir / path
            if not full_path.is_dir():
                raise NotADirectoryError(f"Not a directory: {path}")

            if recursive:
                if pattern:
                    files = list(full_path.rglob(pattern))
                else:
                    files = list(full_path.rglob("*"))
            else:
                if pattern:
                    files = list(full_path.glob(pattern))
                else:
                    files = list(full_path.iterdir())

            return [str(f.relative_to(self.work_dir)) for f in files if f.is_file()]

        @self.register(
            name="search_code",
            description="Search for pattern in files",
            parameters={
                "pattern": {"type": "string", "description": "Regex pattern to search"},
                "path": {"type": "string", "description": "Directory to search in"},
                "file_pattern": {"type": "string", "description": "File glob pattern"},
                "max_results": {"type": "integer", "description": "Maximum results"}
            },
            required=["pattern"],
            returns={"type": "array", "items": {"type": "object"}}
        )
        def search_code(
            pattern: str,
            path: str = ".",
            file_pattern: str = "*.py",
            max_results: int = 50
        ) -> list[dict]:
            full_path = self.work_dir / path
            regex = re.compile(pattern)
            results = []

            for file_path in full_path.rglob(file_pattern):
                if len(results) >= max_results:
                    break
                if not file_path.is_file():
                    continue
                try:
                    content = file_path.read_text()
                    for i, line in enumerate(content.split("\n"), 1):
                        if regex.search(line):
                            results.append({
                                "file": str(file_path.relative_to(self.work_dir)),
                                "line": i,
                                "content": line.strip()
                            })
                            if len(results) >= max_results:
                                break
                except (UnicodeDecodeError, PermissionError):
                    continue

            return results

        @self.register(
            name="find_definition",
            description="Find function/class definition using AST",
            parameters={
                "name": {"type": "string", "description": "Name to find"},
                "path": {"type": "string", "description": "Directory to search"}
            },
            required=["name"],
            returns={"type": "array", "items": {"type": "object"}}
        )
        def find_definition(name: str, path: str = ".") -> list[dict]:
            full_path = self.work_dir / path
            results = []

            for file_path in full_path.rglob("*.py"):
                try:
                    content = file_path.read_text()
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if node.name == name:
                                results.append({
                                    "file": str(file_path.relative_to(self.work_dir)),
                                    "line": node.lineno,
                                    "type": "function",
                                    "name": node.name
                                })
                        elif isinstance(node, ast.ClassDef):
                            if node.name == name:
                                results.append({
                                    "file": str(file_path.relative_to(self.work_dir)),
                                    "line": node.lineno,
                                    "type": "class",
                                    "name": node.name
                                })
                except (SyntaxError, UnicodeDecodeError):
                    continue

            return results

        @self.register(
            name="run_command",
            description="Execute a shell command",
            parameters={
                "command": {"type": "string", "description": "Command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
                "cwd": {"type": "string", "description": "Working directory"}
            },
            required=["command"],
            returns={"type": "object", "properties": {
                "returncode": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"}
            }}
        )
        def run_command(
            command: str,
            timeout: int = 60,
            cwd: str | None = None
        ) -> dict:
            work_cwd = self.work_dir / cwd if cwd else self.work_dir
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_cwd
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }

        @self.register(
            name="git_diff",
            description="Get git diff for changes",
            parameters={
                "path": {"type": "string", "description": "File or directory path"},
                "staged": {"type": "boolean", "description": "Show staged changes only"}
            },
            required=[],
            returns={"type": "string", "description": "Diff output"}
        )
        def git_diff(path: str = ".", staged: bool = False) -> str:
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--staged")
            cmd.append(path)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.work_dir
            )
            return result.stdout

        @self.register(
            name="git_commit",
            description="Create a git commit",
            parameters={
                "message": {"type": "string", "description": "Commit message"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to commit"}
            },
            required=["message"],
            returns={"type": "boolean", "description": "Success status"}
        )
        def git_commit(message: str, files: list[str] | None = None) -> bool:
            if files:
                for f in files:
                    subprocess.run(["git", "add", f], cwd=self.work_dir, check=True)
            else:
                subprocess.run(["git", "add", "-A"], cwd=self.work_dir, check=True)

            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.work_dir,
                capture_output=True,
                text=True
            )
            return result.returncode == 0

        @self.register(
            name="get_repo_structure",
            description="Get repository file structure",
            parameters={
                "max_depth": {"type": "integer", "description": "Maximum directory depth"},
                "exclude_patterns": {"type": "array", "items": {"type": "string"}}
            },
            required=[],
            returns={"type": "string", "description": "Tree structure"}
        )
        def get_repo_structure(
            max_depth: int = 3,
            exclude_patterns: list[str] | None = None
        ) -> str:
            excludes = exclude_patterns or [
                "__pycache__", ".git", "node_modules", ".venv", "venv",
                "*.pyc", "*.pyo", ".pytest_cache", ".mypy_cache"
            ]

            def should_exclude(path: Path) -> bool:
                for pattern in excludes:
                    if pattern.startswith("*"):
                        if path.name.endswith(pattern[1:]):
                            return True
                    elif path.name == pattern:
                        return True
                return False

            def build_tree(dir_path: Path, prefix: str = "", depth: int = 0) -> list[str]:
                if depth > max_depth:
                    return []

                lines = []
                try:
                    entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name))
                except PermissionError:
                    return []

                entries = [e for e in entries if not should_exclude(e)]

                for i, entry in enumerate(entries):
                    is_last = i == len(entries) - 1
                    connector = "└── " if is_last else "├── "
                    lines.append(f"{prefix}{connector}{entry.name}")

                    if entry.is_dir():
                        extension = "    " if is_last else "│   "
                        lines.extend(build_tree(entry, prefix + extension, depth + 1))

                return lines

            tree_lines = [str(self.work_dir.name) + "/"]
            tree_lines.extend(build_tree(self.work_dir))
            return "\n".join(tree_lines)
