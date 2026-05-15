"""
tools.py - T: Tool Registry with Pydantic schema validation

Provides tool registration, validation, and execution with structured exception handling.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar
from enum import Enum

from pydantic import BaseModel, ValidationError

from harness.schemas import ToolSchema, ToolResult, ToolDangerLevel


class ToolError(Exception):
    """Base exception for tool errors"""
    pass


class ToolNotFoundError(ToolError):
    """Tool not registered"""
    pass


class ToolValidationError(ToolError):
    """Input/output validation failed"""
    def __init__(self, message: str, validation_errors: list[dict] | None = None):
        super().__init__(message)
        self.validation_errors = validation_errors or []


class ToolExecutionError(ToolError):
    """Tool execution failed"""
    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class ToolApprovalRequired(ToolError):
    """Tool requires user approval before execution"""
    def __init__(self, tool_name: str, args: dict[str, Any], reason: str):
        super().__init__(f"Approval required for {tool_name}: {reason}")
        self.tool_name = tool_name
        self.args = args
        self.reason = reason


class ToolErrorCategory(str, Enum):
    """Structured error classification"""
    VALIDATION = "validation"
    EXECUTION = "execution"
    TIMEOUT = "timeout"
    APPROVAL = "approval"
    INTERNAL = "internal"


T = TypeVar("T", bound=BaseModel)


class Tool(ABC):
    """
    Base class for all tools.

    Subclasses must:
    - Define name, description, danger_level
    - Specify input_model and output_model Pydantic classes
    - Implement _execute method
    """

    name: str
    description: str
    danger_level: ToolDangerLevel = ToolDangerLevel.SAFE
    requires_context: bool = False
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    def get_schema(self) -> ToolSchema:
        """Get the tool's schema for registration"""
        return ToolSchema(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
            output_schema=self.output_model.model_json_schema(),
            danger_level=self.danger_level,
            requires_context=self.requires_context
        )

    def validate_input(self, args: dict[str, Any]) -> BaseModel:
        """Validate input against schema"""
        try:
            return self.input_model.model_validate(args)
        except ValidationError as e:
            raise ToolValidationError(
                f"Input validation failed for {self.name}",
                validation_errors=e.errors()
            )

    def validate_output(self, output: Any) -> BaseModel:
        """Validate output against schema"""
        if isinstance(output, self.output_model):
            return output
        try:
            if isinstance(output, dict):
                return self.output_model.model_validate(output)
            return self.output_model.model_validate({"result": output})
        except ValidationError as e:
            raise ToolValidationError(
                f"Output validation failed for {self.name}",
                validation_errors=e.errors()
            )

    @abstractmethod
    def _execute(self, validated_input: BaseModel, context: dict[str, Any] | None = None) -> Any:
        """Execute the tool with validated input"""
        pass

    def execute(
        self,
        args: dict[str, Any],
        context: dict[str, Any] | None = None,
        approved: bool = False
    ) -> ToolResult:
        """
        Execute the tool with full validation and error handling.

        Args:
            args: Tool arguments
            context: Optional context dict (for tools that require_context)
            approved: Whether approval has been given (for dangerous tools)

        Returns:
            ToolResult with success status and output/error
        """
        if self.danger_level == ToolDangerLevel.NEEDS_APPROVAL and not approved:
            raise ToolApprovalRequired(
                self.name,
                args,
                f"Tool {self.name} requires approval before execution"
            )

        try:
            validated_input = self.validate_input(args)
            raw_output = self._execute(validated_input, context)
            validated_output = self.validate_output(raw_output)

            return ToolResult(
                success=True,
                output=validated_output.model_dump(),
                metadata={"tool": self.name}
            )

        except ToolValidationError as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={
                    "tool": self.name,
                    "error_category": ToolErrorCategory.VALIDATION.value,
                    "validation_errors": e.validation_errors
                }
            )
        except ToolExecutionError as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={
                    "tool": self.name,
                    "error_category": ToolErrorCategory.EXECUTION.value
                }
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Internal error: {str(e)}",
                metadata={
                    "tool": self.name,
                    "error_category": ToolErrorCategory.INTERNAL.value,
                    "exception_type": type(e).__name__
                }
            )


class ToolRegistry:
    """
    T component: Registry for all tools with schema validation.

    Provides:
    - Registration with schema validation
    - Lookup by name
    - Listing available tools
    - Schema export for LLM function calling
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._schemas: dict[str, ToolSchema] = {}

    def register(self, tool: Tool) -> None:
        """
        Register a tool with validation.

        Raises ToolValidationError if tool schema is invalid.
        """
        if not hasattr(tool, 'name') or not tool.name:
            raise ToolValidationError("Tool must have a name")
        if not hasattr(tool, 'input_model') or not hasattr(tool, 'output_model'):
            raise ToolValidationError("Tool must define input_model and output_model")

        schema = tool.get_schema()
        self._tools[tool.name] = tool
        self._schemas[tool.name] = schema

    def get(self, name: str) -> Tool:
        """Get a tool by name"""
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool not found: {name}")
        return self._tools[name]

    def get_schema(self, name: str) -> ToolSchema:
        """Get a tool's schema by name"""
        if name not in self._schemas:
            raise ToolNotFoundError(f"Tool not found: {name}")
        return self._schemas[name]

    def list_tools(self) -> list[str]:
        """List all registered tool names"""
        return list(self._tools.keys())

    def list_schemas(self) -> list[ToolSchema]:
        """List all tool schemas"""
        return list(self._schemas.values())

    def get_openai_functions(self) -> list[dict[str, Any]]:
        """Export tools in OpenAI function calling format"""
        functions = []
        for name, schema in self._schemas.items():
            functions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": schema.description,
                    "parameters": schema.input_schema
                }
            })
        return functions

    def execute(
        self,
        name: str,
        args: dict[str, Any],
        context: dict[str, Any] | None = None,
        approved: bool = False
    ) -> ToolResult:
        """Execute a tool by name"""
        tool = self.get(name)
        return tool.execute(args, context, approved)

    def requires_approval(self, name: str) -> bool:
        """Check if a tool requires approval"""
        schema = self.get_schema(name)
        return schema.danger_level == ToolDangerLevel.NEEDS_APPROVAL

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
