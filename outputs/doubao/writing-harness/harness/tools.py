from typing import Dict, Any, Optional, Type
from abc import ABC, abstractmethod
from pydantic import BaseModel, ValidationError
from enum import Enum


class ToolResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    NEEDS_APPROVAL = "needs_approval"


class ToolCallResult(BaseModel):
    status: ToolResultStatus
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    requires_approval: bool = False


class ToolBase(ABC):
    """Abstract base class for all tools"""
    name: str
    description: str
    input_schema: Type[BaseModel]
    requires_approval: bool = False

    @abstractmethod
    def execute(self, **kwargs) -> ToolCallResult:
        """Execute the tool with the given parameters"""
        pass

    def validate_input(self, **kwargs) -> ToolCallResult:
        """Validate input against schema"""
        try:
            self.input_schema(**kwargs)
            return ToolCallResult(status=ToolResultStatus.SUCCESS)
        except ValidationError as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Input validation failed: {str(e)}"
            )


class ToolRegistry:
    """Registry for all available tools"""
    def __init__(self):
        self._tools: Dict[str, ToolBase] = {}

    def register_tool(self, tool: ToolBase) -> None:
        """Register a tool in the registry"""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def unregister_tool(self, tool_name: str) -> None:
        """Unregister a tool from the registry"""
        if tool_name in self._tools:
            del self._tools[tool_name]

    def get_tool(self, tool_name: str) -> Optional[ToolBase]:
        """Get a tool by name"""
        return self._tools.get(tool_name)

    def list_tools(self) -> Dict[str, str]:
        """List all registered tools and their descriptions"""
        return {name: tool.description for name, tool in self._tools.items()}

    def execute_tool(self, tool_name: str, **kwargs) -> ToolCallResult:
        """Execute a tool by name with the given parameters"""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Tool '{tool_name}' not found in registry"
            )

        # Validate input first
        validation_result = tool.validate_input(**kwargs)
        if validation_result.status != ToolResultStatus.SUCCESS:
            return validation_result

        try:
            result = tool.execute(**kwargs)
            return result
        except Exception as e:
            return ToolCallResult(
                status=ToolResultStatus.ERROR,
                error_message=f"Tool execution failed: {str(e)}"
            )