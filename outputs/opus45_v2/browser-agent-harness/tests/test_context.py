"""Tests for the Context Manager module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from harness.context import ContextManager, PageContext, ElementInfo


class TestElementInfo:
    """Tests for ElementInfo dataclass."""

    def test_element_info_creation(self):
        elem = ElementInfo(
            role="button",
            name="Submit",
            text="Submit Form",
            tag="button",
            attributes={"id": "submit-btn"},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="#submit-btn",
            index=0,
        )
        assert elem.role == "button"
        assert elem.name == "Submit"
        assert elem.index == 0

    def test_element_info_to_dict(self):
        elem = ElementInfo(
            role="link",
            name="Home",
            text="Go Home",
            tag="a",
            attributes={"href": "/"},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="a:has-text('Home')",
            index=1,
        )
        data = elem.to_dict()
        assert data["role"] == "link"
        assert data["name"] == "Home"
        assert data["selector"] == "a:has-text('Home')"

    def test_element_info_str(self):
        elem = ElementInfo(
            role="button",
            name="Login",
            text="Login Now",
            tag="button",
            attributes={},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="#login",
            index=0,
        )
        s = str(elem)
        assert "[0]" in s
        assert "button" in s
        assert "Login" in s

    def test_element_info_str_long_text(self):
        long_text = "A" * 100
        elem = ElementInfo(
            role="button",
            name="",
            text=long_text,
            tag="button",
            attributes={},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="button",
            index=0,
        )
        s = str(elem)
        assert "..." in s


class TestPageContext:
    """Tests for PageContext dataclass."""

    def test_page_context_creation(self):
        ctx = PageContext(
            url="https://example.com",
            title="Example",
        )
        assert ctx.url == "https://example.com"
        assert ctx.title == "Example"
        assert len(ctx.elements) == 0

    def test_page_context_with_elements(self):
        elem = ElementInfo(
            role="button",
            name="Submit",
            text="",
            tag="button",
            attributes={},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="#submit",
            index=0,
        )
        ctx = PageContext(
            url="https://example.com",
            title="Example",
            elements=[elem],
            has_forms=True,
        )
        assert len(ctx.elements) == 1
        assert ctx.has_forms is True

    def test_to_prompt_context(self):
        elem = ElementInfo(
            role="button",
            name="Submit",
            text="Submit Form",
            tag="button",
            attributes={},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="#submit",
            index=0,
        )
        ctx = PageContext(
            url="https://example.com",
            title="Test Page",
            elements=[elem],
            page_text_summary="This is a test page.",
        )

        prompt = ctx.to_prompt_context()

        assert "https://example.com" in prompt
        assert "Test Page" in prompt
        assert "Interactive Elements" in prompt
        assert "button" in prompt
        assert "Submit" in prompt

    def test_to_prompt_context_with_errors(self):
        ctx = PageContext(
            url="https://example.com",
            title="Test",
            error_messages=["Invalid email address"],
        )

        prompt = ctx.to_prompt_context()
        assert "Invalid email address" in prompt

    def test_to_prompt_context_with_modals(self):
        ctx = PageContext(
            url="https://example.com",
            title="Test",
            has_modals=True,
        )

        prompt = ctx.to_prompt_context()
        assert "Modal" in prompt or "dialog" in prompt.lower()


class TestContextManager:
    """Tests for ContextManager."""

    def test_init(self):
        cm = ContextManager()
        assert cm._element_cache == {}
        assert cm._current_context is None

    def test_infer_role(self):
        cm = ContextManager()
        assert cm._infer_role("button") == "button"
        assert cm._infer_role("a") == "link"
        assert cm._infer_role("input") == "textbox"
        assert cm._infer_role("select") == "combobox"
        assert cm._infer_role("div") == "generic"

    def test_build_selector_with_id(self):
        cm = ContextManager()
        selector = cm._build_selector("button", "submit-btn", "", "", "", "")
        assert selector == "#submit-btn"

    def test_build_selector_with_aria_label(self):
        cm = ContextManager()
        selector = cm._build_selector("button", "", "", "Close dialog", "", "")
        assert 'aria-label="Close dialog"' in selector

    def test_build_selector_with_placeholder(self):
        cm = ContextManager()
        selector = cm._build_selector("input", "", "", "", "Enter email", "")
        assert 'placeholder="Enter email"' in selector

    def test_build_selector_with_name(self):
        cm = ContextManager()
        selector = cm._build_selector("input", "", "email", "", "", "")
        assert 'name="email"' in selector

    def test_build_selector_with_text(self):
        cm = ContextManager()
        selector = cm._build_selector("button", "", "", "", "", "Click Me")
        assert 'has-text("Click Me")' in selector

    def test_escape_attr(self):
        cm = ContextManager()
        assert cm._escape_attr('value"with"quotes') == 'value\\"with\\"quotes'
        assert cm._escape_attr("value\nwith\nnewlines") == "value with newlines"

    def test_get_element_by_index(self):
        cm = ContextManager()
        elem = ElementInfo(
            role="button",
            name="Test",
            text="",
            tag="button",
            attributes={},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="#test",
            index=5,
        )
        cm._element_cache[5] = elem

        assert cm.get_element_by_index(5) == elem
        assert cm.get_element_by_index(10) is None

    def test_get_current_context(self):
        cm = ContextManager()
        assert cm.get_current_context() is None

        ctx = PageContext(url="https://example.com", title="Test")
        cm._current_context = ctx
        assert cm.get_current_context() == ctx

    def test_clear_cache(self):
        cm = ContextManager()
        cm._element_cache[0] = MagicMock()
        cm._current_context = MagicMock()

        cm.clear_cache()

        assert cm._element_cache == {}
        assert cm._current_context is None


class TestContextManagerAsync:
    """Async tests for ContextManager."""

    @pytest.mark.asyncio
    async def test_extract_context_basic(self):
        cm = ContextManager()

        mock_page = AsyncMock()
        mock_page.url = "https://example.com"
        mock_page.title = AsyncMock(return_value="Example Page")

        mock_locator = AsyncMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_locator.inner_text = AsyncMock(return_value="Page content here")
        mock_locator.first = mock_locator
        mock_locator.nth = MagicMock(return_value=mock_locator)

        mock_page.locator = MagicMock(return_value=mock_locator)

        ctx = await cm.extract_context(mock_page)

        assert ctx.url == "https://example.com"
        assert ctx.title == "Example Page"

    @pytest.mark.asyncio
    async def test_find_element_by_description(self):
        cm = ContextManager()

        elem = ElementInfo(
            role="button",
            name="Submit Form",
            text="Submit",
            tag="button",
            attributes={},
            bounding_box=None,
            is_visible=True,
            is_enabled=True,
            selector="#submit",
            index=0,
        )
        cm._element_cache[0] = elem
        cm._current_context = PageContext(url="https://example.com", title="Test")

        mock_page = AsyncMock()

        found = await cm.find_element_by_description(mock_page, "submit")
        assert found == elem

        not_found = await cm.find_element_by_description(mock_page, "nonexistent")
        assert not_found is None
