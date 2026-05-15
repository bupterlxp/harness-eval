"""
T - Tool Registry

Manages analysis tools with:
- Tool registration with schema declaration
- Input/output type validation
- Tool discovery and invocation
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

import pandas as pd


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type_hint: str
    required: bool
    default: Any = None
    description: str = ""


@dataclass
class ToolDefinition:
    """Complete definition of a registered tool."""
    name: str
    description: str
    category: str
    function: Callable[..., Any]
    parameters: list[ToolParameter]
    return_type: str
    input_schema: dict[str, str] | None = None
    output_schema: dict[str, str] | None = None
    requires_dataframe: bool = False
    produces_chart: bool = False


class ToolRegistry:
    """
    Registry for analysis tools.

    Each tool declares:
    - Input parameter types
    - Output type
    - Optional DataFrame schema requirements
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._categories: dict[str, list[str]] = {}

    def register(
        self,
        name: str | None = None,
        description: str = "",
        category: str = "general",
        input_schema: dict[str, str] | None = None,
        output_schema: dict[str, str] | None = None,
        requires_dataframe: bool = False,
        produces_chart: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Decorator to register a tool.

        Usage:
            @registry.register(name="load_csv", category="data")
            def load_csv(filepath: str) -> pd.DataFrame:
                ...
        """
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            parameters = self._extract_parameters(func)
            return_type = self._extract_return_type(func)

            tool_def = ToolDefinition(
                name=tool_name,
                description=description or func.__doc__ or "",
                category=category,
                function=func,
                parameters=parameters,
                return_type=return_type,
                input_schema=input_schema,
                output_schema=output_schema,
                requires_dataframe=requires_dataframe,
                produces_chart=produces_chart,
            )

            self._tools[tool_name] = tool_def

            if category not in self._categories:
                self._categories[category] = []
            self._categories[category].append(tool_name)

            return func

        return decorator

    def register_tool(self, tool_def: ToolDefinition) -> None:
        """Register a tool definition directly."""
        self._tools[tool_def.name] = tool_def
        if tool_def.category not in self._categories:
            self._categories[tool_def.category] = []
        self._categories[tool_def.category].append(tool_def.name)

    def _extract_parameters(self, func: Callable[..., Any]) -> list[ToolParameter]:
        """Extract parameter information from function signature."""
        sig = inspect.signature(func)
        try:
            hints = get_type_hints(func)
        except Exception:
            hints = {}

        params = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            type_hint = hints.get(param_name, Any)
            type_str = getattr(type_hint, "__name__", str(type_hint))

            has_default = param.default is not inspect.Parameter.empty
            params.append(ToolParameter(
                name=param_name,
                type_hint=type_str,
                required=not has_default,
                default=param.default if has_default else None,
            ))

        return params

    def _extract_return_type(self, func: Callable[..., Any]) -> str:
        """Extract return type from function."""
        try:
            hints = get_type_hints(func)
            ret = hints.get("return", Any)
            return getattr(ret, "__name__", str(ret))
        except Exception:
            return "Any"

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def invoke(self, name: str, **kwargs: Any) -> Any:
        """Invoke a tool by name with given arguments."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        self._validate_inputs(tool, kwargs)

        return tool.function(**kwargs)

    def _validate_inputs(self, tool: ToolDefinition, kwargs: dict[str, Any]) -> None:
        """Validate tool inputs against schema."""
        for param in tool.parameters:
            if param.required and param.name not in kwargs:
                raise ValueError(f"Missing required parameter: {param.name}")

        if tool.requires_dataframe:
            for key, value in kwargs.items():
                if "df" in key.lower() and not isinstance(value, pd.DataFrame):
                    raise TypeError(f"Expected DataFrame for {key}, got {type(value)}")

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_by_category(self, category: str) -> list[str]:
        """List tools in a category."""
        return self._categories.get(category, [])

    def get_categories(self) -> list[str]:
        """Get all tool categories."""
        return list(self._categories.keys())

    def get_tool_summary(self, name: str) -> str:
        """Get a summary of a tool for LLM context."""
        tool = self._tools.get(name)
        if not tool:
            return f"Tool not found: {name}"

        params_str = ", ".join(
            f"{p.name}: {p.type_hint}" + ("" if p.required else f" = {p.default}")
            for p in tool.parameters
        )
        return f"{tool.name}({params_str}) -> {tool.return_type}: {tool.description}"

    def get_all_tools_summary(self) -> str:
        """Get summary of all tools for LLM context."""
        lines = ["Available Tools:"]
        for category in sorted(self._categories.keys()):
            lines.append(f"\n## {category}")
            for tool_name in self._categories[category]:
                lines.append(f"  - {self.get_tool_summary(tool_name)}")
        return "\n".join(lines)

    def get_chart_tools(self) -> list[str]:
        """Get tools that produce charts."""
        return [name for name, tool in self._tools.items() if tool.produces_chart]

    def get_dataframe_tools(self) -> list[str]:
        """Get tools that require DataFrames."""
        return [name for name, tool in self._tools.items() if tool.requires_dataframe]
