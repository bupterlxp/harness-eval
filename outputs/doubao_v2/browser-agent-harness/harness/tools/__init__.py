import json
import os
from typing import Dict, Any, List, Optional
from playwright.async_api import Page, ElementHandle
from abc import ABC, abstractmethod


class Tool(ABC):
    """Base class for browser automation tools"""

    def __init__(self, context_manager, state_store):
        self.context_manager = context_manager
        self.state_store = state_store

    @abstractmethod
    async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool action"""
        pass


class ToolRegistry:
    """Registry of available browser automation tools"""

    def __init__(self, context_manager, state_store):
        self.context_manager = context_manager
        self.state_store = state_store
        self.tools: Dict[str, Tool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """Register all default browser tools"""
        from . import navigation, interaction, extraction, waiting
        self.register_tool("navigate", navigation.NavigateTool(self.context_manager, self.state_store))
        self.register_tool("click", interaction.ClickTool(self.context_manager, self.state_store))
        self.register_tool("input", interaction.InputTool(self.context_manager, self.state_store))
        self.register_tool("select", interaction.SelectTool(self.context_manager, self.state_store))
        self.register_tool("extract", extraction.ExtractTool(self.context_manager, self.state_store))
        self.register_tool("wait_for_selector", waiting.WaitForSelectorTool(self.context_manager, self.state_store))
        self.register_tool("wait_for_page_load", waiting.WaitForPageLoadTool(self.context_manager, self.state_store))

    def register_tool(self, name: str, tool: Tool):
        """Register a new tool"""
        self.tools[name] = tool

    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self.tools.get(name)

    async def execute_tool(self, page: Page, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found")

        # Wait for element readiness if selector is provided
        if "selector" in params and tool_name != "wait_for_selector":
            await self.context_manager.wait_for_element_ready(page, params["selector"])

        return await tool.execute(page, params)


# Tool implementations
class navigation:
    class NavigateTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            url = params.get("url")
            if not url:
                raise ValueError("URL parameter is required")

            await page.goto(url)
            return {"success": True, "url": page.url}


class interaction:
    class ClickTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            selector = params.get("selector")
            if not selector:
                raise ValueError("Selector parameter is required")

            await page.click(selector)
            return {"success": True, "selector": selector}

    class InputTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            selector = params.get("selector")
            text = params.get("text")
            if not selector or text is None:
                raise ValueError("Selector and text parameters are required")

            await page.fill(selector, text)
            return {"success": True, "selector": selector, "text": text}

    class SelectTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            selector = params.get("selector")
            value = params.get("value")
            if not selector or value is None:
                raise ValueError("Selector and value parameters are required")

            await page.select_option(selector, value)
            return {"success": True, "selector": selector, "value": value}


class extraction:
    class ExtractTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            # Extract page content in a structured way
            result = {}

            # Get page title
            result["title"] = await page.title()

            # Get current URL
            result["url"] = page.url

            # Extract text content
            result["text"] = await page.text_content("body")

            # Extract links
            links = await page.evaluate("""""""""Array.from(document.querySelectorAll('a')).map(a => ({text: a.textContent, href: a.href})))"""""""")
            result["links"] = links

            # Extract forms
            forms = await page.evaluate(""""""""Array.from(document.querySelectorAll('form')).map(f => ({id: f.id, action: f.action, method: f.method})))"""""""")
            result["forms"] = forms

            return result


class waiting:
    class WaitForSelectorTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            selector = params.get("selector")
            timeout = params.get("timeout", 30000)
            if not selector:
                raise ValueError("Selector parameter is required")

            await page.wait_for_selector(selector, timeout=timeout)
            return {"success": True, "selector": selector, "timeout": timeout}

    class WaitForPageLoadTool(Tool):
        async def execute(self, page: Page, params: Dict[str, Any]) -> Dict[str, Any]:
            wait_until = params.get("wait_until", "load")
            timeout = params.get("timeout", 30000)

            await page.wait_for_load_state(wait_until, timeout=timeout)
            return {"success": True, "wait_until": wait_until, "timeout": timeout}