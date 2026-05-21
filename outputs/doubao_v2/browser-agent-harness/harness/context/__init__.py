import json
import os
from typing import Dict, Any, List, Optional
from playwright.async_api import BrowserContext, Page


class ContextManager:
    """Manages browser page contexts and state"""

    def __init__(self, browser_context: BrowserContext):
        self.browser_context = browser_context
        self.pages: Dict[str, Page] = {}
        self.current_page: Optional[Page] = None

    async def initialize(self):
        """Initialize context manager"""
        pass

    async def new_page(self) -> Page:
        """Create a new page"""
        page = await self.browser_context.new_page()
        self.pages[page.url] = page
        self.current_page = page
        return page

    async def get_page_state(self, page: Page) -> Dict[str, Any]:
        """Get compressed page state (not full DOM)"""
        state = {}

        # Get basic page info
        state["url"] = page.url
        state["title"] = await page.title()

        # Get accessibility tree summary
        try:
            ax_tree = await page.accessibility.snapshot()
            if ax_tree:
                state["accessibility_tree"] = self._compress_accessibility_tree(ax_tree)
        except Exception:
            state["accessibility_tree"] = "unavailable"

        # Get key elements
        state["key_elements"] = await self._get_key_elements(page)

        return state

    def _compress_accessibility_tree(self, ax_tree: Dict[str, Any]) -> Dict[str, Any]:
        """Compress accessibility tree to avoid large prompts"""
        compressed = {}

        if "role" in ax_tree:
            compressed["role"] = ax_tree["role"]
        if "name" in ax_tree:
            compressed["name"] = ax_tree["name"]
        if "value" in ax_tree:
            compressed["value"] = ax_tree["value"]

        # Recursively compress children but limit depth
        if "children" in ax_tree and ax_tree["children"]:
            children = ax_tree["children"]
            if len(children) > 10:
                # Limit number of children shown
                compressed["children"] = [
                    self._compress_accessibility_tree(child)
                    for child in children[:5]
                ]
                compressed["children_count"] = len(children)
            else:
                compressed["children"] = [
                    self._compress_accessibility_tree(child)
                    for child in children
                ]

        return compressed

    async def _get_key_elements(self, page: Page) -> List[Dict[str, Any]]:
        """Get list of key elements on the page"""
        elements = []

        # Get interactive elements
        selectors = [
            "a", "button", "input", "select", "textarea",
            "[role=button]", "[role=link]", "[role=textbox]"
        ]

        for selector in selectors:
            try:
                els = await page.query_selector_all(selector)
                for el in els[:3]:  # Limit per selector
                    info = {}
                    info["tag"] = await el.evaluate("el => el.tagName.toLowerCase()")
                    info["selector"] = selector
                    info["text"] = await el.text_content()
                    info["id"] = await el.evaluate("el => el.id")
                    info["class"] = await el.evaluate("el => el.className")
                    elements.append(info)
            except Exception:
                continue

        return elements[:20]  # Total limit

    async def wait_for_element_ready(self, page: Page, selector: str, timeout: int = 30000):
        """Wait for element to be ready and visible"""
        await page.wait_for_selector(selector, timeout=timeout)
        await page.wait_for_element_state(selector, "visible", timeout=timeout)
        await page.wait_for_element_state(selector, "enabled", timeout=timeout)

    async def cleanup(self):
        """Cleanup all pages"""
        for page in self.pages.values():
            if not page.is_closed():
                await page.close()
        self.pages.clear()
        self.current_page = None