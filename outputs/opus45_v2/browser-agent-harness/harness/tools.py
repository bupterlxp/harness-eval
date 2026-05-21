"""Tool Registry (T) - Browser operation tools.

Provides navigation, element interaction, data extraction, screenshot,
and waiting capabilities. All operations wait for elements before acting.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator, Download


class ToolCategory(str, Enum):
    NAVIGATION = "navigation"
    INTERACTION = "interaction"
    EXTRACTION = "extraction"
    WAIT = "wait"
    UTILITY = "utility"


@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    data: Any = None
    error: str | None = None
    screenshot_path: str | None = None


@dataclass
class ToolDefinition:
    """Definition of a browser tool."""
    name: str
    description: str
    category: ToolCategory
    parameters: dict[str, dict[str, Any]]
    handler: Callable[..., Awaitable[ToolResult]]

    def to_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": [k for k, v in self.parameters.items() if v.get("required", False)],
                },
            },
        }


class ToolRegistry:
    """Registry of browser operation tools.

    All tools wait for elements to be ready before operating.
    """

    DEFAULT_TIMEOUT = 30000
    ELEMENT_WAIT_TIMEOUT = 10000

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._tools: dict[str, ToolDefinition] = {}
        self._page: "Page | None" = None
        self._screenshot_counter = 0
        self._register_default_tools()

    def set_page(self, page: "Page") -> None:
        """Set the current page for tool operations."""
        self._page = page

    @property
    def page(self) -> "Page":
        if self._page is None:
            raise RuntimeError("Page not set in tool registry")
        return self._page

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Get all tools as OpenAI function schemas."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, tool_name: str, **params) -> ToolResult:
        """Execute a tool by name."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

        try:
            return await tool.handler(**params)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _wait_for_element(self, selector: str, state: str = "visible") -> "Locator":
        """Wait for an element to be ready."""
        locator = self.page.locator(selector)
        await locator.wait_for(state=state, timeout=self.ELEMENT_WAIT_TIMEOUT)
        return locator

    def _register_default_tools(self) -> None:
        """Register all default browser tools."""

        self.register(ToolDefinition(
            name="navigate",
            description="Navigate to a URL",
            category=ToolCategory.NAVIGATION,
            parameters={
                "url": {"type": "string", "description": "URL to navigate to", "required": True},
            },
            handler=self._navigate,
        ))

        self.register(ToolDefinition(
            name="go_back",
            description="Go back in browser history",
            category=ToolCategory.NAVIGATION,
            parameters={},
            handler=self._go_back,
        ))

        self.register(ToolDefinition(
            name="go_forward",
            description="Go forward in browser history",
            category=ToolCategory.NAVIGATION,
            parameters={},
            handler=self._go_forward,
        ))

        self.register(ToolDefinition(
            name="refresh",
            description="Refresh the current page",
            category=ToolCategory.NAVIGATION,
            parameters={},
            handler=self._refresh,
        ))

        self.register(ToolDefinition(
            name="click",
            description="Click on an element identified by selector or text",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector, text content, or element index", "required": True},
            },
            handler=self._click,
        ))

        self.register(ToolDefinition(
            name="type_text",
            description="Type text into an input field",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for input element", "required": True},
                "text": {"type": "string", "description": "Text to type", "required": True},
                "clear_first": {"type": "boolean", "description": "Clear field before typing", "default": True},
            },
            handler=self._type_text,
        ))

        self.register(ToolDefinition(
            name="select_option",
            description="Select an option from a dropdown",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for select element", "required": True},
                "value": {"type": "string", "description": "Option value, label, or index to select", "required": True},
            },
            handler=self._select_option,
        ))

        self.register(ToolDefinition(
            name="check",
            description="Check a checkbox or radio button",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for checkbox/radio", "required": True},
            },
            handler=self._check,
        ))

        self.register(ToolDefinition(
            name="uncheck",
            description="Uncheck a checkbox",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for checkbox", "required": True},
            },
            handler=self._uncheck,
        ))

        self.register(ToolDefinition(
            name="upload_file",
            description="Upload a file to a file input",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for file input", "required": True},
                "file_path": {"type": "string", "description": "Path to file to upload", "required": True},
            },
            handler=self._upload_file,
        ))

        self.register(ToolDefinition(
            name="press_key",
            description="Press a keyboard key",
            category=ToolCategory.INTERACTION,
            parameters={
                "key": {"type": "string", "description": "Key to press (e.g., Enter, Tab, Escape)", "required": True},
                "selector": {"type": "string", "description": "Optional selector to focus first"},
            },
            handler=self._press_key,
        ))

        self.register(ToolDefinition(
            name="hover",
            description="Hover over an element",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for element to hover", "required": True},
            },
            handler=self._hover,
        ))

        self.register(ToolDefinition(
            name="scroll",
            description="Scroll the page or an element",
            category=ToolCategory.INTERACTION,
            parameters={
                "direction": {"type": "string", "description": "up, down, left, right", "required": True},
                "amount": {"type": "integer", "description": "Pixels to scroll", "default": 500},
                "selector": {"type": "string", "description": "Optional selector to scroll within"},
            },
            handler=self._scroll,
        ))

        self.register(ToolDefinition(
            name="extract_text",
            description="Extract text from an element or the page",
            category=ToolCategory.EXTRACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector (optional, defaults to body)"},
            },
            handler=self._extract_text,
        ))

        self.register(ToolDefinition(
            name="extract_table",
            description="Extract table data as a list of dictionaries",
            category=ToolCategory.EXTRACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for table", "required": True},
            },
            handler=self._extract_table,
        ))

        self.register(ToolDefinition(
            name="extract_links",
            description="Extract all links from the page or a section",
            category=ToolCategory.EXTRACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector to limit scope"},
            },
            handler=self._extract_links,
        ))

        self.register(ToolDefinition(
            name="extract_form_fields",
            description="Extract form field information",
            category=ToolCategory.EXTRACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for form", "required": True},
            },
            handler=self._extract_form_fields,
        ))

        self.register(ToolDefinition(
            name="get_element_attribute",
            description="Get an attribute value from an element",
            category=ToolCategory.EXTRACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector for element", "required": True},
                "attribute": {"type": "string", "description": "Attribute name to get", "required": True},
            },
            handler=self._get_element_attribute,
        ))

        self.register(ToolDefinition(
            name="screenshot",
            description="Take a screenshot of the page or element",
            category=ToolCategory.UTILITY,
            parameters={
                "selector": {"type": "string", "description": "Optional selector for element screenshot"},
                "full_page": {"type": "boolean", "description": "Capture full page", "default": False},
            },
            handler=self._screenshot,
        ))

        self.register(ToolDefinition(
            name="wait_for_element",
            description="Wait for an element to appear or reach a state",
            category=ToolCategory.WAIT,
            parameters={
                "selector": {"type": "string", "description": "CSS selector", "required": True},
                "state": {"type": "string", "description": "visible, hidden, attached, detached", "default": "visible"},
                "timeout": {"type": "integer", "description": "Timeout in milliseconds", "default": 30000},
            },
            handler=self._wait_for_element_tool,
        ))

        self.register(ToolDefinition(
            name="wait_for_navigation",
            description="Wait for navigation to complete",
            category=ToolCategory.WAIT,
            parameters={
                "timeout": {"type": "integer", "description": "Timeout in milliseconds", "default": 30000},
            },
            handler=self._wait_for_navigation,
        ))

        self.register(ToolDefinition(
            name="wait_for_network_idle",
            description="Wait for network to be idle",
            category=ToolCategory.WAIT,
            parameters={
                "timeout": {"type": "integer", "description": "Timeout in milliseconds", "default": 30000},
            },
            handler=self._wait_for_network_idle,
        ))

        self.register(ToolDefinition(
            name="dismiss_dialog",
            description="Dismiss a browser dialog (alert/confirm/prompt)",
            category=ToolCategory.UTILITY,
            parameters={
                "accept": {"type": "boolean", "description": "Accept or dismiss", "default": False},
                "prompt_text": {"type": "string", "description": "Text for prompt dialogs"},
            },
            handler=self._dismiss_dialog,
        ))

        self.register(ToolDefinition(
            name="get_page_info",
            description="Get current page URL and title",
            category=ToolCategory.UTILITY,
            parameters={},
            handler=self._get_page_info,
        ))

    async def _navigate(self, url: str) -> ToolResult:
        """Navigate to a URL."""
        try:
            response = await self.page.goto(url, wait_until="domcontentloaded", timeout=self.DEFAULT_TIMEOUT)
            status = response.status if response else None
            return ToolResult(success=True, data={"url": self.page.url, "status": status})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _go_back(self) -> ToolResult:
        """Go back in history."""
        try:
            await self.page.go_back(wait_until="domcontentloaded", timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True, data={"url": self.page.url})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _go_forward(self) -> ToolResult:
        """Go forward in history."""
        try:
            await self.page.go_forward(wait_until="domcontentloaded", timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True, data={"url": self.page.url})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _refresh(self) -> ToolResult:
        """Refresh the page."""
        try:
            await self.page.reload(wait_until="domcontentloaded", timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True, data={"url": self.page.url})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _resolve_selector(self, selector: str) -> "Locator":
        """Resolve a selector that might be an index, text, or CSS selector."""
        if selector.isdigit():
            idx = int(selector)
            elements = await self._get_interactive_elements()
            if idx < len(elements):
                return elements[idx]

        if selector.startswith("text=") or selector.startswith("'") or selector.startswith('"'):
            clean_text = selector.replace("text=", "").strip("'\"")
            return self.page.get_by_text(clean_text, exact=False)

        return self.page.locator(selector)

    async def _get_interactive_elements(self) -> list["Locator"]:
        """Get all interactive elements."""
        selectors = "button, a, input, select, textarea, [role='button'], [role='link']"
        return [self.page.locator(selectors).nth(i) for i in range(await self.page.locator(selectors).count())]

    async def _click(self, selector: str) -> ToolResult:
        """Click an element."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
            await locator.click(timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _type_text(self, selector: str, text: str, clear_first: bool = True) -> ToolResult:
        """Type text into an input."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
            if clear_first:
                await locator.fill(text, timeout=self.DEFAULT_TIMEOUT)
            else:
                await locator.type(text, timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _select_option(self, selector: str, value: str) -> ToolResult:
        """Select a dropdown option."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
            await locator.select_option(value=value, timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception:
            try:
                locator = await self._resolve_selector(selector)
                await locator.select_option(label=value, timeout=self.DEFAULT_TIMEOUT)
                return ToolResult(success=True)
            except Exception as e:
                return ToolResult(success=False, error=str(e))

    async def _check(self, selector: str) -> ToolResult:
        """Check a checkbox or radio."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
            await locator.check(timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _uncheck(self, selector: str) -> ToolResult:
        """Uncheck a checkbox."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
            await locator.uncheck(timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _upload_file(self, selector: str, file_path: str) -> ToolResult:
        """Upload a file."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.set_input_files(file_path, timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _press_key(self, key: str, selector: str | None = None) -> ToolResult:
        """Press a keyboard key."""
        try:
            if selector:
                locator = await self._resolve_selector(selector)
                await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
                await locator.press(key, timeout=self.DEFAULT_TIMEOUT)
            else:
                await self.page.keyboard.press(key)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _hover(self, selector: str) -> ToolResult:
        """Hover over an element."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)
            await locator.hover(timeout=self.DEFAULT_TIMEOUT)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _scroll(self, direction: str, amount: int = 500, selector: str | None = None) -> ToolResult:
        """Scroll the page or element."""
        try:
            delta_x, delta_y = 0, 0
            if direction == "down":
                delta_y = amount
            elif direction == "up":
                delta_y = -amount
            elif direction == "right":
                delta_x = amount
            elif direction == "left":
                delta_x = -amount

            if selector:
                locator = await self._resolve_selector(selector)
                await locator.scroll_into_view_if_needed()
            else:
                await self.page.mouse.wheel(delta_x, delta_y)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _extract_text(self, selector: str | None = None) -> ToolResult:
        """Extract text from element or page."""
        try:
            if selector:
                locator = await self._resolve_selector(selector)
                text = await locator.inner_text()
            else:
                text = await self.page.locator("body").inner_text()
            return ToolResult(success=True, data={"text": text})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _extract_table(self, selector: str) -> ToolResult:
        """Extract table data."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)

            headers = []
            header_cells = locator.locator("thead th, thead td, tr:first-child th, tr:first-child td")
            header_count = await header_cells.count()
            for i in range(header_count):
                text = await header_cells.nth(i).inner_text()
                headers.append(text.strip())

            rows = []
            body_rows = locator.locator("tbody tr, tr:not(:first-child)")
            row_count = await body_rows.count()

            for i in range(row_count):
                row = body_rows.nth(i)
                cells = row.locator("td, th")
                cell_count = await cells.count()
                row_data = {}
                for j in range(cell_count):
                    text = await cells.nth(j).inner_text()
                    key = headers[j] if j < len(headers) else f"col_{j}"
                    row_data[key] = text.strip()
                if row_data:
                    rows.append(row_data)

            return ToolResult(success=True, data={"headers": headers, "rows": rows})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _extract_links(self, selector: str | None = None) -> ToolResult:
        """Extract links from page."""
        try:
            base = self.page.locator(selector) if selector else self.page
            links = base.locator("a[href]")
            count = await links.count()

            extracted = []
            for i in range(min(count, 100)):
                link = links.nth(i)
                href = await link.get_attribute("href")
                text = await link.inner_text()
                extracted.append({"href": href, "text": text.strip()[:100]})

            return ToolResult(success=True, data={"links": extracted})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _extract_form_fields(self, selector: str) -> ToolResult:
        """Extract form field information."""
        try:
            form = await self._resolve_selector(selector)
            await form.wait_for(state="visible", timeout=self.ELEMENT_WAIT_TIMEOUT)

            fields = []
            inputs = form.locator("input, select, textarea")
            count = await inputs.count()

            for i in range(count):
                inp = inputs.nth(i)
                tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                field_type = await inp.get_attribute("type") or tag
                name = await inp.get_attribute("name") or ""
                id_attr = await inp.get_attribute("id") or ""
                placeholder = await inp.get_attribute("placeholder") or ""
                required = await inp.get_attribute("required") is not None
                value = await inp.input_value() if tag != "select" else ""

                fields.append({
                    "tag": tag,
                    "type": field_type,
                    "name": name,
                    "id": id_attr,
                    "placeholder": placeholder,
                    "required": required,
                    "current_value": value,
                })

            return ToolResult(success=True, data={"fields": fields})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _get_element_attribute(self, selector: str, attribute: str) -> ToolResult:
        """Get an element attribute."""
        try:
            locator = await self._resolve_selector(selector)
            await locator.wait_for(state="attached", timeout=self.ELEMENT_WAIT_TIMEOUT)
            value = await locator.get_attribute(attribute)
            return ToolResult(success=True, data={"attribute": attribute, "value": value})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _screenshot(self, selector: str | None = None, full_page: bool = False) -> ToolResult:
        """Take a screenshot."""
        try:
            self._screenshot_counter += 1
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}_{self._screenshot_counter}.png"
            path = self.output_dir / filename

            if selector:
                locator = await self._resolve_selector(selector)
                await locator.screenshot(path=str(path))
            else:
                await self.page.screenshot(path=str(path), full_page=full_page)

            return ToolResult(success=True, data={"path": str(path)}, screenshot_path=str(path))
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _wait_for_element_tool(self, selector: str, state: str = "visible", timeout: int = 30000) -> ToolResult:
        """Wait for an element."""
        try:
            locator = self.page.locator(selector)
            await locator.wait_for(state=state, timeout=timeout)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _wait_for_navigation(self, timeout: int = 30000) -> ToolResult:
        """Wait for navigation."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return ToolResult(success=True, data={"url": self.page.url})
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _wait_for_network_idle(self, timeout: int = 30000) -> ToolResult:
        """Wait for network idle."""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=timeout)
            return ToolResult(success=True)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _dismiss_dialog(self, accept: bool = False, prompt_text: str | None = None) -> ToolResult:
        """Handle dialog - note: dialogs are typically handled via lifecycle hooks."""
        return ToolResult(success=True, data={"note": "Dialogs are handled automatically by lifecycle hooks"})

    async def _get_page_info(self) -> ToolResult:
        """Get page info."""
        try:
            return ToolResult(success=True, data={
                "url": self.page.url,
                "title": await self.page.title(),
            })
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def take_error_screenshot(self, prefix: str = "error") -> str | None:
        """Take a screenshot for error documentation."""
        try:
            result = await self._screenshot()
            if result.success and result.screenshot_path:
                new_path = self.output_dir / f"{prefix}_{os.path.basename(result.screenshot_path)}"
                os.rename(result.screenshot_path, new_path)
                return str(new_path)
        except Exception:
            pass
        return None
