"""Tool Registry (T) - Registration and invocation of tools with schemas."""

from __future__ import annotations

import difflib
import fnmatch
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
    parameters: dict[str, dict[str, Any]]
    required: list[str]


@dataclass
class Tool:
    """A registered tool with schema and implementation."""
    name: str
    description: str
    parameters: dict[str, dict[str, Any]]
    required: list[str]
    handler: Callable[..., dict[str, Any]]

    def validate_input(self, params: dict[str, Any]) -> list[str]:
        """Validate input parameters against schema."""
        errors: list[str] = []

        for req in self.required:
            if req not in params:
                errors.append(f"Missing required parameter: {req}")

        for key, value in params.items():
            if key in self.parameters:
                expected_type = self.parameters[key].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    errors.append(f"Parameter {key} must be string")
                elif expected_type == "integer" and not isinstance(value, int):
                    errors.append(f"Parameter {key} must be integer")
                elif expected_type == "array" and not isinstance(value, list):
                    errors.append(f"Parameter {key} must be array")

        return errors

    def to_schema(self) -> ToolSchema:
        """Export tool as schema dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }


@dataclass
class ToolRegistry:
    """Registry for tools with schema validation."""

    _tools: dict[str, Tool] = field(default_factory=dict)
    _call_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._register_builtin_tools()

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, dict[str, Any]],
        required: list[str],
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        """Register a new tool."""
        self._tools[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            required=required,
            handler=handler,
        )

    def call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by name with parameters."""
        if name not in self._tools:
            return {"error": f"Unknown tool: {name}"}

        tool = self._tools[name]
        errors = tool.validate_input(params)
        if errors:
            return {"error": f"Validation failed: {errors}"}

        try:
            result = tool.handler(**params)
            self._call_history.append({
                "tool": name,
                "params": params,
                "result": result,
            })
            return result
        except Exception as e:
            return {"error": str(e)}

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_schemas(self) -> list[ToolSchema]:
        """Get schemas for all tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    def get_call_history(self) -> list[dict[str, Any]]:
        """Get history of tool calls."""
        return self._call_history.copy()

    def clear_history(self) -> None:
        """Clear call history."""
        self._call_history.clear()

    def _register_builtin_tools(self) -> None:
        """Register built-in tools for code operations."""

        self.register(
            name="read_file",
            description="Read contents of a file",
            parameters={
                "path": {"type": "string", "description": "Path to the file"},
                "max_lines": {"type": "integer", "description": "Maximum lines to read"},
            },
            required=["path"],
            handler=self._read_file,
        )

        self.register(
            name="write_file",
            description="Write content to a file",
            parameters={
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            required=["path", "content"],
            handler=self._write_file,
        )

        self.register(
            name="scan_repo",
            description="Scan repository structure",
            parameters={
                "path": {"type": "string", "description": "Repository root path"},
                "max_depth": {"type": "integer", "description": "Maximum directory depth"},
            },
            required=["path"],
            handler=self._scan_repo,
        )

        self.register(
            name="search_code",
            description="Search for pattern in code files",
            parameters={
                "path": {"type": "string", "description": "Directory to search"},
                "pattern": {"type": "string", "description": "Search pattern (regex)"},
                "file_pattern": {"type": "string", "description": "File glob pattern"},
            },
            required=["path", "pattern"],
            handler=self._search_code,
        )

        self.register(
            name="run_command",
            description="Execute a shell command",
            parameters={
                "command": {"type": "string", "description": "Command to execute"},
                "cwd": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
            },
            required=["command"],
            handler=self._run_command,
        )

        self.register(
            name="generate_diff",
            description="Generate unified diff between two contents",
            parameters={
                "old_content": {"type": "string", "description": "Original content"},
                "new_content": {"type": "string", "description": "New content"},
                "file_path": {"type": "string", "description": "File path for diff header"},
            },
            required=["old_content", "new_content"],
            handler=self._generate_diff,
        )

        self.register(
            name="list_directory",
            description="List contents of a directory",
            parameters={
                "path": {"type": "string", "description": "Directory path"},
                "pattern": {"type": "string", "description": "Glob pattern filter"},
            },
            required=["path"],
            handler=self._list_directory,
        )

        self.register(
            name="find_functions",
            description="Find function definitions in a file",
            parameters={
                "path": {"type": "string", "description": "File path"},
                "language": {"type": "string", "description": "Programming language"},
            },
            required=["path"],
            handler=self._find_functions,
        )

        self.register(
            name="apply_patch",
            description="Apply a unified diff patch to a file",
            parameters={
                "path": {"type": "string", "description": "File path"},
                "patch": {"type": "string", "description": "Unified diff patch"},
            },
            required=["path", "patch"],
            handler=self._apply_patch,
        )

    def _read_file(self, path: str, max_lines: int | None = None) -> dict[str, Any]:
        """Read file contents."""
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"File not found: {path}"}
            if not p.is_file():
                return {"error": f"Not a file: {path}"}

            content = p.read_text(encoding="utf-8", errors="replace")

            if max_lines:
                lines = content.split("\n")
                content = "\n".join(lines[:max_lines])
                truncated = len(lines) > max_lines
            else:
                truncated = False

            return {
                "content": content,
                "size": p.stat().st_size,
                "truncated": truncated,
            }
        except Exception as e:
            return {"error": str(e)}

    def _write_file(self, path: str, content: str) -> dict[str, Any]:
        """Write content to file."""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"success": True, "path": path, "size": len(content)}
        except Exception as e:
            return {"error": str(e)}

    def _scan_repo(self, path: str, max_depth: int = 3) -> dict[str, Any]:
        """Scan repository structure."""
        try:
            root = Path(path)
            if not root.exists():
                return {"error": f"Path not found: {path}"}

            structure: dict[str, Any] = {
                "root": str(root.absolute()),
                "files": [],
                "directories": [],
                "file_count": 0,
                "languages": set(),
            }

            ignore_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".eggs", "dist", "build"}
            ignore_files = {".pyc", ".pyo", ".so", ".dylib"}

            lang_extensions = {
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".java": "java",
                ".go": "go",
                ".rs": "rust",
                ".rb": "ruby",
                ".c": "c",
                ".cpp": "cpp",
                ".h": "c_header",
            }

            def scan_dir(dir_path: Path, depth: int) -> None:
                if depth > max_depth:
                    return

                try:
                    for entry in sorted(dir_path.iterdir()):
                        if entry.name.startswith(".") and entry.name != ".":
                            continue
                        if entry.is_dir():
                            if entry.name in ignore_dirs:
                                continue
                            rel_path = str(entry.relative_to(root))
                            structure["directories"].append(rel_path)
                            scan_dir(entry, depth + 1)
                        elif entry.is_file():
                            if entry.suffix in ignore_files:
                                continue
                            rel_path = str(entry.relative_to(root))
                            structure["files"].append(rel_path)
                            structure["file_count"] += 1
                            if entry.suffix in lang_extensions:
                                structure["languages"].add(lang_extensions[entry.suffix])
                except PermissionError:
                    pass

            scan_dir(root, 0)
            structure["languages"] = list(structure["languages"])

            return structure
        except Exception as e:
            return {"error": str(e)}

    def _search_code(
        self,
        path: str,
        pattern: str,
        file_pattern: str = "*.py",
    ) -> dict[str, Any]:
        """Search for pattern in code files."""
        try:
            root = Path(path)
            if not root.exists():
                return {"error": f"Path not found: {path}"}

            matches: list[dict[str, Any]] = []
            files_searched = 0
            files_matched: set[str] = set()

            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                return {"error": f"Invalid regex: {e}"}

            for fpath in root.rglob("*"):
                if not fpath.is_file():
                    continue
                if not fnmatch.fnmatch(fpath.name, file_pattern):
                    continue
                if any(ignore in fpath.parts for ignore in (".git", "__pycache__", "node_modules")):
                    continue

                files_searched += 1

                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    for line_num, line in enumerate(content.split("\n"), 1):
                        if regex.search(line):
                            rel_path = str(fpath.relative_to(root))
                            files_matched.add(rel_path)
                            matches.append({
                                "file": rel_path,
                                "line": line_num,
                                "content": line.strip()[:200],
                            })
                            if len(matches) >= 100:
                                break
                except Exception:
                    continue

                if len(matches) >= 100:
                    break

            return {
                "matches": matches,
                "files": list(files_matched),
                "files_searched": files_searched,
                "truncated": len(matches) >= 100,
            }
        except Exception as e:
            return {"error": str(e)}

    def _run_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Execute shell command."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out", "exit_code": -1}
        except Exception as e:
            return {"error": str(e), "exit_code": -1}

    def _generate_diff(
        self,
        old_content: str,
        new_content: str,
        file_path: str = "file",
    ) -> dict[str, Any]:
        """Generate unified diff."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )

        return {"diff": "".join(diff)}

    def _list_directory(
        self,
        path: str,
        pattern: str | None = None,
    ) -> dict[str, Any]:
        """List directory contents."""
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"Path not found: {path}"}
            if not p.is_dir():
                return {"error": f"Not a directory: {path}"}

            entries: list[dict[str, Any]] = []
            for entry in sorted(p.iterdir()):
                if pattern and not fnmatch.fnmatch(entry.name, pattern):
                    continue
                entries.append({
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else None,
                })

            return {"entries": entries, "count": len(entries)}
        except Exception as e:
            return {"error": str(e)}

    def _find_functions(
        self,
        path: str,
        language: str = "python",
    ) -> dict[str, Any]:
        """Find function definitions in a file."""
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace")

            functions: list[dict[str, Any]] = []

            if language == "python":
                pattern = r'^(\s*)(async\s+)?def\s+(\w+)\s*\((.*?)\)'
                for match in re.finditer(pattern, content, re.MULTILINE):
                    indent = len(match.group(1))
                    is_async = bool(match.group(2))
                    name = match.group(3)
                    params = match.group(4)
                    line_num = content[:match.start()].count("\n") + 1
                    functions.append({
                        "name": name,
                        "line": line_num,
                        "async": is_async,
                        "params": params[:100],
                        "indent": indent,
                    })
            elif language in ("javascript", "typescript"):
                patterns = [
                    r'function\s+(\w+)\s*\((.*?)\)',
                    r'(\w+)\s*=\s*(?:async\s+)?\((.*?)\)\s*=>',
                    r'(\w+)\s*:\s*(?:async\s+)?function\s*\((.*?)\)',
                ]
                for pat in patterns:
                    for match in re.finditer(pat, content):
                        name = match.group(1)
                        params = match.group(2)
                        line_num = content[:match.start()].count("\n") + 1
                        functions.append({
                            "name": name,
                            "line": line_num,
                            "params": params[:100],
                        })

            return {"functions": functions, "count": len(functions)}
        except Exception as e:
            return {"error": str(e)}

    def _apply_patch(self, path: str, patch: str) -> dict[str, Any]:
        """Apply a unified diff patch."""
        try:
            p = Path(path)
            if not p.exists():
                return {"error": f"File not found: {path}"}

            original = p.read_text(encoding="utf-8")
            lines = original.splitlines(keepends=True)

            patch_lines = patch.splitlines(keepends=True)
            chunks: list[tuple[int, int, list[str]]] = []
            current_chunk: list[str] = []
            start_line = 0
            remove_count = 0

            for line in patch_lines:
                if line.startswith("@@"):
                    if current_chunk:
                        chunks.append((start_line, remove_count, current_chunk))
                        current_chunk = []
                    match = re.match(r'@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@', line)
                    if match:
                        start_line = int(match.group(1)) - 1
                        remove_count = int(match.group(2) or 1)
                elif line.startswith("---") or line.startswith("+++"):
                    continue
                elif line.startswith("-"):
                    pass
                elif line.startswith("+"):
                    current_chunk.append(line[1:])
                elif line.startswith(" "):
                    current_chunk.append(line[1:])

            if current_chunk:
                chunks.append((start_line, remove_count, current_chunk))

            for start, count, new_lines in reversed(chunks):
                lines[start:start + count] = new_lines

            new_content = "".join(lines)
            p.write_text(new_content, encoding="utf-8")

            return {"success": True, "path": path}
        except Exception as e:
            return {"error": str(e)}
