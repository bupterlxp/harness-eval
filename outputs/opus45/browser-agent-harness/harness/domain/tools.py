"""
domain/tools.py - Browser operation tool implementations.

Provides the actual browser automation logic using Playwright.
Uses semantic selectors (aria-label, placeholder, text content) rather than hardcoded DOM structure.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.schemas import InteractableElement, PageState


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: int = 0


class BrowserToolExecutor:
    """
    Executes browser operations with proper waiting and error handling.

    All operations use semantic selectors where possible:
    - aria-label for accessibility
    - placeholder for form inputs
    - text content for buttons/links
    - id/name as fallback
    """

    def __init__(self, page: Any, timeout_ms: int = 10000) -> None:
        self._page = page
        self._default_timeout = timeout_ms

    async def navigate(self, url: str, wait_until: str = "networkidle") -> ToolResult:
        """Navigate to URL and wait for load."""
        start = datetime.now()
        try:
            await self._page.goto(url, wait_until=wait_until, timeout=30000)
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data={"url": self._page.url}, duration_ms=duration)
        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def click(
        self,
        selector: str,
        wait_navigation: bool = False,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Click an element with proper waiting."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=timeout)

            is_enabled = await self._page.is_enabled(selector)
            if not is_enabled:
                return ToolResult(success=False, error=f"Element not enabled: {selector}")

            if wait_navigation:
                async with self._page.expect_navigation(timeout=30000):
                    await self._page.click(selector, timeout=timeout)
            else:
                await self._page.click(selector, timeout=timeout)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def fill(
        self,
        selector: str,
        value: str,
        clear_first: bool = True,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Fill a text input."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=timeout)

            if clear_first:
                await self._page.fill(selector, "", timeout=timeout)

            await self._page.fill(selector, value, timeout=timeout)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def select_option(
        self,
        selector: str,
        value: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Select an option from a dropdown."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=timeout)

            try:
                await self._page.select_option(selector, value=value, timeout=timeout)
            except Exception:
                await self._page.select_option(selector, label=value, timeout=timeout)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def set_date(
        self,
        selector: str,
        date: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Set a date input value."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, state="visible", timeout=timeout)
            await self._page.fill(selector, date, timeout=timeout)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def extract_text(
        self,
        selector: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Extract text content from an element."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            text = await self._page.inner_text(selector)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data=text.strip(), duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def extract_attribute(
        self,
        selector: str,
        attribute: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Extract an attribute value from an element."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            value = await self._page.get_attribute(selector, attribute)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data=value, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def extract_table(
        self,
        selector: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Extract data from an HTML table."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            await self._page.wait_for_selector(selector, timeout=timeout)

            headers = []
            header_els = await self._page.query_selector_all(f"{selector} thead th")
            for th in header_els:
                headers.append(await th.inner_text())

            rows = []
            row_els = await self._page.query_selector_all(f"{selector} tbody tr")
            for tr in row_els:
                cells = await tr.query_selector_all("td")
                row_data = {}
                for i, cell in enumerate(cells):
                    text = await cell.inner_text()
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    row_data[key] = text.strip()
                rows.append(row_data)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data=rows, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def extract_all(
        self,
        selector: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Extract text from all matching elements."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            elements = await self._page.query_selector_all(selector)
            texts = []
            for el in elements:
                text = await el.inner_text()
                texts.append(text.strip())

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data=texts, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def wait_for_element(
        self,
        selector: str,
        visible: bool = True,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Wait for an element to appear."""
        start = datetime.now()
        timeout = timeout_ms or self._default_timeout

        try:
            state = "visible" if visible else "attached"
            await self._page.wait_for_selector(selector, state=state, timeout=timeout)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def wait_for_load(self, timeout_ms: int | None = None) -> ToolResult:
        """Wait for page load to complete."""
        start = datetime.now()
        timeout = timeout_ms or 30000

        try:
            await self._page.wait_for_load_state("networkidle", timeout=timeout)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def screenshot(
        self,
        path: str,
        selector: str | None = None,
        full_page: bool = False,
    ) -> ToolResult:
        """Take a screenshot."""
        start = datetime.now()

        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)

            if selector:
                element = await self._page.wait_for_selector(selector, timeout=5000)
                if element:
                    await element.screenshot(path=path)
            else:
                await self._page.screenshot(path=path, full_page=full_page)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data=path, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def download_file(
        self,
        trigger_selector: str,
        save_path: str,
        timeout_ms: int | None = None,
    ) -> ToolResult:
        """Trigger and wait for a file download."""
        start = datetime.now()
        timeout = timeout_ms or 30000

        try:
            Path(save_path).parent.mkdir(parents_=True, exist_ok=True)

            async with self._page.expect_download(timeout=timeout) as download_info:
                await self._page.click(trigger_selector)

            download = await download_info.value
            await download.save_as(save_path)

            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=True, data=save_path, duration_ms=duration)

        except Exception as e:
            duration = int((datetime.now() - start).total_seconds() * 1000)
            return ToolResult(success=False, error=str(e), duration_ms=duration)

    async def get_page_state(self) -> PageState:
        """Extract current page state with DOM summary."""
        url = self._page.url
        title = await self._page.title()

        elements = []
        selectors_to_check = [
            ("input", "input:visible"),
            ("button", "button:visible"),
            ("a", "a[href]:visible"),
            ("select", "select:visible"),
            ("textarea", "textarea:visible"),
        ]

        for tag, selector in selectors_to_check:
            try:
                els = await self._page.query_selector_all(selector)
                for el in els[:10]:
                    try:
                        elements.append(await self._extract_element_info(el, tag))
                    except Exception:
                        continue
            except Exception:
                continue

        has_popup = False
        popup_type = None
        popup_checks = [
            ("#cookie-banner.active", "cookie_banner"),
            (".cookie-banner.active", "cookie_banner"),
            (".modal-overlay.active", "modal"),
            ("#reject-modal.active", "reject_modal"),
            ("#success-modal.active", "success_modal"),
        ]

        for sel, ptype in popup_checks:
            try:
                if await self._page.is_visible(sel):
                    has_popup = True
                    popup_type = ptype
                    break
            except Exception:
                continue

        return PageState(
            url=url,
            title=title,
            interactable_elements=elements,
            has_popup=has_popup,
            popup_type=popup_type,
        )

    async def _extract_element_info(self, element: Any, tag: str) -> InteractableElement:
        """Extract info from a single element."""
        el_type = await element.get_attribute("type")
        text = await element.inner_text() if tag not in ("input", "select") else None
        placeholder = await element.get_attribute("placeholder")
        aria_label = await element.get_attribute("aria-label")
        name = await element.get_attribute("name")
        el_id = await element.get_attribute("id")
        is_visible = await element.is_visible()
        is_enabled = await element.is_enabled()

        if el_id:
            css_selector = f"#{el_id}"
        elif name:
            css_selector = f"{tag}[name='{name}']"
        elif placeholder:
            css_selector = f"{tag}[placeholder*='{placeholder[:20]}']"
        elif text and tag in ("button", "a"):
            clean_text = text.strip()[:20]
            css_selector = f"{tag}:has-text('{clean_text}')"
        else:
            css_selector = tag

        return InteractableElement(
            tag=tag,
            element_type=el_type,
            selector=css_selector,
            text=text[:50].strip() if text else None,
            placeholder=placeholder,
            aria_label=aria_label,
            name=name,
            element_id=el_id,
            is_visible=is_visible,
            is_enabled=is_enabled,
        )

    async def find_element_by_text(self, text: str, tag: str = "*") -> str | None:
        """Find element selector by text content."""
        selector = f"{tag}:has-text('{text}')"
        try:
            if await self._page.is_visible(selector):
                return selector
        except Exception:
            pass
        return None

    async def find_element_by_placeholder(self, placeholder: str) -> str | None:
        """Find input element by placeholder."""
        selector = f"input[placeholder*='{placeholder}'], textarea[placeholder*='{placeholder}']"
        try:
            if await self._page.is_visible(selector):
                return selector
        except Exception:
            pass
        return None

    async def find_element_by_label(self, label: str) -> str | None:
        """Find form element by its label text."""
        try:
            label_el = await self._page.query_selector(f"label:has-text('{label}')")
            if label_el:
                for_id = await label_el.get_attribute("for")
                if for_id:
                    return f"#{for_id}"

                input_el = await label_el.query_selector("input, select, textarea")
                if input_el:
                    el_id = await input_el.get_attribute("id")
                    if el_id:
                        return f"#{el_id}"
                    name = await input_el.get_attribute("name")
                    if name:
                        tag = await input_el.evaluate("el => el.tagName.toLowerCase()")
                        return f"{tag}[name='{name}']"
        except Exception:
            pass
        return None
