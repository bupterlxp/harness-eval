"""Context Manager (C) - Page context with accessibility tree summarization.

Provides page context to the LLM without injecting full DOM/HTML.
Uses accessibility tree summary and key element extraction.
"""

import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, Locator


@dataclass
class ElementInfo:
    """Information about a page element."""
    role: str
    name: str
    text: str
    tag: str
    attributes: dict[str, str]
    bounding_box: dict[str, float] | None
    is_visible: bool
    is_enabled: bool
    selector: str
    index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "text": self.text[:200] if self.text else "",
            "tag": self.tag,
            "attributes": self.attributes,
            "is_visible": self.is_visible,
            "is_enabled": self.is_enabled,
            "selector": self.selector,
            "index": self.index,
        }

    def __str__(self) -> str:
        parts = [f"[{self.index}] {self.role}"]
        if self.name:
            parts.append(f'"{self.name}"')
        if self.text and self.text != self.name:
            display_text = self.text[:50] + "..." if len(self.text) > 50 else self.text
            parts.append(f'text="{display_text}"')
        return " ".join(parts)


@dataclass
class PageContext:
    """Summarized page context for LLM consumption."""
    url: str
    title: str
    elements: list[ElementInfo] = field(default_factory=list)
    page_text_summary: str = ""
    has_forms: bool = False
    has_tables: bool = False
    has_modals: bool = False
    error_messages: list[str] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Generate a concise context string for LLM prompts."""
        lines = [
            f"URL: {self.url}",
            f"Title: {self.title}",
        ]

        if self.error_messages:
            lines.append(f"Page Errors: {', '.join(self.error_messages)}")

        if self.has_modals:
            lines.append("Note: Modal/dialog detected on page")

        lines.append("")
        lines.append("Interactive Elements:")

        for elem in self.elements[:100]:
            lines.append(f"  {elem}")

        if len(self.elements) > 100:
            lines.append(f"  ... and {len(self.elements) - 100} more elements")

        if self.page_text_summary:
            lines.append("")
            lines.append("Page Summary:")
            lines.append(self.page_text_summary[:500])

        return "\n".join(lines)


class ContextManager:
    """Manages page context extraction and summarization.

    Key principle: Never inject full DOM/HTML into prompts.
    Instead, extract accessibility tree and key interactive elements.
    """

    INTERACTIVE_ROLES = {
        "button", "link", "textbox", "checkbox", "radio", "combobox",
        "listbox", "menuitem", "tab", "switch", "slider", "spinbutton",
        "searchbox", "option", "menuitemcheckbox", "menuitemradio"
    }

    SEMANTIC_SELECTORS = [
        "[aria-label]",
        "[placeholder]",
        "[name]",
        "[id]",
        "button",
        "a[href]",
        "input",
        "select",
        "textarea",
        "[role='button']",
        "[role='link']",
        "[role='textbox']",
        "[role='checkbox']",
        "[role='radio']",
        "[role='combobox']",
        "[role='tab']",
    ]

    def __init__(self):
        self._element_cache: dict[int, ElementInfo] = {}
        self._current_context: PageContext | None = None

    async def extract_context(self, page: "Page") -> PageContext:
        """Extract summarized page context."""
        url = page.url
        title = await page.title()

        elements = await self._extract_interactive_elements(page)

        has_forms = await page.locator("form").count() > 0
        has_tables = await page.locator("table").count() > 0
        has_modals = await self._detect_modals(page)

        error_messages = await self._extract_error_messages(page)

        page_text_summary = await self._extract_text_summary(page)

        self._current_context = PageContext(
            url=url,
            title=title,
            elements=elements,
            page_text_summary=page_text_summary,
            has_forms=has_forms,
            has_tables=has_tables,
            has_modals=has_modals,
            error_messages=error_messages,
        )

        self._element_cache = {elem.index: elem for elem in elements}

        return self._current_context

    async def _extract_interactive_elements(self, page: "Page") -> list[ElementInfo]:
        """Extract interactive elements using accessibility tree approach."""
        elements: list[ElementInfo] = []
        seen_selectors: set[str] = set()
        index = 0

        for selector in self.SEMANTIC_SELECTORS:
            try:
                locators = page.locator(selector)
                count = await locators.count()

                for i in range(min(count, 50)):
                    try:
                        locator = locators.nth(i)

                        is_visible = await locator.is_visible()
                        if not is_visible:
                            continue

                        elem_info = await self._extract_element_info(locator, index)
                        if elem_info and elem_info.selector not in seen_selectors:
                            elements.append(elem_info)
                            seen_selectors.add(elem_info.selector)
                            index += 1

                            if index >= 150:
                                return elements
                    except Exception:
                        continue
            except Exception:
                continue

        return elements

    async def _extract_element_info(self, locator: "Locator", index: int) -> ElementInfo | None:
        """Extract information about a single element."""
        try:
            tag = await locator.evaluate("el => el.tagName.toLowerCase()")
            role = await locator.get_attribute("role") or self._infer_role(tag)

            aria_label = await locator.get_attribute("aria-label") or ""
            placeholder = await locator.get_attribute("placeholder") or ""
            name_attr = await locator.get_attribute("name") or ""
            id_attr = await locator.get_attribute("id") or ""
            text_content = await locator.inner_text() if tag not in ("input", "select") else ""
            text_content = text_content.strip()[:100] if text_content else ""

            name = aria_label or placeholder or text_content or name_attr

            is_enabled = await locator.is_enabled()

            selector = self._build_selector(tag, id_attr, name_attr, aria_label, placeholder, text_content)

            attributes = {}
            if id_attr:
                attributes["id"] = id_attr
            if name_attr:
                attributes["name"] = name_attr
            if aria_label:
                attributes["aria-label"] = aria_label
            if placeholder:
                attributes["placeholder"] = placeholder

            input_type = await locator.get_attribute("type")
            if input_type:
                attributes["type"] = input_type

            href = await locator.get_attribute("href")
            if href and tag == "a":
                attributes["href"] = href[:100]

            return ElementInfo(
                role=role,
                name=name,
                text=text_content,
                tag=tag,
                attributes=attributes,
                bounding_box=None,
                is_visible=True,
                is_enabled=is_enabled,
                selector=selector,
                index=index,
            )
        except Exception:
            return None

    def _infer_role(self, tag: str) -> str:
        """Infer ARIA role from HTML tag."""
        role_map = {
            "button": "button",
            "a": "link",
            "input": "textbox",
            "select": "combobox",
            "textarea": "textbox",
            "checkbox": "checkbox",
            "radio": "radio",
            "option": "option",
            "li": "listitem",
            "table": "table",
            "form": "form",
            "img": "image",
            "nav": "navigation",
            "header": "banner",
            "footer": "contentinfo",
            "main": "main",
            "article": "article",
            "section": "region",
        }
        return role_map.get(tag, "generic")

    def _build_selector(
        self,
        tag: str,
        id_attr: str,
        name_attr: str,
        aria_label: str,
        placeholder: str,
        text_content: str
    ) -> str:
        """Build a semantic selector for the element."""
        if id_attr:
            return f"#{id_attr}"
        if aria_label:
            return f'{tag}[aria-label="{self._escape_attr(aria_label)}"]'
        if placeholder:
            return f'{tag}[placeholder="{self._escape_attr(placeholder)}"]'
        if name_attr:
            return f'{tag}[name="{self._escape_attr(name_attr)}"]'
        if text_content and tag in ("button", "a"):
            short_text = text_content[:30]
            return f'{tag}:has-text("{self._escape_attr(short_text)}")'
        return tag

    def _escape_attr(self, value: str) -> str:
        """Escape attribute value for use in selector."""
        return value.replace('"', '\\"').replace("\n", " ").strip()

    async def _detect_modals(self, page: "Page") -> bool:
        """Detect if there's a modal/dialog on the page."""
        modal_selectors = [
            "[role='dialog']",
            "[role='alertdialog']",
            ".modal:visible",
            ".dialog:visible",
            "[aria-modal='true']",
        ]
        for selector in modal_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    first = page.locator(selector).first
                    if await first.is_visible():
                        return True
            except Exception:
                continue
        return False

    async def _extract_error_messages(self, page: "Page") -> list[str]:
        """Extract visible error messages from the page."""
        errors: list[str] = []
        error_selectors = [
            "[role='alert']",
            ".error",
            ".error-message",
            ".alert-danger",
            ".form-error",
            "[aria-invalid='true']",
        ]
        for selector in error_selectors:
            try:
                elements = page.locator(selector)
                count = await elements.count()
                for i in range(min(count, 5)):
                    elem = elements.nth(i)
                    if await elem.is_visible():
                        text = await elem.inner_text()
                        if text.strip():
                            errors.append(text.strip()[:100])
            except Exception:
                continue
        return errors[:5]

    async def _extract_text_summary(self, page: "Page") -> str:
        """Extract a text summary of the page content."""
        try:
            body_text = await page.locator("body").inner_text()
            lines = body_text.split("\n")
            non_empty_lines = [line.strip() for line in lines if line.strip()]
            summary_lines = non_empty_lines[:20]
            return "\n".join(summary_lines)
        except Exception:
            return ""

    def get_element_by_index(self, index: int) -> ElementInfo | None:
        """Get a cached element by its index."""
        return self._element_cache.get(index)

    def get_current_context(self) -> PageContext | None:
        """Get the current page context."""
        return self._current_context

    async def find_element_by_description(
        self,
        page: "Page",
        description: str
    ) -> ElementInfo | None:
        """Find an element matching a natural language description."""
        if self._current_context is None:
            await self.extract_context(page)

        desc_lower = description.lower()

        for elem in self._element_cache.values():
            if elem.name and desc_lower in elem.name.lower():
                return elem
            if elem.text and desc_lower in elem.text.lower():
                return elem
            for attr_val in elem.attributes.values():
                if desc_lower in str(attr_val).lower():
                    return elem

        return None

    def clear_cache(self) -> None:
        """Clear the element cache (call on navigation)."""
        self._element_cache.clear()
        self._current_context = None
