"""
Tool Registry component - registers and calls tools with proper schemas
"""

import importlib
import inspect
from typing import Dict, Any, Callable, Optional, Type
from dataclasses import dataclass
from abc import ABC, abstractmethod
import importlib
import inspect
import hashlib
import os
import json
import shutil
import tempfile
import subprocess
import time
import glob



@dataclass
class ToolSchema:
    """Schema defining a tool's input and output"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]


class Tool(ABC):
    """Abstract base class for all tools"""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema"""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute the tool with given parameters"""
        pass


class ToolRegistry:
    """
    Registers and manages all available tools
    Supports dynamic loading and execution
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._schemas: Dict[str, ToolSchema] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        """Register all built-in tools"""
        # File operations
        self.register_tool(ReadFileTool())
        self.register_tool(WriteFileTool())
        self.register_tool(EditFileTool())
        self.register_tool(SearchFilesTool())

        # Code execution
        self.register_tool(CommandExecutionTool())

        # Code search
        self.register_tool(GrepTool())
        self.register_tool(GlobTool())

    def register_tool(self, tool: Tool):
        """Register a tool in the registry"""
        self._tools[tool.schema.name] = tool
        self._schemas[tool.schema.name] = tool.schema

    def unregister_tool(self, tool_name: str):
        """Remove a tool from the registry"""
        if tool_name in self._tools:
            del self._tools[tool_name]
            del self._schemas[tool_name]

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self._tools.get(tool_name)

    def get_tool_schema(self, tool_name: str) -> Optional[ToolSchema]:
        """Get a tool's schema by name"""
        return self._schemas.get(tool_name)

    def list_tools(self) -> Dict[str, ToolSchema]:
        """List all registered tools and their schemas"""
        return self._schemas.copy()
    def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Execute a tool by name with given parameters"""
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found in registry")

        # Validate input against schema
        self._validate_input(tool.schema.input_schema, kwargs)

        # Execute the tool
        result = tool.execute(**kwargs)

        # Validate output against schema
        self._validate_output(tool.schema.output_schema, result)

        return result

    def _validate_input(self, input_schema: Dict[str, Any], kwargs: Dict[str, Any]):
        """Validate tool input against schema"""
        # Simple validation - in real implementation would use jsonschema
        required = input_schema.get("required", [])
        for param in required:
            if param not in kwargs:
                raise ValueError(f"Missing required parameter: {param}")

    def _validate_output(self, output_schema: Dict[str, Any], result: Dict[str, Any]):
        """Validate tool output against schema"""
        # Simple validation - in real implementation would use jsonschema
        if "type" in output_schema and output_schema["type"] == "object":
            if not isinstance(result, dict):
                raise ValueError(f"Expected dict output, got {type(result)}")


# Concrete tool implementations

class ReadFileTool(Tool):
    """Tool to read file contents"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_file",
            description="Read the contents of a file",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to file"},
                    "offset": {"type": "integer", "description": "Line offset to start reading from", "default": 0},
                    "limit": {"type": "integer", "description": "Number of lines to read", "default": 100}
                },
                "required": ["file_path"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "File content"},
                    "lines_read": {"type": "integer", "description": "Number of lines read"},
                    "file_size": {"type": "integer", "description": "Total file size in bytes"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        file_path = kwargs["file_path"]
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)

        with open(file_path, 'r') as f:
            lines = f.readlines()
            content = ''.join(lines[offset:offset + limit])
            return {
                "content": content,
                "lines_read": len(lines[offset:offset + limit]),
                "file_size": sum(1 for _ in lines)
            }


class WriteFileTool(Tool):
    """Tool to write content to a file"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="write_file",
            description="Write content to a file",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to file"},
                    "content": {"type": "string", "description": "Content to write"},
                    "append": {"type": "boolean", "description": "Append to file instead of overwriting", "default": False}
                },
                "required": ["file_path", "content"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Whether write succeeded"},
                    "bytes_written": {"type": "integer", "description": "Number of bytes written"},
                    "file_path": {"type": "string", "description": "Path to the written file"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        file_path = kwargs["file_path"]
        content = kwargs["content"]
        append = kwargs.get("append", False)

        mode = 'a' if append else 'w'
        with open(file_path, mode) as f:
            bytes_written = f.write(content)
            return {
                "success": True,
                "bytes_written": bytes_written,
                "file_path": file_path
            }


class EditFileTool(Tool):
    """Tool to edit file content with string replacement"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="edit_file",
            description="Edit file content by replacing exact strings",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to file"},
                    "old_string": {"type": "string", "description": "Text to replace"},
                    "new_string": {"type": "string", "description": "Text to replace with"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences", "default": False}
                },
                "required": ["file_path", "old_string", "new_string"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Whether edit succeeded"},
                    "replacements": {"type": "integer", "description": "Number of replacements made"},
                    "file_path": {"type": "string", "description": "Path to the edited file"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        file_path = kwargs["file_path"]
        old_string = kwargs["old_string"]
        new_string = kwargs["new_string"]
        replace_all = kwargs.get("replace_all", False)

        with open(file_path, 'r') as f:
            content = f.read()

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1 if old_string in content else 0

        with open(file_path, 'w') as f:
            f.write(new_content)

        return {
            "success": replacements > 0,
            "replacements": replacements,
            "file_path": file_path
        }


class SearchFilesTool(Tool):
    """Tool to search for files matching a pattern"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="search_files",
            description="Search for files matching a glob pattern",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match files"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "./"}
                },
                "required": ["pattern"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "List of matching files"},
                    "count": {"type": "integer", "description": "Number of files found"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        import glob
        pattern = kwargs["pattern"]
        path = kwargs.get("path", "./")

        search_path = f"{path}/{pattern}" if path else pattern
        files = glob.glob(search_path, recursive=True)
        return {
            "files": files,
            "count": len(files)
        }


class CommandExecutionTool(Tool):
    """Tool to execute shell commands"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="execute_command",
            description="Execute a shell command and return output",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "cwd": {"type": "string", "description": "Working directory", "default": "./"},
                    "timeout": {"type": "integer", "description": "Command timeout in seconds", "default": 60}
                },
                "required": ["command"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "stdout": {"type": "string", "description": "Command standard output"},
                    "stderr": {"type": "string", "description": "Command standard error"},
                    "returncode": {"type": "integer", "description": "Command exit code"},
                    "execution_time": {"type": "number", "description": "Time taken to execute in seconds"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        import subprocess
        import time

        command = kwargs["command"]
        cwd = kwargs.get("cwd", "./")
        timeout = kwargs.get("timeout", 60)

        start_time = time.time()
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        execution_time = time.time() - start_time

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "execution_time": execution_time
        }


class GrepTool(Tool):
    """Tool to search file contents with grep"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="grep",
            description="Search file contents for a pattern",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Pattern to search for"},
                    "path": {"type": "string", "description": "File or directory to search in", "default": "./"},
                    "glob": {"type": "string", "description": "Glob pattern to filter files", "default": "*"}
                },
                "required": ["pattern"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "matches": {"type": "array", "items": {"type": "string"}, "description": "List of matching lines"},
                    "files_matched": {"type": "array", "items": {"type": "string"}, "description": "List of files with matches"},
                    "count": {"type": "integer", "description": "Total number of matches"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        import subprocess
        import shlex

        pattern = kwargs["pattern"]
        path = kwargs.get("path", "./")
        file_glob = kwargs.get("glob", "*")

        command = f"grep -r {shlex.quote(pattern)} {shlex.quote(path)} --include={shlex.quote(file_glob)}"
        result = subprocess.run(command, shell=True, capture_output=True, text=True)

        matches = result.stdout.split('\n')[:-1]  # Remove empty last line
        files_matched = list({line.split(':', 1)[0] for line in matches if ':' in line})

        return {
            "matches": matches,
            "files_matched": files_matched,
            "count": len(matches)
        }


class GlobTool(Tool):
    """Tool to find files matching glob patterns"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="glob",
            description="Find files matching glob patterns",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match"},
                    "path": {"type": "string", "description": "Base directory", "default": "./"}
                },
                "required": ["pattern"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Matching file paths"},
                    "count": {"type": "integer", "description": "Number of files found"}
                }
            }
        )

    def execute(self, **kwargs) -> Dict[str, Any]:
        import glob
        import os

        pattern = kwargs["pattern"]
        path = kwargs.get("path", "./")

        full_pattern = os.path.join(path, pattern)
        files = glob.glob(full_pattern, recursive=True)

        return {
            "files": files,
            "count": len(files)
        }