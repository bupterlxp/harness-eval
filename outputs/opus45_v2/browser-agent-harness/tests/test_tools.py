"""Tests for the Tool Registry module."""

import tempfile
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock

from harness.tools import ToolRegistry, ToolDefinition, ToolResult, ToolCategory


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_success_result(self):
        result = ToolResult(success=True, data={"key": "value"})
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_error_result(self):
        result = ToolResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_result_with_screenshot(self):
        result = ToolResult(success=True, screenshot_path="/path/to/screenshot.png")
        assert result.screenshot_path == "/path/to/screenshot.png"


class TestToolDefinition:
    """Tests for ToolDefinition dataclass."""

    def test_tool_definition_creation(self):
        async def handler(**params):
            return ToolResult(success=True)

        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.UTILITY,
            parameters={"param1": {"type": "string", "required": True}},
            handler=handler,
        )

        assert tool.name == "test_tool"
        assert tool.category == ToolCategory.UTILITY

    def test_to_schema(self):
        async def handler(**params):
            return ToolResult(success=True)

        tool = ToolDefinition(
            name="click",
            description="Click an element",
            category=ToolCategory.INTERACTION,
            parameters={
                "selector": {"type": "string", "description": "CSS selector", "required": True},
            },
            handler=handler,
        )

        schema = tool.to_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "click"
        assert "selector" in schema["function"]["parameters"]["properties"]
        assert "selector" in schema["function"]["parameters"]["required"]


class TestToolRegistry:
    """Tests for ToolRegistry."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init_registers_default_tools(self, temp_dir):
        registry = ToolRegistry(temp_dir)

        assert registry.get_tool("navigate") is not None
        assert registry.get_tool("click") is not None
        assert registry.get_tool("type_text") is not None
        assert registry.get_tool("screenshot") is not None
        assert registry.get_tool("extract_text") is not None

    def test_list_tools(self, temp_dir):
        registry = ToolRegistry(temp_dir)
        tools = registry.list_tools()

        assert len(tools) > 0
        tool_names = [t.name for t in tools]
        assert "navigate" in tool_names
        assert "click" in tool_names

    def test_get_tools_schema(self, temp_dir):
        registry = ToolRegistry(temp_dir)
        schemas = registry.get_tools_schema()

        assert len(schemas) > 0
        assert all(s["type"] == "function" for s in schemas)

    def test_register_custom_tool(self, temp_dir):
        registry = ToolRegistry(temp_dir)

        async def custom_handler(**params):
            return ToolResult(success=True, data={"custom": True})

        tool = ToolDefinition(
            name="custom_tool",
            description="A custom tool",
            category=ToolCategory.UTILITY,
            parameters={},
            handler=custom_handler,
        )
        registry.register(tool)

        assert registry.get_tool("custom_tool") is not None

    def test_get_unknown_tool(self, temp_dir):
        registry = ToolRegistry(temp_dir)
        assert registry.get_tool("nonexistent") is None

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, temp_dir):
        registry = ToolRegistry(temp_dir)
        result = await registry.execute("nonexistent_tool")

        assert result.success is False
        assert "Unknown tool" in result.error


class TestToolRegistryAsync:
    """Async tests for ToolRegistry tool execution."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.url = "https://example.com"
        page.title = AsyncMock(return_value="Test Page")
        page.goto = AsyncMock()
        page.go_back = AsyncMock()
        page.go_forward = AsyncMock()
        page.reload = AsyncMock()
        page.screenshot = AsyncMock()
        page.keyboard = AsyncMock()
        page.mouse = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        mock_locator = AsyncMock()
        mock_locator.wait_for = AsyncMock()
        mock_locator.click = AsyncMock()
        mock_locator.fill = AsyncMock()
        mock_locator.type = AsyncMock()
        mock_locator.check = AsyncMock()
        mock_locator.uncheck = AsyncMock()
        mock_locator.hover = AsyncMock()
        mock_locator.inner_text = AsyncMock(return_value="Test text")
        mock_locator.get_attribute = AsyncMock(return_value=None)
        mock_locator.is_visible = AsyncMock(return_value=True)
        mock_locator.is_enabled = AsyncMock(return_value=True)
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.nth = MagicMock(return_value=mock_locator)
        mock_locator.first = mock_locator

        page.locator = MagicMock(return_value=mock_locator)
        page.get_by_text = MagicMock(return_value=mock_locator)

        return page

    @pytest.mark.asyncio
    async def test_navigate(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_page.goto.return_value = mock_response

        result = await registry.execute("navigate", url="https://example.com")

        assert result.success is True
        mock_page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_click(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("click", selector="#button")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_type_text(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("type_text", selector="#input", text="Hello")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_screenshot(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("screenshot")

        assert result.success is True
        assert result.screenshot_path is not None
        assert "screenshot" in result.screenshot_path

    @pytest.mark.asyncio
    async def test_get_page_info(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("get_page_info")

        assert result.success is True
        assert result.data["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_extract_text(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("extract_text", selector="#content")

        assert result.success is True
        assert "text" in result.data

    @pytest.mark.asyncio
    async def test_scroll(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("scroll", direction="down", amount=500)

        assert result.success is True
        mock_page.mouse.wheel.assert_called_once()

    @pytest.mark.asyncio
    async def test_press_key(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("press_key", key="Enter")

        assert result.success is True
        mock_page.keyboard.press.assert_called_with("Enter")

    @pytest.mark.asyncio
    async def test_go_back(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("go_back")

        assert result.success is True
        mock_page.go_back.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh(self, temp_dir, mock_page):
        registry = ToolRegistry(temp_dir)
        registry.set_page(mock_page)

        result = await registry.execute("refresh")

        assert result.success is True
        mock_page.reload.assert_called_once()
