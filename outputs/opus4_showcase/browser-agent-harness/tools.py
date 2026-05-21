"""Tool Registry (T) — tool registration and dispatch with input/output schemas.

Defines all browser actions the agent can take and dispatches them
via Playwright. Each tool has a JSON schema for input validation and
structured output.
"""

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from playwright.async_api import Page, BrowserContext, ElementHandle, Frame


@dataclass
class ToolSchema:
    """Schema definition for a tool's input parameters."""

    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    """Structured result from tool execution."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    page_changed: bool = False
    new_tab_opened: bool = False


# Type alias for tool handler functions
ToolHandler = Callable[..., Awaitable[ToolResult]]


class AccessibilityTreeBuilder:
    """Builds compressed accessibility tree from page DOM."""

    def __init__(self, max_elements: int = 500):
        self.max_elements = max_elements

    async def build(self, page: Page, previous_indices: set[int] | None = None) -> str:
        """Build accessibility tree summary with stable numeric indices."""
        try:
            tree_data = await page.accessibility.snapshot(interesting_only=True)
        except Exception:
            # Fallback: use evaluate to extract interactive elements
            tree_data = None

        if tree_data:
            lines = self._flatten_a11y_tree(tree_data, previous_indices)
        else:
            lines = await self._fallback_extraction(page, previous_indices)

        return "\n".join(lines[: self.max_elements])

    def _flatten_a11y_tree(
        self,
        node: dict[str, Any],
        previous_indices: set[int] | None,
        lines: list[str] | None = None,
        index_counter: list[int] | None = None,
        depth: int = 0,
    ) -> list[str]:
        """Recursively flatten accessibility tree into indexed lines."""
        if lines is None:
            lines = []
        if index_counter is None:
            index_counter = [0]

        role = node.get("role", "")
        name = node.get("name", "")
        value = node.get("value", "")

        # Skip non-informative nodes
        skip_roles = {"none", "presentation", "generic"}
        if role in skip_roles and not node.get("children"):
            return lines

        # Assign index to interactive/informative elements
        interactive_roles = {
            "link", "button", "textbox", "checkbox", "radio", "combobox",
            "menuitem", "tab", "switch", "slider", "spinbutton", "searchbox",
            "option", "menuitemcheckbox", "menuitemradio", "treeitem",
        }

        idx = index_counter[0]
        index_counter[0] += 1

        indent = "  " * depth
        new_marker = ""
        if previous_indices is not None and idx not in previous_indices:
            new_marker = " [NEW]"

        if role in interactive_roles:
            val_str = f' value="{value}"' if value else ""
            line = f"[{idx}] {indent}{role}: {name}{val_str}{new_marker}"
            lines.append(line)
        elif role in ("heading", "img", "table", "list", "listitem", "cell", "row"):
            line = f"[{idx}] {indent}{role}: {name}{new_marker}"
            lines.append(line)
        elif name and role not in ("group", "document", "main", "navigation", "banner"):
            line = f"[{idx}] {indent}{role}: {name}"
            lines.append(line)

        # Recurse into children
        for child in node.get("children", []):
            self._flatten_a11y_tree(child, previous_indices, lines, index_counter, depth + 1)

        return lines

    async def _fallback_extraction(
        self, page: Page, previous_indices: set[int] | None
    ) -> list[str]:
        """Fallback: extract interactive elements via JS evaluation."""
        elements = await page.evaluate("""() => {
            const results = [];
            const interactive = document.querySelectorAll(
                'a, button, input, select, textarea, [role="button"], [role="link"], ' +
                '[role="checkbox"], [role="radio"], [tabindex], [onclick]'
            );
            let idx = 0;
            for (const el of interactive) {
                if (idx >= 500) break;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) continue;
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || tag;
                const text = (el.textContent || '').trim().substring(0, 100);
                const name = el.getAttribute('aria-label') || el.getAttribute('name') || text;
                const value = el.value || '';
                const type = el.getAttribute('type') || '';
                results.push({idx, role, name, value, type, tag});
                idx++;
            }
            return results;
        }""")

        lines = []
        for el in elements:
            idx = el["idx"]
            new_marker = ""
            if previous_indices is not None and idx not in previous_indices:
                new_marker = " [NEW]"
            val_str = f' value="{el["value"]}"' if el["value"] else ""
            type_str = f' type="{el["type"]}"' if el["type"] else ""
            lines.append(f'[{idx}] {el["role"]}{type_str}: {el["name"]}{val_str}{new_marker}')

        return lines

    async def get_page_fingerprint(self, page: Page) -> str:
        """Get a fingerprint of current page state for stagnation detection."""
        try:
            content = await page.evaluate("""() => {
                const texts = [];
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null, false
                );
                let count = 0;
                while (walker.nextNode() && count < 100) {
                    const text = walker.currentNode.textContent.trim();
                    if (text) {
                        texts.push(text.substring(0, 50));
                        count++;
                    }
                }
                return texts.join('|');
            }""")
            return hashlib.md5(content.encode()).hexdigest()
        except Exception:
            return ""


class ToolRegistry:
    """Registry and dispatcher for browser action tools."""

    def __init__(self):
        self._tools: dict[str, ToolSchema] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._a11y_builder = AccessibilityTreeBuilder()
        self._page: Page | None = None
        self._context: BrowserContext | None = None
        self._element_index_map: dict[int, Any] = {}
        self._previous_indices: set[int] = set()
        self._register_all_tools()

    def set_browser_context(self, context: BrowserContext, page: Page) -> None:
        """Set the browser context and current page for tool execution."""
        self._context = context
        self._page = page

    def set_page(self, page: Page) -> None:
        """Update the current active page."""
        self._page = page

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser page not set. Call set_browser_context first.")
        return self._page

    @property
    def browser_context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser context not set.")
        return self._context

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get all tool schemas for LLM function calling."""
        schemas = []
        for name, schema in self._tools.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": {
                        "type": "object",
                        "properties": schema.parameters,
                        "required": schema.required,
                    },
                },
            })
        return schemas

    async def dispatch(self, action_type: str, params: dict[str, Any]) -> ToolResult:
        """Dispatch an action to the appropriate handler."""
        handler = self._handlers.get(action_type)
        if handler is None:
            return ToolResult(success=False, error=f"Unknown action: {action_type}")
        try:
            result = await handler(**params)
            return result
        except Exception as e:
            return ToolResult(success=False, error=f"Action '{action_type}' failed: {str(e)}")

    async def get_accessibility_tree(self) -> str:
        """Get current page accessibility tree."""
        tree = await self._a11y_builder.build(self.page, self._previous_indices)
        # Update previous indices for next call
        indices = set()
        for line in tree.split("\n"):
            match = re.match(r"\[(\d+)\]", line)
            if match:
                indices.add(int(match.group(1)))
        self._previous_indices = indices
        return tree

    async def get_page_fingerprint(self) -> str:
        """Get current page fingerprint for stagnation detection."""
        return await self._a11y_builder.get_page_fingerprint(self.page)

    async def build_element_index_map(self) -> None:
        """Build mapping from accessibility tree indices to element locators."""
        self._element_index_map = await self.page.evaluate("""() => {
            const map = {};
            const interactive = document.querySelectorAll(
                'a, button, input, select, textarea, [role="button"], [role="link"], ' +
                '[role="checkbox"], [role="radio"], [tabindex], [onclick]'
            );
            let idx = 0;
            for (const el of interactive) {
                if (idx >= 500) break;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) continue;
                // Generate a unique selector
                let selector = '';
                if (el.id) {
                    selector = '#' + el.id;
                } else {
                    const tag = el.tagName.toLowerCase();
                    const text = (el.textContent || '').trim().substring(0, 30);
                    const ariaLabel = el.getAttribute('aria-label') || '';
                    if (ariaLabel) {
                        selector = `${tag}[aria-label="${ariaLabel}"]`;
                    } else if (text && tag !== 'input' && tag !== 'select') {
                        selector = `${tag}:has-text("${text}")`;
                    } else {
                        selector = `${tag}:nth-of-type(${Array.from(el.parentElement.children).indexOf(el) + 1})`;
                    }
                }
                map[idx] = {
                    selector,
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    tag: el.tagName.toLowerCase(),
                };
                idx++;
            }
            return map;
        }""")

    def _register_all_tools(self) -> None:
        """Register all available browser action tools."""

        # Click action
        self._register("click", ToolSchema(
            name="click",
            description="Click on an element by its accessibility tree index or coordinates.",
            parameters={
                "index": {"type": "integer", "description": "Element index from accessibility tree"},
                "x": {"type": "number", "description": "X coordinate for coordinate-based click"},
                "y": {"type": "number", "description": "Y coordinate for coordinate-based click"},
            },
            required=[],
        ), self._handle_click)

        # Fill action
        self._register("fill", ToolSchema(
            name="fill",
            description="Type text into an input field identified by index.",
            parameters={
                "index": {"type": "integer", "description": "Element index from accessibility tree"},
                "value": {"type": "string", "description": "Text to type into the field"},
                "clear_first": {"type": "boolean", "description": "Clear existing content before typing (default: true)"},
            },
            required=["index", "value"],
        ), self._handle_fill)

        # Scroll action
        self._register("scroll", ToolSchema(
            name="scroll",
            description="Scroll the page or an element.",
            parameters={
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "Scroll direction"},
                "amount": {"type": "integer", "description": "Scroll amount in pixels (default: 500)"},
                "index": {"type": "integer", "description": "Optional element index to scroll within"},
            },
            required=["direction"],
        ), self._handle_scroll)

        # Navigate action
        self._register("navigate", ToolSchema(
            name="navigate",
            description="Navigate to a URL.",
            parameters={
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            required=["url"],
        ), self._handle_navigate)

        # Go back
        self._register("go_back", ToolSchema(
            name="go_back",
            description="Navigate back in browser history.",
            parameters={},
            required=[],
        ), self._handle_go_back)

        # Switch tab
        self._register("switch_tab", ToolSchema(
            name="switch_tab",
            description="Switch to a different browser tab by its ID.",
            parameters={
                "tab_id": {"type": "string", "description": "Tab ID to switch to"},
            },
            required=["tab_id"],
        ), self._handle_switch_tab)

        # Close tab
        self._register("close_tab", ToolSchema(
            name="close_tab",
            description="Close a browser tab by its ID.",
            parameters={
                "tab_id": {"type": "string", "description": "Tab ID to close"},
            },
            required=["tab_id"],
        ), self._handle_close_tab)

        # Extract content
        self._register("extract_content", ToolSchema(
            name="extract_content",
            description="Extract text content from the page or specific elements.",
            parameters={
                "selector": {"type": "string", "description": "CSS selector for elements to extract (optional, extracts full page if omitted)"},
                "attribute": {"type": "string", "description": "Element attribute to extract instead of text content"},
            },
            required=[],
        ), self._handle_extract_content)

        # Search page
        self._register("search_page", ToolSchema(
            name="search_page",
            description="Search for text content on the current page.",
            parameters={
                "query": {"type": "string", "description": "Text to search for"},
            },
            required=["query"],
        ), self._handle_search_page)

        # Screenshot
        self._register("screenshot", ToolSchema(
            name="screenshot",
            description="Take a screenshot of the current page.",
            parameters={
                "full_page": {"type": "boolean", "description": "Capture full page (default: false)"},
            },
            required=[],
        ), self._handle_screenshot)

        # Wait
        self._register("wait", ToolSchema(
            name="wait",
            description="Wait for a specified duration or condition.",
            parameters={
                "seconds": {"type": "number", "description": "Seconds to wait (default: 2)"},
                "selector": {"type": "string", "description": "CSS selector to wait for (optional)"},
            },
            required=[],
        ), self._handle_wait)

        # Select option
        self._register("select_option", ToolSchema(
            name="select_option",
            description="Select an option from a dropdown/select element.",
            parameters={
                "index": {"type": "integer", "description": "Element index of the select element"},
                "value": {"type": "string", "description": "Option value or label to select"},
            },
            required=["index", "value"],
        ), self._handle_select_option)

        # Press key
        self._register("press_key", ToolSchema(
            name="press_key",
            description="Press a keyboard key or key combination.",
            parameters={
                "key": {"type": "string", "description": "Key to press (e.g., 'Enter', 'Tab', 'Escape', 'Control+a')"},
            },
            required=["key"],
        ), self._handle_press_key)

        # Done action
        self._register("done", ToolSchema(
            name="done",
            description="Signal that the task is complete.",
            parameters={
                "result": {"type": "string", "description": "Summary of what was accomplished"},
                "extracted_data": {"type": "object", "description": "Any structured data extracted during the task"},
            },
            required=["result"],
        ), self._handle_done)

    def _register(self, name: str, schema: ToolSchema, handler: ToolHandler) -> None:
        """Register a tool with its schema and handler."""
        self._tools[name] = schema
        self._handlers[name] = handler

    async def _resolve_element(self, index: int) -> Any:
        """Resolve element by accessibility tree index."""
        if not self._element_index_map:
            await self.build_element_index_map()
        el_info = self._element_index_map.get(str(index)) or self._element_index_map.get(index)
        if not el_info:
            raise ValueError(f"Element with index {index} not found")
        return el_info

    async def _handle_click(
        self, index: int | None = None, x: float | None = None, y: float | None = None
    ) -> ToolResult:
        """Handle click action."""
        page = self.page
        if x is not None and y is not None:
            await page.mouse.click(x, y)
            await self._wait_for_stable(page)
            return ToolResult(success=True, data={"clicked_at": {"x": x, "y": y}}, page_changed=True)

        if index is not None:
            el_info = await self._resolve_element(index)
            try:
                # Try selector first
                selector = el_info.get("selector", "")
                if selector and not selector.startswith(":"):
                    try:
                        await page.click(selector, timeout=5000)
                    except Exception:
                        # Fallback to coordinate click
                        await page.mouse.click(el_info["x"], el_info["y"])
                else:
                    await page.mouse.click(el_info["x"], el_info["y"])
                await self._wait_for_stable(page)
                return ToolResult(success=True, data={"clicked_index": index}, page_changed=True)
            except Exception as e:
                return ToolResult(success=False, error=f"Click failed: {str(e)}")

        return ToolResult(success=False, error="Must provide either 'index' or 'x'+'y' coordinates")

    async def _handle_fill(
        self, index: int, value: str, clear_first: bool = True
    ) -> ToolResult:
        """Handle fill/type action."""
        page = self.page
        el_info = await self._resolve_element(index)
        selector = el_info.get("selector", "")
        try:
            if selector and not selector.startswith(":"):
                if clear_first:
                    await page.fill(selector, value, timeout=5000)
                else:
                    await page.click(selector, timeout=5000)
                    await page.keyboard.type(value)
            else:
                await page.mouse.click(el_info["x"], el_info["y"])
                if clear_first:
                    await page.keyboard.press("Control+a")
                    await page.keyboard.press("Backspace")
                await page.keyboard.type(value)
            return ToolResult(success=True, data={"filled_index": index, "value": value})
        except Exception as e:
            return ToolResult(success=False, error=f"Fill failed: {str(e)}")

    async def _handle_scroll(
        self, direction: str, amount: int = 500, index: int | None = None
    ) -> ToolResult:
        """Handle scroll action."""
        page = self.page
        dx, dy = 0, 0
        if direction == "down":
            dy = amount
        elif direction == "up":
            dy = -amount
        elif direction == "right":
            dx = amount
        elif direction == "left":
            dx = -amount

        try:
            if index is not None:
                el_info = await self._resolve_element(index)
                await page.mouse.move(el_info["x"], el_info["y"])
            await page.mouse.wheel(dx, dy)
            await asyncio.sleep(0.5)
            return ToolResult(success=True, data={"scrolled": direction, "amount": amount})
        except Exception as e:
            return ToolResult(success=False, error=f"Scroll failed: {str(e)}")

    async def _handle_navigate(self, url: str) -> ToolResult:
        """Handle navigation action."""
        page = self.page
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._wait_for_stable(page)
            return ToolResult(
                success=True,
                data={"url": page.url, "title": await page.title()},
                page_changed=True,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Navigation failed: {str(e)}")

    async def _handle_go_back(self) -> ToolResult:
        """Handle browser back navigation."""
        page = self.page
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=15000)
            await self._wait_for_stable(page)
            return ToolResult(
                success=True,
                data={"url": page.url, "title": await page.title()},
                page_changed=True,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Go back failed: {str(e)}")

    async def _handle_switch_tab(self, tab_id: str) -> ToolResult:
        """Handle tab switching."""
        pages = self.browser_context.pages
        for p in pages:
            page_id = str(id(p))
            if page_id == tab_id:
                self._page = p
                await p.bring_to_front()
                return ToolResult(
                    success=True,
                    data={"tab_id": tab_id, "url": p.url, "title": await p.title()},
                    page_changed=True,
                )
        return ToolResult(success=False, error=f"Tab {tab_id} not found")

    async def _handle_close_tab(self, tab_id: str) -> ToolResult:
        """Handle closing a tab."""
        pages = self.browser_context.pages
        for p in pages:
            if str(id(p)) == tab_id:
                if len(pages) <= 1:
                    return ToolResult(success=False, error="Cannot close the last tab")
                await p.close()
                # Switch to first remaining page
                remaining = self.browser_context.pages
                if remaining:
                    self._page = remaining[0]
                    await remaining[0].bring_to_front()
                return ToolResult(success=True, data={"closed_tab": tab_id})
        return ToolResult(success=False, error=f"Tab {tab_id} not found")

    async def _handle_extract_content(
        self, selector: str | None = None, attribute: str | None = None
    ) -> ToolResult:
        """Handle content extraction."""
        page = self.page
        try:
            if selector:
                elements = await page.query_selector_all(selector)
                results = []
                for el in elements[:50]:  # Limit to 50 elements
                    if attribute:
                        val = await el.get_attribute(attribute)
                    else:
                        val = await el.inner_text()
                    if val:
                        results.append(val.strip())
                return ToolResult(success=True, data={"content": results, "count": len(results)})
            else:
                # Extract main page content
                text = await page.evaluate("""() => {
                    const main = document.querySelector('main') || document.body;
                    return main.innerText.substring(0, 5000);
                }""")
                return ToolResult(success=True, data={"content": text, "url": page.url})
        except Exception as e:
            return ToolResult(success=False, error=f"Extraction failed: {str(e)}")

    async def _handle_search_page(self, query: str) -> ToolResult:
        """Search for text on the current page."""
        page = self.page
        try:
            results = await page.evaluate(f"""(query) => {{
                const body = document.body.innerText;
                const lines = body.split('\\n');
                const matches = [];
                for (let i = 0; i < lines.length; i++) {{
                    if (lines[i].toLowerCase().includes(query.toLowerCase())) {{
                        matches.push({{line: i + 1, text: lines[i].trim().substring(0, 200)}});
                    }}
                    if (matches.length >= 20) break;
                }}
                return matches;
            }}""", query)
            return ToolResult(
                success=True,
                data={"matches": results, "count": len(results), "query": query},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {str(e)}")

    async def _handle_screenshot(self, full_page: bool = False) -> ToolResult:
        """Take a screenshot."""
        page = self.page
        try:
            screenshot_bytes = await page.screenshot(full_page=full_page)
            # We just report it was taken, the execution engine stores it
            return ToolResult(
                success=True,
                data={"screenshot_taken": True, "size": len(screenshot_bytes), "bytes": screenshot_bytes},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Screenshot failed: {str(e)}")

    async def _handle_wait(
        self, seconds: float = 2, selector: str | None = None
    ) -> ToolResult:
        """Wait for time or element."""
        page = self.page
        try:
            if selector:
                await page.wait_for_selector(selector, timeout=int(seconds * 1000) if seconds else 10000)
                return ToolResult(success=True, data={"waited_for": selector})
            else:
                await asyncio.sleep(seconds)
                return ToolResult(success=True, data={"waited_seconds": seconds})
        except Exception as e:
            return ToolResult(success=False, error=f"Wait failed: {str(e)}")

    async def _handle_select_option(self, index: int, value: str) -> ToolResult:
        """Select an option from a dropdown."""
        page = self.page
        el_info = await self._resolve_element(index)
        selector = el_info.get("selector", "")
        try:
            if selector:
                await page.select_option(selector, label=value, timeout=5000)
            else:
                await page.mouse.click(el_info["x"], el_info["y"])
                await asyncio.sleep(0.3)
                await page.keyboard.type(value)
                await page.keyboard.press("Enter")
            return ToolResult(success=True, data={"selected": value, "index": index})
        except Exception as e:
            return ToolResult(success=False, error=f"Select failed: {str(e)}")

    async def _handle_press_key(self, key: str) -> ToolResult:
        """Press a keyboard key."""
        page = self.page
        try:
            await page.keyboard.press(key)
            await asyncio.sleep(0.3)
            return ToolResult(success=True, data={"key_pressed": key})
        except Exception as e:
            return ToolResult(success=False, error=f"Key press failed: {str(e)}")

    async def _handle_done(
        self, result: str, extracted_data: dict[str, Any] | None = None
    ) -> ToolResult:
        """Signal task completion."""
        return ToolResult(
            success=True,
            data={"result": result, "extracted_data": extracted_data or {}},
        )

    async def _wait_for_stable(self, page: Page, timeout: float = 5.0) -> None:
        """Wait for page to stabilize after an action."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        await asyncio.sleep(0.3)

    async def get_tab_list(self) -> list[dict[str, Any]]:
        """Get list of all open tabs with metadata."""
        tabs = []
        pages = self.browser_context.pages
        for p in pages:
            try:
                title = await p.title()
            except Exception:
                title = "(loading)"
            tabs.append({
                "tab_id": str(id(p)),
                "url": p.url,
                "title": title,
                "is_active": p == self._page,
            })
        return tabs

    async def handle_popup_detection(self) -> ToolResult | None:
        """Detect and auto-dismiss popups/modals/cookie banners."""
        page = self.page
        try:
            dismissed = await page.evaluate("""() => {
                // Common cookie banner selectors
                const selectors = [
                    '[class*="cookie"] button[class*="accept"]',
                    '[class*="cookie"] button[class*="agree"]',
                    '[id*="cookie"] button',
                    '[class*="consent"] button[class*="accept"]',
                    '[class*="modal"] button[class*="close"]',
                    '[class*="popup"] button[class*="close"]',
                    '[aria-label="Close"]',
                    '[aria-label="Dismiss"]',
                    'button[class*="dismiss"]',
                ];
                for (const sel of selectors) {
                    const btn = document.querySelector(sel);
                    if (btn && btn.offsetParent !== null) {
                        btn.click();
                        return sel;
                    }
                }
                return null;
            }""")
            if dismissed:
                return ToolResult(success=True, data={"dismissed_popup": dismissed})
        except Exception:
            pass
        return None
