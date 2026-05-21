"""Tests for the Lifecycle Hooks module."""

import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock

from harness.lifecycle import LifecycleHooks, LifecycleEvent, LifecycleEventRecord


class TestLifecycleEventRecord:
    """Tests for LifecycleEventRecord."""

    def test_record_creation(self):
        record = LifecycleEventRecord(
            event_type=LifecycleEvent.NAVIGATION_END,
            timestamp="2024-01-01T00:00:00",
            data={"url": "https://example.com"},
        )
        assert record.event_type == LifecycleEvent.NAVIGATION_END
        assert record.data["url"] == "https://example.com"

    def test_to_dict(self):
        record = LifecycleEventRecord(
            event_type=LifecycleEvent.DIALOG_OPENED,
            timestamp="2024-01-01T00:00:00",
            data={"type": "alert", "message": "Hello"},
        )
        data = record.to_dict()

        assert data["event_type"] == "dialog_opened"
        assert data["data"]["type"] == "alert"


class TestLifecycleHooks:
    """Tests for LifecycleHooks."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.url = "https://example.com"
        page.on = MagicMock()
        page.wait_for_load_state = AsyncMock()
        page.screenshot = AsyncMock()

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_locator.click = AsyncMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_locator.first = mock_locator

        page.locator = MagicMock(return_value=mock_locator)

        return page

    def test_init(self, temp_dir):
        hooks = LifecycleHooks(temp_dir)

        assert hooks.output_dir == temp_dir
        assert hooks._page is None
        assert len(hooks._event_log) == 0

    def test_set_page(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        assert hooks._page is mock_page
        assert mock_page.on.call_count >= 4

    def test_configure_dialog_handling(self, temp_dir):
        hooks = LifecycleHooks(temp_dir)

        hooks.configure_dialog_handling(
            auto_dismiss=False,
            accept=True,
            prompt_text="test input",
        )

        assert hooks._auto_dismiss_dialogs is False
        assert hooks._dialog_accept is True
        assert hooks._dialog_prompt_text == "test input"

    def test_get_downloads(self, temp_dir):
        hooks = LifecycleHooks(temp_dir)
        hooks._downloads = ["/path/to/file1.pdf", "/path/to/file2.pdf"]

        downloads = hooks.get_downloads()

        assert len(downloads) == 2
        assert "/path/to/file1.pdf" in downloads

    def test_get_event_log(self, temp_dir):
        hooks = LifecycleHooks(temp_dir)
        hooks._record_event(LifecycleEvent.NAVIGATION_END, {"url": "https://example.com"})
        hooks._record_event(LifecycleEvent.LOAD_COMPLETE, {})

        log = hooks.get_event_log()

        assert len(log) == 2
        assert log[0]["event_type"] == "navigation_end"

    def test_clear_event_log(self, temp_dir):
        hooks = LifecycleHooks(temp_dir)
        hooks._record_event(LifecycleEvent.NAVIGATION_END, {})

        hooks.clear_event_log()

        assert len(hooks._event_log) == 0

    def test_register_handler(self, temp_dir):
        hooks = LifecycleHooks(temp_dir)

        async def handler(record):
            pass

        hooks.register_handler(LifecycleEvent.DIALOG_OPENED, handler)

        assert LifecycleEvent.DIALOG_OPENED in hooks._custom_handlers
        assert handler in hooks._custom_handlers[LifecycleEvent.DIALOG_OPENED]


class TestLifecycleHooksAsync:
    """Async tests for LifecycleHooks."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.url = "https://example.com"
        page.on = MagicMock()
        page.wait_for_load_state = AsyncMock()
        page.screenshot = AsyncMock()

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_locator.click = AsyncMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_locator.first = mock_locator

        page.locator = MagicMock(return_value=mock_locator)

        return page

    @pytest.mark.asyncio
    async def test_wait_for_page_ready(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        result = await hooks.wait_for_page_ready()

        assert result is True
        mock_page.wait_for_load_state.assert_called()

    @pytest.mark.asyncio
    async def test_wait_for_page_ready_timeout(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        mock_page.wait_for_load_state.side_effect = Exception("Timeout")

        result = await hooks.wait_for_page_ready()

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_cookie_banner_not_found(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        result = await hooks.handle_cookie_banner()

        assert result is False

    @pytest.mark.asyncio
    async def test_handle_cookie_banner_found(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        mock_locator = AsyncMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        mock_locator.click = AsyncMock()
        mock_page.locator.return_value.first = mock_locator

        result = await hooks.handle_cookie_banner()

        assert result is True

    @pytest.mark.asyncio
    async def test_handle_modal_not_found(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        result = await hooks.handle_modal()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_and_handle_popups(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        handled = await hooks.check_and_handle_popups()

        assert isinstance(handled, list)

    @pytest.mark.asyncio
    async def test_take_timeout_screenshot(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)

        path = await hooks.take_timeout_screenshot()

        assert path is not None
        assert "timeout" in path
        mock_page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_dialog_handler_dismiss(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)
        hooks.configure_dialog_handling(auto_dismiss=True, accept=False)

        mock_dialog = AsyncMock()
        mock_dialog.type = "alert"
        mock_dialog.message = "Test alert"
        mock_dialog.dismiss = AsyncMock()
        mock_dialog.accept = AsyncMock()

        await hooks._on_dialog(mock_dialog)

        mock_dialog.dismiss.assert_called_once()
        assert len(hooks._event_log) >= 1

    @pytest.mark.asyncio
    async def test_dialog_handler_accept(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)
        hooks.configure_dialog_handling(auto_dismiss=True, accept=True)

        mock_dialog = AsyncMock()
        mock_dialog.type = "confirm"
        mock_dialog.message = "Are you sure?"
        mock_dialog.dismiss = AsyncMock()
        mock_dialog.accept = AsyncMock()

        await hooks._on_dialog(mock_dialog)

        mock_dialog.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_dialog_handler_prompt(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)
        hooks.configure_dialog_handling(auto_dismiss=True, accept=True, prompt_text="test input")

        mock_dialog = AsyncMock()
        mock_dialog.type = "prompt"
        mock_dialog.message = "Enter name:"
        mock_dialog.accept = AsyncMock()

        await hooks._on_dialog(mock_dialog)

        mock_dialog.accept.assert_called_with("test input")

    @pytest.mark.asyncio
    async def test_cleanup(self, temp_dir, mock_page):
        hooks = LifecycleHooks(temp_dir)
        hooks.set_page(mock_page)
        hooks._record_event(LifecycleEvent.NAVIGATION_END, {})

        await hooks.cleanup()

        assert len(hooks._event_log) == 0
        assert len(hooks._pending_dialogs) == 0
