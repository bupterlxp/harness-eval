"""
tools.py - Tool registry for the browser agent harness.

Defines the interface and metadata for all browser operation tools.
Actual browser implementations are in domain/tools.py.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


class ToolSafety(str, Enum):
    """Tool safety classification."""
    SAFE = "safe"
    NEEDS_APPROVAL = "needs_approval"


@dataclass
class ToolParameter:
    """Tool parameter definition."""
    name: str
    param_type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolDefinition:
    """Tool definition with metadata."""
    name: str
    description: str
    safety: ToolSafety
    parameters: list[ToolParameter] = field(default_factory=list)
    returns: str = "None"
    timeout_ms: int = 30000
    max_retries: int = 3
    requires_page_loaded: bool = True

    def to_openai_function(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.param_type,
                "description": param.description,
            }
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class ToolRegistry:
    """Registry of available browser operation tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[..., Coroutine[Any, Any, Any]]] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register all built-in browser tools."""

        # Navigation tools
        self.register(ToolDefinition(
            name="navigate",
            description="Navigate to a URL. Waits for page load to complete.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("url", "string", "The URL to navigate to"),
            ],
            returns="PageState with new page information",
            timeout_ms=30000,
            requires_page_loaded=False,
        ))

        self.register(ToolDefinition(
            name="go_back",
            description="Navigate to the previous page in browser history.",
            safety=ToolSafety.SAFE,
            parameters=[],
            returns="PageState with previous page information",
            timeout_ms=15000,
        ))

        self.register(ToolDefinition(
            name="reload",
            description="Reload the current page.",
            safety=ToolSafety.SAFE,
            parameters=[],
            returns="PageState with refreshed page information",
            timeout_ms=30000,
        ))

        # Element interaction tools
        self.register(ToolDefinition(
            name="click",
            description="Click on an element identified by selector.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the element"),
                ToolParameter("wait_navigation", "boolean", "Whether to wait for navigation after click", required=False, default=False),
            ],
            returns="True if click succeeded",
            timeout_ms=10000,
        ))

        self.register(ToolDefinition(
            name="click_submit",
            description="Click a submit/approve/reject button. Requires user approval.",
            safety=ToolSafety.NEEDS_APPROVAL,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the button"),
                ToolParameter("action_description", "string", "Description of the action for user approval"),
            ],
            returns="True if click succeeded",
            timeout_ms=10000,
        ))

        self.register(ToolDefinition(
            name="fill",
            description="Fill a text input or textarea with the specified value.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the input element"),
                ToolParameter("value", "string", "Text value to fill"),
                ToolParameter("clear_first", "boolean", "Whether to clear existing content first", required=False, default=True),
            ],
            returns="True if fill succeeded",
            timeout_ms=5000,
        ))

        self.register(ToolDefinition(
            name="select",
            description="Select an option from a dropdown/select element.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the select element"),
                ToolParameter("value", "string", "Option value or visible text to select"),
            ],
            returns="True if select succeeded",
            timeout_ms=5000,
        ))

        self.register(ToolDefinition(
            name="set_date",
            description="Set a date input to the specified value.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the date input"),
                ToolParameter("date", "string", "Date in YYYY-MM-DD format"),
            ],
            returns="True if date was set",
            timeout_ms=5000,
        ))

        # Extraction tools
        self.register(ToolDefinition(
            name="extract_text",
            description="Extract text content from an element.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the element"),
            ],
            returns="Text content of the element",
            timeout_ms=5000,
        ))

        self.register(ToolDefinition(
            name="extract_attribute",
            description="Extract an attribute value from an element.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the element"),
                ToolParameter("attribute", "string", "Attribute name to extract"),
            ],
            returns="Attribute value",
            timeout_ms=5000,
        ))

        self.register(ToolDefinition(
            name="extract_table",
            description="Extract data from an HTML table.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the table"),
            ],
            returns="List of dictionaries with table data",
            timeout_ms=10000,
        ))

        self.register(ToolDefinition(
            name="extract_all",
            description="Extract text from multiple elements matching a selector.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the elements"),
            ],
            returns="List of text contents",
            timeout_ms=10000,
        ))

        # Wait tools
        self.register(ToolDefinition(
            name="wait_for_element",
            description="Wait for an element to appear in the DOM.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("selector", "string", "CSS selector for the element"),
                ToolParameter("timeout_ms", "integer", "Maximum wait time in milliseconds", required=False, default=10000),
                ToolParameter("visible", "boolean", "Whether element must be visible", required=False, default=True),
            ],
            returns="True if element appeared",
            timeout_ms=30000,
            requires_page_loaded=False,
        ))

        self.register(ToolDefinition(
            name="wait_for_load",
            description="Wait for page load to complete (network idle).",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("timeout_ms", "integer", "Maximum wait time in milliseconds", required=False, default=30000),
            ],
            returns="True when page is loaded",
            timeout_ms=30000,
            requires_page_loaded=False,
        ))

        self.register(ToolDefinition(
            name="wait_for_navigation",
            description="Wait for a navigation event to occur.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("timeout_ms", "integer", "Maximum wait time in milliseconds", required=False, default=30000),
            ],
            returns="New URL after navigation",
            timeout_ms=30000,
            requires_page_loaded=False,
        ))

        # Screenshot tool
        self.register(ToolDefinition(
            name="screenshot",
            description="Take a screenshot of the current page or element.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("path", "string", "File path to save the screenshot"),
                ToolParameter("selector", "string", "CSS selector for element screenshot (optional)", required=False),
                ToolParameter("full_page", "boolean", "Whether to capture full page", required=False, default=False),
            ],
            returns="Path to saved screenshot",
            timeout_ms=10000,
        ))

        # Popup handling
        self.register(ToolDefinition(
            name="close_popup",
            description="Close a popup, modal, or banner.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("popup_type", "string", "Type of popup: 'cookie_banner', 'modal', 'alert'"),
                ToolParameter("selector", "string", "CSS selector for close button (optional)", required=False),
            ],
            returns="True if popup was closed",
            timeout_ms=5000,
        ))

        self.register(ToolDefinition(
            name="detect_popup",
            description="Detect if any popup is currently visible.",
            safety=ToolSafety.SAFE,
            parameters=[],
            returns="Popup type if detected, None otherwise",
            timeout_ms=2000,
        ))

        # Page info
        self.register(ToolDefinition(
            name="get_page_info",
            description="Get current page information including URL, title, and interactable elements.",
            safety=ToolSafety.SAFE,
            parameters=[],
            returns="PageState with current page information",
            timeout_ms=10000,
            requires_page_loaded=False,
        ))

        # File download
        self.register(ToolDefinition(
            name="download_file",
            description="Trigger and wait for a file download.",
            safety=ToolSafety.SAFE,
            parameters=[
                ToolParameter("trigger_selector", "string", "CSS selector for download trigger element"),
                ToolParameter("save_path", "string", "Path to save the downloaded file"),
                ToolParameter("timeout_ms", "integer", "Maximum wait time in milliseconds", required=False, default=30000),
            ],
            returns="Path to downloaded file",
            timeout_ms=60000,
        ))

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool

    def set_handler(
        self,
        name: str,
        handler: Callable[..., Coroutine[Any, Any, Any]],
    ) -> None:
        """Set the handler function for a tool."""
        if name not in self._tools:
            raise ValueError(f"Unknown tool: {name}")
        self._handlers[name] = handler

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def get_handler(self, name: str) -> Callable[..., Coroutine[Any, Any, Any]] | None:
        """Get the handler for a tool."""
        return self._handlers.get(name)

    def get_all_tools(self) -> list[ToolDefinition]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_safe_tools(self) -> list[ToolDefinition]:
        """Get all safe tools."""
        return [t for t in self._tools.values() if t.safety == ToolSafety.SAFE]

    def get_tools_requiring_approval(self) -> list[ToolDefinition]:
        """Get tools requiring user approval."""
        return [t for t in self._tools.values() if t.safety == ToolSafety.NEEDS_APPROVAL]

    def to_openai_functions(self) -> list[dict[str, Any]]:
        """Get all tools in OpenAI function calling format."""
        return [t.to_openai_function() for t in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Get all tool names."""
        return list(self._tools.keys())
