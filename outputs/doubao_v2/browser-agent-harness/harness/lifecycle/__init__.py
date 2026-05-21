import asyncio
import os
from typing import Dict, Any, Optional
from playwright.async_api import Page
from ..context import ContextManager
from ..tools import ToolRegistry


class LifecycleHooks:
    """Handles page lifecycle events and automatic handling"""

    def __init__(self, context_manager: ContextManager, tool_registry: ToolRegistry):
        self.context_manager = context_manager
        self.tool_registry = tool_registry
        self.popup_handlers = {}
        self._setup_default_handlers()

    def _setup_default_handlers(self):
        """Setup default handlers for common events"""
        # Cookie banner detection and handling
        self.popup_handlers["cookie"] = {
            "patterns": ["cookie", "accept", "decline", "manage"],
            "handler": self._handle_cookie_banner
        }

        # Modal dialog handlers
        self.popup_handlers["modal"] = {
            "patterns": ["modal", "dialog", "popup"],
            "handler": self._handle_modal_dialog
        }

        # Alert/confirm/prompt
        self.popup_handlers["alert"] = {
            "patterns": ["alert", "confirm", "prompt"],
            "handler": self._handle_alert
        }

    async def handle_page_events(self, page: Page):
        """Handle all page events and automatic popups"""
        # Check for dialogs
        page.on("dialog", self._handle_alert)

        # Wait for network idle
        await self.wait_for_network_idle(page)

        # Check for popups/modals
        await self._check_for_popups(page)

    async def wait_for_page_load(self, page: Page, wait_until: str = "load"):
        """Wait for page to load completely"""
        await page.wait_for_load_state(wait_until)
        await self.wait_for_network_idle(page)

    async def wait_for_network_idle(self, page: Page, timeout: int = 5000):
        """Wait for network to be idle"""
        try:
            await page.wait_for_load_state("networkidle", timeout=timeout)
        except:
            # Fallback to multiple requests wait
            await asyncio.sleep(2)

    async def _check_for_popups(self, page: Page):
        """Check and handle common popups"""
        # Check for cookie banners
        cookie_selectors = [
            "[class*='cookie']", "[id*='cookie']",
            "[class*='banner']", "[id*='banner']",
            "button:has-text('Accept')", "button:has-text('Decline')"
        ]

        for selector in cookie_selectors:
            try:
                if await page.query_selector(selector):
                    await self._handle_cookie_banner(page, selector)
                    break
            except:
                continue

        # Check for modals
        modal_selectors = [
            "[role='dialog']", ".modal", "#modal",
            "[class*='modal']", "[id*='modal']"
        ]

        for selector in modal_selectors:
            try:
                if await page.query_selector(selector):
                    await self._handle_modal_dialog(page, selector)
                    break
            except:
                continue

    async def _handle_cookie_banner(self, page: Page, selector: str = ""):
        """Handle cookie consent banners"""
        try:
            # Try to find accept button
            if not selector:
                selectors = ["button:has-text('Accept')", "button:has-text('Accept all')",
                           "button:has-text('同意')", "button:has-text('接受')"]
                for s in selectors:
                    if await page.query_selector(s):
                        selector = s
                        break

            if selector:
                await self.tool_registry.execute_tool(page, "click", {"selector": selector})
                await self.wait_for_network_idle(page)
        except Exception as e:
            print(f"Failed to handle cookie banner: {e}")

    async def _handle_modal_dialog(self, page: Page, selector: str = ""):
        """Handle modal dialogs"""
        try:
            # Try to find close button
            close_selectors = ["button:has-text('Close')", "button:has-text('×')",
                             ".modal-close", ".modal-header .close",
                             "[class*='close']"]

            for close_selector in close_selectors:
                try:
                    if await page.query_selector(f"{selector} {close_selector}"):
                        await self.tool_registry.execute_tool(page, "click",
                                                           {"selector": f"{selector} {close_selector}"})
                        await self.wait_for_network_idle(page)
                        break
                except:
                    continue

            # If no close button, press ESC
            await page.keyboard.press('Escape')
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Failed to handle modal dialog: {e}")

    async def _handle_alert(self, dialog):
        """Handle alert dialogs"""
        try:
            await dialog.accept()
        except:
            pass