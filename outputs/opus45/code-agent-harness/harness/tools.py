"""
T component - Tool Registry and Tool base class.

Provides:
- Abstract Tool base class with Pydantic schema validation
- ToolRegistry for registration and lookup
- Structured exceptions for tool failures
"""

from abc import ABC, abstractmethod
from typing import Any, Type, TypeVar, Generic
from pydantic import BaseModel, ValidationError
import time

from harness.schemas import ToolCall


class ToolError(Exception):
    """Base exception for tool failures."""

    def __init__(self, tool_name: str, message: str, details: dict | None = None):
        self.tool_name = tool_name
        self.message = message
        self.details = details or {}
        super().__init__(f"{tool_name}: {message}")


class ToolInputError(ToolError):
    """Invalid tool input."""
    pass


class ToolExecutionError(ToolError):
    """Tool execution failed."""
    pass


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class Tool(ABC, Generic[InputT, OutputT]):
    """
    Abstract base class for all tools.

    Each tool defines:
    - name: Unique identifier
    - description: What the tool does
    - input_schema: Pydantic model for inputs
    - output_schema: Pydantic model for outputs
    - execute(): Implementation logic
    """

    name: str
    description: str
    input_schema: Type[InputT]
    output_schema: Type[OutputT]

    def __init__(self) -> None:
        if not hasattr(self, "name"):
            raise ValueError("Tool must define 'name'")
        if not hasattr(self, "input_schema"):
            raise ValueError(f"Tool {self.name} must define 'input_schema'")
        if not hasattr(self, "output_schema"):
            raise ValueError(f"Tool {self.name} must define 'output_schema'")

    def validate_input(self, raw_input: dict) -> InputT:
        """Validate and parse raw input."""
        try:
            return self.input_schema(**raw_input)
        except ValidationError as e:
            raise ToolInputError(
                self.name,
                f"Invalid input: {e}",
                {"validation_errors": e.errors()},
            )

    def validate_output(self, raw_output: Any) -> OutputT:
        """Validate output matches schema."""
        if isinstance(raw_output, self.output_schema):
            return raw_output
        try:
            return self.output_schema(**raw_output)
        except ValidationError as e:
            raise ToolExecutionError(
                self.name,
                f"Invalid output: {e}",
                {"validation_errors": e.errors()},
            )

    @abstractmethod
    def execute(self, input_data: InputT) -> OutputT:
        """Execute the tool with validated input."""
        pass

    def run(self, raw_input: dict) -> tuple[OutputT, ToolCall]:
        """
        Full execution pipeline with validation and recording.

        Returns (result, tool_call_record).
        """
        start_time = time.time()
        try:
            validated_input = self.validate_input(raw_input)
            result = self.execute(validated_input)
            validated_output = self.validate_output(result)
            duration_ms = (time.time() - start_time) * 1000

            tool_call = ToolCall(
                tool_name=self.name,
                inputs=raw_input,
                outputs=validated_output.model_dump(),
                duration_ms=duration_ms,
                success=True,
                error=None,
            )
            return validated_output, tool_call

        except (ToolInputError, ToolExecutionError) as e:
            duration_ms = (time.time() - start_time) * 1000
            tool_call = ToolCall(
                tool_name=self.name,
                inputs=raw_input,
                outputs={},
                duration_ms=duration_ms,
                success=False,
                error=str(e),
            )
            raise e from None

    def get_schema(self) -> dict:
        """Get tool schema for LLM function calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema.model_json_schema(),
        }


class ToolRegistry:
    """
    Registry for tool management.

    Provides registration, lookup, and schema export.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Get a tool by name."""
        if name not in self._tools:
            raise ToolError(name, f"Tool '{name}' not found")
        return self._tools[name]

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_all_schemas(self) -> list[dict]:
        """Get schemas for all tools (for LLM function calling)."""
        return [tool.get_schema() for tool in self._tools.values()]

    def run_tool(self, name: str, inputs: dict) -> tuple[Any, ToolCall]:
        """Run a tool by name with inputs."""
        tool = self.get(name)
        return tool.run(inputs)
