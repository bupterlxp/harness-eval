"""Tool Registry — tool registration and dispatch with input/output schemas.

Provides a registry of tools the agent can invoke, along with schema
definitions for validation and LLM function-calling integration.
"""

import ast
import io
import os
import sys
import time
import signal
import traceback
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt


@dataclass
class ToolSchema:
    """Schema definition for a tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    returns: dict[str, Any]


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: str
    error: str | None = None
    artifacts: list[str] = field(default_factory=list)  # Paths to generated files
    execution_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxNamespace:
    """Persistent Python namespace for code execution.

    All variables, DataFrames, and intermediate results persist across steps.
    """

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir
        self._namespace: dict[str, Any] = {
            "__builtins__": __builtins__,
        }
        # Pre-import common libraries into namespace
        self._setup_imports()

    def _setup_imports(self) -> None:
        """Pre-import commonly used libraries."""
        setup_code = """
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import json
import os
import warnings
warnings.filterwarnings('ignore')
"""
        try:
            exec(setup_code, self._namespace)
        except ImportError:
            pass

    @property
    def namespace(self) -> dict[str, Any]:
        return self._namespace

    def get_variable_names(self) -> list[str]:
        """Get list of user-defined variable names in namespace."""
        skip = {"__builtins__", "pd", "np", "plt", "sns", "Path", "json", "os", "warnings", "matplotlib"}
        return [k for k in self._namespace.keys() if k not in skip and not k.startswith("_")]

    def get_dataframe_summaries(self) -> list[dict[str, Any]]:
        """Get summaries of all DataFrames in namespace."""
        import pandas as pd

        summaries = []
        for name, val in self._namespace.items():
            if isinstance(val, pd.DataFrame) and not name.startswith("_"):
                summaries.append({
                    "name": name,
                    "shape": val.shape,
                    "columns": list(val.columns),
                    "dtypes": {col: str(dtype) for col, dtype in val.dtypes.items()},
                    "memory_mb": round(val.memory_usage(deep=True).sum() / 1024 / 1024, 2),
                })
        return summaries


class TimeoutError(Exception):
    pass


def _timeout_handler(signum: int, frame: Any) -> None:
    raise TimeoutError("Code execution timed out")


class ToolRegistry:
    """Registry and dispatcher for all available tools.

    Tools:
      - execute_python: Run Python code in persistent namespace
      - execute_sql: Run SQL queries (via pandas/sqlite)
      - discover_data: Auto-discover data files in working directory
      - read_file: Read file contents
      - write_file: Write content to a file
      - list_files: List files in directory
    """

    def __init__(self, work_dir: Path, output_dir: Path) -> None:
        self.work_dir = work_dir
        self.output_dir = output_dir
        self.sandbox = SandboxNamespace(work_dir)
        self._tools: dict[str, Callable[..., ToolResult]] = {}
        self._schemas: dict[str, ToolSchema] = {}
        self._artifacts: list[dict[str, Any]] = []

        # Register built-in tools
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register all built-in tools."""
        self.register(
            name="execute_python",
            func=self._execute_python,
            schema=ToolSchema(
                name="execute_python",
                description="Execute Python code in a persistent namespace. All variables persist across calls. Use for data loading, analysis, computation, and visualization.",
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code to execute",
                        }
                    },
                    "required": ["code"],
                },
                returns={
                    "type": "object",
                    "properties": {
                        "output": {"type": "string"},
                        "artifacts": {"type": "array", "items": {"type": "string"}},
                    },
                },
            ),
        )

        self.register(
            name="discover_data",
            func=self._discover_data,
            schema=ToolSchema(
                name="discover_data",
                description="Auto-discover data files in the working directory. Returns file paths, sizes, and inferred types.",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Directory to scan (default: working directory)",
                        }
                    },
                },
                returns={
                    "type": "object",
                    "properties": {
                        "files": {"type": "array"},
                    },
                },
            ),
        )

        self.register(
            name="read_file",
            func=self._read_file,
            schema=ToolSchema(
                name="read_file",
                description="Read the contents of a file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to read"},
                        "max_lines": {"type": "integer", "description": "Maximum lines to read (default: 100)"},
                    },
                    "required": ["path"],
                },
                returns={"type": "object", "properties": {"content": {"type": "string"}}},
            ),
        )

        self.register(
            name="write_file",
            func=self._write_file,
            schema=ToolSchema(
                name="write_file",
                description="Write content to a file in the output directory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path relative to output directory"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
                returns={"type": "object", "properties": {"path": {"type": "string"}}},
            ),
        )

        self.register(
            name="list_files",
            func=self._list_files,
            schema=ToolSchema(
                name="list_files",
                description="List files in a directory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Directory path"},
                        "pattern": {"type": "string", "description": "Glob pattern (default: *)"},
                    },
                },
                returns={"type": "object", "properties": {"files": {"type": "array"}}},
            ),
        )

    def register(self, name: str, func: Callable[..., ToolResult], schema: ToolSchema) -> None:
        """Register a new tool."""
        self._tools[name] = func
        self._schemas[name] = schema

    def dispatch(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Dispatch a tool call by name."""
        if tool_name not in self._tools:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {tool_name}. Available: {list(self._tools.keys())}",
            )
        start = time.time()
        try:
            result = self._tools[tool_name](**kwargs)
        except Exception as e:
            result = ToolResult(
                success=False,
                output="",
                error=f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
            )
        result.execution_time_ms = int((time.time() - start) * 1000)
        return result

    def get_tool_schemas_for_llm(self) -> list[dict[str, Any]]:
        """Get tool schemas formatted for OpenAI function calling."""
        functions = []
        for name, schema in self._schemas.items():
            functions.append({
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": schema.parameters,
                },
            })
        return functions

    def get_artifacts(self) -> list[dict[str, Any]]:
        """Get all registered artifacts."""
        return self._artifacts.copy()

    def _register_artifact(self, artifact: dict[str, Any]) -> None:
        """Register a new artifact."""
        self._artifacts.append(artifact)

    # --- Tool Implementations ---

    def _execute_python(self, code: str, timeout: int = 60) -> ToolResult:
        """Execute Python code in the persistent sandbox namespace.

        Features:
          - Persistent namespace (variables survive across calls)
          - Captures stdout/stderr
          - Detects and saves matplotlib figures
          - Timeout protection
          - Memory limit awareness
        """
        # Syntax check
        try:
            ast.parse(code)
        except SyntaxError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"SyntaxError: {e}",
            )

        # Set working directory in namespace
        self.sandbox.namespace["__work_dir__"] = str(self.work_dir)
        self.sandbox.namespace["__output_dir__"] = str(self.output_dir)

        # Capture output
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        artifacts: list[str] = []

        # Close any existing figures before execution
        plt.close("all")

        # Change to work directory for relative paths
        original_dir = os.getcwd()
        os.chdir(self.work_dir)

        try:
            # Set timeout (Unix only; on Windows this is a no-op)
            if hasattr(signal, "SIGALRM"):
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(timeout)

            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, self.sandbox.namespace)

            # Cancel timeout
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        except TimeoutError:
            os.chdir(original_dir)
            return ToolResult(
                success=False,
                output=stdout_buf.getvalue(),
                error=f"Execution timed out after {timeout} seconds",
            )
        except Exception as e:
            os.chdir(original_dir)
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)
            tb = traceback.format_exc()
            return ToolResult(
                success=False,
                output=stdout_buf.getvalue(),
                error=f"{type(e).__name__}: {str(e)}\n{tb}",
            )
        finally:
            os.chdir(original_dir)

        # Check for matplotlib figures and save them
        fig_nums = plt.get_fignums()
        for fig_num in fig_nums:
            fig = plt.figure(fig_num)
            fig_name = f"figure_{len(self._artifacts) + len(artifacts) + 1}.png"
            fig_path = self.output_dir / fig_name
            fig.savefig(fig_path, dpi=150, bbox_inches="tight")
            artifacts.append(str(fig_path))
            self._register_artifact({
                "type": "chart",
                "path": str(fig_path),
                "name": fig_name,
            })
        plt.close("all")

        stdout_output = stdout_buf.getvalue()
        stderr_output = stderr_buf.getvalue()

        # Truncate very long outputs
        max_output_len = 5000
        if len(stdout_output) > max_output_len:
            stdout_output = stdout_output[:max_output_len] + f"\n... [truncated, total {len(stdout_buf.getvalue())} chars]"

        combined_output = stdout_output
        if stderr_output:
            combined_output += f"\n[stderr]: {stderr_output[:1000]}"

        # Register DataFrame artifacts
        for summary in self.sandbox.get_dataframe_summaries():
            existing_names = {a.get("name") for a in self._artifacts}
            if summary["name"] not in existing_names:
                self._register_artifact({
                    "type": "dataframe",
                    "name": summary["name"],
                    "shape": summary["shape"],
                    "columns": summary["columns"],
                    "dtypes": summary["dtypes"],
                    "memory_mb": summary["memory_mb"],
                })

        return ToolResult(
            success=True,
            output=combined_output if combined_output else "(no output)",
            artifacts=artifacts,
            metadata={
                "namespace_vars": self.sandbox.get_variable_names(),
                "dataframes": self.sandbox.get_dataframe_summaries(),
            },
        )

    def _discover_data(self, directory: str | None = None) -> ToolResult:
        """Auto-discover data files in working directory."""
        scan_dir = Path(directory) if directory else self.work_dir

        data_extensions = {
            ".csv": "CSV",
            ".xlsx": "Excel",
            ".xls": "Excel",
            ".parquet": "Parquet",
            ".json": "JSON",
            ".jsonl": "JSON Lines",
            ".tsv": "TSV",
            ".sql": "SQL",
            ".db": "SQLite Database",
            ".sqlite": "SQLite Database",
        }

        found_files: list[dict[str, Any]] = []
        for ext, file_type in data_extensions.items():
            for file_path in scan_dir.rglob(f"*{ext}"):
                stat = file_path.stat()
                found_files.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "type": file_type,
                    "size_bytes": stat.st_size,
                    "size_human": self._human_size(stat.st_size),
                })

        # Also check for markdown/text files that might be task specs
        for ext in [".md", ".txt"]:
            for file_path in scan_dir.rglob(f"*{ext}"):
                stat = file_path.stat()
                found_files.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "type": "Text/Markdown",
                    "size_bytes": stat.st_size,
                    "size_human": self._human_size(stat.st_size),
                })

        output_lines = [f"Found {len(found_files)} data files in {scan_dir}:\n"]
        for f in found_files:
            output_lines.append(f"  - {f['name']} ({f['type']}, {f['size_human']})")

        return ToolResult(
            success=True,
            output="\n".join(output_lines),
            metadata={"files": found_files},
        )

    def _read_file(self, path: str, max_lines: int = 100) -> ToolResult:
        """Read file contents."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.work_dir / file_path

        if not file_path.exists():
            return ToolResult(success=False, output="", error=f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            content = "".join(lines[:max_lines])
            if len(lines) > max_lines:
                content += f"\n... [{len(lines) - max_lines} more lines]"
            return ToolResult(success=True, output=content)
        except UnicodeDecodeError:
            return ToolResult(success=True, output=f"[Binary file: {file_path.name}, {self._human_size(file_path.stat().st_size)}]")

    def _write_file(self, path: str, content: str) -> ToolResult:
        """Write content to a file."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.output_dir / file_path

        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        self._register_artifact({
            "type": "file",
            "path": str(file_path),
            "name": file_path.name,
        })

        return ToolResult(success=True, output=f"Written to {file_path}")

    def _list_files(self, directory: str | None = None, pattern: str = "*") -> ToolResult:
        """List files in directory."""
        scan_dir = Path(directory) if directory else self.work_dir

        if not scan_dir.exists():
            return ToolResult(success=False, output="", error=f"Directory not found: {scan_dir}")

        files = sorted(scan_dir.glob(pattern))
        output_lines = [f"Files in {scan_dir} (pattern: {pattern}):\n"]
        for f in files[:100]:  # Limit to 100 entries
            prefix = "d" if f.is_dir() else "f"
            size = self._human_size(f.stat().st_size) if f.is_file() else ""
            output_lines.append(f"  [{prefix}] {f.name} {size}")

        if len(files) > 100:
            output_lines.append(f"  ... and {len(files) - 100} more")

        return ToolResult(success=True, output="\n".join(output_lines))

    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Convert bytes to human-readable size."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"
