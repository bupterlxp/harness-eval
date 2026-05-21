"""Tool Registry — tool registration and dispatch with input/output schemas."""

from __future__ import annotations

import ast
import glob
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class ToolSchema:
    """Schema definition for a tool's input and output."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for parameters
    returns: dict[str, Any] = field(default_factory=lambda: {"type": "string"})


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    output: str
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Registry for tool functions with schema validation and dispatch."""

    def __init__(self, workspace: Path | str = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self._tools: dict[str, Callable[..., ToolResult]] = {}
        self._schemas: dict[str, ToolSchema] = {}

    def register(self, schema: ToolSchema, func: Callable[..., ToolResult]) -> None:
        """Register a tool with its schema and implementation."""
        self._tools[schema.name] = func
        self._schemas[schema.name] = schema

    def get_tool_names(self) -> list[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())

    def get_schema(self, name: str) -> ToolSchema | None:
        """Get the schema for a tool."""
        return self._schemas.get(name)

    def get_all_schemas(self) -> list[ToolSchema]:
        """Get all tool schemas for LLM function calling."""
        return list(self._schemas.values())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI function-calling format."""
        tools = []
        for schema in self._schemas.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": schema.parameters,
                },
            })
        return tools

    def dispatch(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Dispatch a tool call by name with arguments."""
        if name not in self._tools:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: '{name}'. Available tools: {', '.join(self._tools.keys())}",
            )
        try:
            return self._tools[name](**arguments)
        except TypeError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid arguments for tool '{name}': {e}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' execution failed: {type(e).__name__}: {e}",
            )


def register_default_tools(registry: ToolRegistry, workspace: Path | str = ".") -> None:
    """Register the default set of code agent tools."""
    workspace = Path(workspace).resolve()

    # ─── File Tree / Glob ───────────────────────────────────────────────
    def find_files(pattern: str, path: str = ".") -> ToolResult:
        """Find files matching a glob pattern relative to workspace."""
        search_path = workspace / path
        if not search_path.is_relative_to(workspace):
            return ToolResult(success=False, output="", error="Path escapes workspace")
        try:
            matches = sorted(glob.glob(pattern, root_dir=str(search_path), recursive=True))
            if not matches:
                return ToolResult(success=True, output="No files found matching pattern.")
            output = "\n".join(matches[:200])
            if len(matches) > 200:
                output += f"\n... and {len(matches) - 200} more files"
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="find_files",
            description="Find files matching a glob pattern in the workspace. Supports ** for recursive search.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.py')"},
                    "path": {"type": "string", "description": "Subdirectory to search in (relative to workspace)", "default": "."},
                },
                "required": ["pattern"],
            },
        ),
        find_files,
    )

    # ─── Grep ───────────────────────────────────────────────────────────
    def grep(pattern: str, path: str = ".", include: str = "", max_results: int = 50) -> ToolResult:
        """Search file contents with regex."""
        search_path = workspace / path
        if not search_path.resolve().is_relative_to(workspace):
            return ToolResult(success=False, output="", error="Path escapes workspace")

        cmd = ["grep", "-rn", "--include", include if include else "*", "-E", pattern, str(search_path)]
        if not include:
            cmd = ["grep", "-rn", "-E", pattern, str(search_path)]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, cwd=str(workspace)
            )
            lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
            if not lines:
                return ToolResult(success=True, output="No matches found.")
            # Make paths relative to workspace
            rel_lines = []
            for line in lines[:max_results]:
                rel_lines.append(line.replace(str(workspace) + "/", ""))
            output = "\n".join(rel_lines)
            if len(lines) > max_results:
                output += f"\n... and {len(lines) - max_results} more matches"
            return ToolResult(success=True, output=output)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="Grep timed out after 30s")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="grep",
            description="Search file contents using regex. Returns matching lines with file path and line number.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in (relative to workspace)", "default": "."},
                    "include": {"type": "string", "description": "File pattern to include (e.g., '*.py')", "default": ""},
                    "max_results": {"type": "integer", "description": "Maximum results to return", "default": 50},
                },
                "required": ["pattern"],
            },
        ),
        grep,
    )

    # ─── Read File ──────────────────────────────────────────────────────
    def read_file(path: str, start_line: int = 1, end_line: int = -1) -> ToolResult:
        """Read file contents with optional line range."""
        file_path = workspace / path
        if not file_path.resolve().is_relative_to(workspace):
            return ToolResult(success=False, output="", error="Path escapes workspace")
        if not file_path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {path}")

        try:
            with open(file_path, "r", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            start = max(0, start_line - 1)
            end = total_lines if end_line == -1 else min(end_line, total_lines)

            selected = lines[start:end]
            numbered = []
            for i, line in enumerate(selected, start=start + 1):
                numbered.append(f"{i:>4}| {line.rstrip()}")

            output = f"[File: {path} | Lines: {start + 1}-{end} of {total_lines}]\n"
            output += "\n".join(numbered)
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="read_file",
            description="Read a file's contents. Optionally specify a line range. Returns numbered lines.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"},
                    "start_line": {"type": "integer", "description": "Starting line number (1-based)", "default": 1},
                    "end_line": {"type": "integer", "description": "Ending line number (-1 for end of file)", "default": -1},
                },
                "required": ["path"],
            },
        ),
        read_file,
    )

    # ─── Write File ─────────────────────────────────────────────────────
    def write_file(path: str, content: str) -> ToolResult:
        """Write content to a file (create or overwrite)."""
        file_path = workspace / path
        if not file_path.resolve().is_relative_to(workspace):
            return ToolResult(success=False, output="", error="Path escapes workspace")

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w") as f:
                f.write(content)
            return ToolResult(
                success=True,
                output=f"File written: {path} ({len(content)} bytes)",
                metadata={"file": path},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="write_file",
            description="Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        ),
        write_file,
    )

    # ─── String Replace (Edit) ──────────────────────────────────────────
    def str_replace(path: str, old_string: str, new_string: str) -> ToolResult:
        """Replace an exact string in a file. The old_string must appear exactly once."""
        file_path = workspace / path
        if not file_path.resolve().is_relative_to(workspace):
            return ToolResult(success=False, output="", error="Path escapes workspace")
        if not file_path.is_file():
            return ToolResult(success=False, output="", error=f"File not found: {path}")

        try:
            with open(file_path, "r") as f:
                content = f.read()

            count = content.count(old_string)
            if count == 0:
                return ToolResult(
                    success=False, output="", error="old_string not found in file. Ensure exact match including whitespace."
                )
            if count > 1:
                return ToolResult(
                    success=False, output="",
                    error=f"old_string found {count} times. Must be unique. Add surrounding context to disambiguate.",
                )

            new_content = content.replace(old_string, new_string, 1)

            # Syntax check for Python files
            if file_path.suffix == ".py":
                try:
                    ast.parse(new_content)
                except SyntaxError as se:
                    return ToolResult(
                        success=False, output="",
                        error=f"Edit would produce syntax error at line {se.lineno}: {se.msg}. Rollback: no changes written.",
                    )

            with open(file_path, "w") as f:
                f.write(new_content)

            # Run linter check
            lint_msg = _lint_file(file_path)

            output = f"Replaced in {path}."
            if lint_msg:
                output += f"\nLinter warning: {lint_msg}"
            return ToolResult(success=True, output=output, metadata={"file": path})
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="str_replace",
            description="Replace an exact string occurrence in a file. old_string must match exactly once. Auto-checks syntax for Python files.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"},
                    "old_string": {"type": "string", "description": "Exact string to find (must be unique in file)"},
                    "new_string": {"type": "string", "description": "Replacement string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ),
        str_replace,
    )

    # ─── Bash Command ───────────────────────────────────────────────────
    def bash(command: str, timeout: int = 60) -> ToolResult:
        """Run a bash command in the workspace."""
        # Pre-check syntax
        syntax_check = subprocess.run(
            ["bash", "-n", "-c", command],
            capture_output=True, text=True, timeout=5
        )
        if syntax_check.returncode != 0:
            return ToolResult(
                success=False, output="",
                error=f"Bash syntax error: {syntax_check.stderr.strip()}"
            )

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True, text=True,
                timeout=timeout, cwd=str(workspace),
            )
            output = result.stdout
            if result.stderr:
                output += ("\n[stderr]\n" + result.stderr) if output else result.stderr

            return ToolResult(
                success=(result.returncode == 0),
                output=output.strip() if output else "(no output)",
                error="" if result.returncode == 0 else f"Exit code: {result.returncode}",
                metadata={"returncode": result.returncode},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error=f"Command timed out after {timeout}s")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="bash",
            description="Run a bash command in the workspace. Pre-checks syntax. Returns stdout+stderr.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Bash command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
                },
                "required": ["command"],
            },
        ),
        bash,
    )

    # ─── List Directory ─────────────────────────────────────────────────
    def list_dir(path: str = ".", depth: int = 2) -> ToolResult:
        """List directory contents as a tree."""
        dir_path = workspace / path
        if not dir_path.resolve().is_relative_to(workspace):
            return ToolResult(success=False, output="", error="Path escapes workspace")
        if not dir_path.is_dir():
            return ToolResult(success=False, output="", error=f"Not a directory: {path}")

        try:
            lines: list[str] = []
            _tree(dir_path, "", depth, lines, workspace)
            return ToolResult(success=True, output="\n".join(lines) if lines else "(empty directory)")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="list_dir",
            description="List directory contents as a tree structure up to a given depth.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to workspace", "default": "."},
                    "depth": {"type": "integer", "description": "Maximum depth to recurse", "default": 2},
                },
                "required": [],
            },
        ),
        list_dir,
    )

    # ─── Run Tests ──────────────────────────────────────────────────────
    def run_tests(command: str = "", path: str = ".") -> ToolResult:
        """Run tests and capture results."""
        if not command:
            # Auto-detect test framework
            if (workspace / "pytest.ini").exists() or (workspace / "pyproject.toml").exists():
                command = "python -m pytest --tb=short -q"
            elif (workspace / "package.json").exists():
                command = "npm test"
            else:
                command = "python -m pytest --tb=short -q"

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True, text=True,
                timeout=120, cwd=str(workspace / path),
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr

            return ToolResult(
                success=(result.returncode == 0),
                output=output.strip() if output else "(no output)",
                error="" if result.returncode == 0 else f"Tests failed (exit code {result.returncode})",
                metadata={"returncode": result.returncode, "passed": result.returncode == 0},
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="Tests timed out after 120s")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    registry.register(
        ToolSchema(
            name="run_tests",
            description="Run the test suite and capture results. Auto-detects pytest or npm test.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Test command to run (auto-detected if empty)", "default": ""},
                    "path": {"type": "string", "description": "Subdirectory to run tests in", "default": "."},
                },
                "required": [],
            },
        ),
        run_tests,
    )

    # ─── Done (Success Signal) ──────────────────────────────────────────
    def done(summary: str) -> ToolResult:
        """Signal task completion."""
        return ToolResult(
            success=True,
            output=f"TASK_COMPLETE: {summary}",
            metadata={"signal": "done"},
        )

    registry.register(
        ToolSchema(
            name="done",
            description="Signal that the task is complete. Provide a brief summary of what was accomplished.",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Summary of what was accomplished"},
                },
                "required": ["summary"],
            },
        ),
        done,
    )


def _tree(path: Path, prefix: str, depth: int, lines: list[str], workspace: Path) -> None:
    """Recursively build a directory tree."""
    if depth < 0:
        return
    # Skip hidden and common noise directories
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".mypy_cache"}
    try:
        entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return

    dirs = [e for e in entries if e.is_dir() and e.name not in skip_dirs]
    files = [e for e in entries if e.is_file()]

    for f in files[:50]:
        rel = f.relative_to(workspace)
        lines.append(f"{prefix}{rel}")

    if len(files) > 50:
        lines.append(f"{prefix}... and {len(files) - 50} more files")

    for d in dirs[:20]:
        rel = d.relative_to(workspace)
        lines.append(f"{prefix}{rel}/")
        if depth > 0:
            _tree(d, prefix + "  ", depth - 1, lines, workspace)


def _lint_file(file_path: Path) -> str:
    """Run a basic lint check on a file. Returns warning message or empty string."""
    if file_path.suffix == ".py":
        try:
            with open(file_path, "r") as f:
                source = f.read()
            ast.parse(source)
        except SyntaxError as e:
            return f"Python syntax error at line {e.lineno}: {e.msg}"
    elif file_path.suffix in (".sh", ".bash"):
        try:
            result = subprocess.run(
                ["bash", "-n", str(file_path)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return f"Shell syntax error: {result.stderr.strip()}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return ""
