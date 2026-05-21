"""Lifecycle Hooks (L) - Page event handling.

Handles navigation events, popup detection, dialog handling, and timeouts.
All handlers are non-blocking to avoid stalling the main execution flow.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Awaitable, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, Dialog, Download, ConsoleMessage


class LifecycleEvent(str, Enum):
    NAVIGATION_START = "navigation_start"
    NAVIGATION_END = "navigation_end"
    DIALOG_OPENED = "dialog_opened"
    DIALOG_CLOSED = "dialog_closed"
    POPUP_DETECTED = "popup_detected"
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_COMPLETED = "download_completed"
    CONSOLE_ERROR = "console_error"
    PAGE_ERROR = "page_error"
    TIMEOUT = "timeout"
    LOAD_COMPLETE = "load_complete"


@dataclass
class LifecycleEventRecord:
    """Record of a lifecycle event."""
    event_type: LifecycleEvent
    timestamp: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "data": self.data,
        }


EventHandler = Callable[[LifecycleEventRecord], Awaitable[None]]


class LifecycleHooks:
    """Manages page lifecycle events with non-blocking handlers.

    Key features:
    - Auto-wait after navigation
    - Non-blocking popup/dialog handling
    - Timeout with screenshot and retry support
    - Download tracking
    """

    DEFAULT_LOAD_TIMEOUT = 30000
    DEFAULT_DIALOG_ACCEPT = False

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self._page: "Page | None" = None
        self._event_log: list[LifecycleEventRecord] = []
        self._custom_handlers: dict[LifecycleEvent, list[EventHandler]] = {}
        self._pending_dialogs: list["Dialog"] = []
        self._downloads: list[str] = []
        self._dialog_handler_installed = False
        self._auto_dismiss_dialogs = True
        self._dialog_accept = self.DEFAULT_DIALOG_ACCEPT
        self._dialog_prompt_text = ""

    def set_page(self, page: "Page") -> None:
        """Set the page and install event listeners."""
        self._page = page
        self._install_listeners()

    @property
    def page(self) -> "Page":
        if self._page is None:
            raise RuntimeError("Page not set in lifecycle hooks")
        return self._page

    def _install_listeners(self) -> None:
        """Install all page event listeners."""
        self.page.on("dialog", self._on_dialog)
        self.page.on("download", self._on_download)
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_page_error)
        self.page.on("load", self._on_load)
        self.page.on("domcontentloaded", self._on_dom_content_loaded)

    def _record_event(self, event_type: LifecycleEvent, data: dict[str, Any] | None = None) -> LifecycleEventRecord:
        """Record a lifecycle event."""
        record = LifecycleEventRecord(
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat(),
            data=data or {},
        )
        self._event_log.append(record)
        return record

    def register_handler(self, event_type: LifecycleEvent, handler: EventHandler) -> None:
        """Register a custom event handler."""
        if event_type not in self._custom_handlers:
            self._custom_handlers[event_type] = []
        self._custom_handlers[event_type].append(handler)

    async def _dispatch_event(self, event_type: LifecycleEvent, data: dict[str, Any] | None = None) -> None:
        """Dispatch event to custom handlers (non-blocking)."""
        record = self._record_event(event_type, data)
        handlers = self._custom_handlers.get(event_type, [])
        for handler in handlers:
            try:
                asyncio.create_task(handler(record))
            except Exception:
                pass

    async def _on_dialog(self, dialog: "Dialog") -> None:
        """Handle browser dialogs (alert/confirm/prompt) non-blocking."""
        dialog_type = dialog.type
        message = dialog.message

        await self._dispatch_event(LifecycleEvent.DIALOG_OPENED, {
            "type": dialog_type,
            "message": message,
        })

        if self._auto_dismiss_dialogs:
            try:
                if self._dialog_accept:
                    if dialog_type == "prompt":
                        await dialog.accept(self._dialog_prompt_text)
                    else:
                        await dialog.accept()
                else:
                    await dialog.dismiss()

                await self._dispatch_event(LifecycleEvent.DIALOG_CLOSED, {
                    "type": dialog_type,
                    "action": "accept" if self._dialog_accept else "dismiss",
                })
            except Exception:
                pass
        else:
            self._pending_dialogs.append(dialog)

    async def _on_download(self, download: "Download") -> None:
        """Handle file downloads."""
        await self._dispatch_event(LifecycleEvent.DOWNLOAD_STARTED, {
            "url": download.url,
            "suggested_filename": download.suggested_filename,
        })

        try:
            path = f"{self.output_dir}/{download.suggested_filename}"
            await download.save_as(path)
            self._downloads.append(path)

            await self._dispatch_event(LifecycleEvent.DOWNLOAD_COMPLETED, {
                "path": path,
                "url": download.url,
            })
        except Exception as e:
            await self._dispatch_event(LifecycleEvent.DOWNLOAD_COMPLETED, {
                "error": str(e),
                "url": download.url,
            })

    async def _on_console(self, message: "ConsoleMessage") -> None:
        """Handle console messages."""
        if message.type == "error":
            await self._dispatch_event(LifecycleEvent.CONSOLE_ERROR, {
                "text": message.text,
            })

    async def _on_page_error(self, error: Exception) -> None:
        """Handle page errors."""
        await self._dispatch_event(LifecycleEvent.PAGE_ERROR, {
            "error": str(error),
        })

    async def _on_load(self) -> None:
        """Handle page load event."""
        await self._dispatch_event(LifecycleEvent.LOAD_COMPLETE, {
            "url": self.page.url,
        })

    async def _on_dom_content_loaded(self) -> None:
        """Handle DOM content loaded event."""
        await self._dispatch_event(LifecycleEvent.NAVIGATION_END, {
            "url": self.page.url,
        })

    async def wait_for_page_ready(self, timeout: int | None = None) -> bool:
        """Wait for page to be ready after navigation."""
        timeout = timeout or self.DEFAULT_LOAD_TIMEOUT
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=timeout)

            try:
                await self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            return True
        except Exception:
            return False

    async def handle_cookie_banner(self) -> bool:
        """Attempt to dismiss cookie consent banners (non-blocking)."""
        cookie_selectors = [
            "button:has-text('Accept')",
            "button:has-text('Accept All')",
            "button:has-text('Accept Cookies')",
            "button:has-text('I Accept')",
            "button:has-text('OK')",
            "button:has-text('Got it')",
            "button:has-text('Agree')",
            "[id*='cookie'] button",
            "[class*='cookie'] button",
            "[id*='consent'] button",
            "[class*='consent'] button",
            "[aria-label*='cookie'] button",
            "[aria-label*='consent'] button",
        ]

        for selector in cookie_selectors:
            try:
                locator = self.page.locator(selector).first
                if await locator.is_visible():
                    await locator.click(timeout=2000)
                    await self._dispatch_event(LifecycleEvent.POPUP_DETECTED, {
                        "type": "cookie_banner",
                        "action": "dismissed",
                        "selector": selector,
                    })
                    return True
            except Exception:
                continue

        return False

    async def handle_modal(self) -> bool:
        """Attempt to close any visible modal/popup (non-blocking)."""
        close_selectors = [
            "[aria-label='Close']",
            "[aria-label='close']",
            "button:has-text('Close')",
            "button:has-text('×')",
            "button:has-text('X')",
            ".modal button.close",
            ".modal [class*='close']",
            "[role='dialog'] button:has-text('Close')",
            "[role='dialog'] [aria-label='Close']",
        ]

        for selector in close_selectors:
            try:
                locator = self.page.locator(selector).first
                if await locator.is_visible():
                    await locator.click(timeout=2000)
                    await self._dispatch_event(LifecycleEvent.POPUP_DETECTED, {
                        "type": "modal",
                        "action": "closed",
                        "selector": selector,
                    })
                    return True
            except Exception:
                continue

        return False

    async def check_and_handle_popups(self) -> list[dict[str, Any]]:
        """Check for and handle any popups/modals (non-blocking).

        Returns list of handled popups.
        """
        handled = []

        if await self.handle_cookie_banner():
            handled.append({"type": "cookie_banner", "action": "dismissed"})
            await asyncio.sleep(0.5)

        if await self.handle_modal():
            handled.append({"type": "modal", "action": "closed"})
            await asyncio.sleep(0.5)

        return handled

    async def take_timeout_screenshot(self) -> str | None:
        """Take a screenshot when timeout occurs."""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            path = f"{self.output_dir}/timeout_{timestamp}.png"
            await self.page.screenshot(path=path)
            await self._dispatch_event(LifecycleEvent.TIMEOUT, {
                "screenshot": path,
            })
            return path
        except Exception:
            return None

    def configure_dialog_handling(
        self,
        auto_dismiss: bool = True,
        accept: bool = False,
        prompt_text: str = ""
    ) -> None:
        """Configure how dialogs are handled."""
        self._auto_dismiss_dialogs = auto_dismiss
        self._dialog_accept = accept
        self._dialog_prompt_text = prompt_text

    def get_downloads(self) -> list[str]:
        """Get list of downloaded file paths."""
        return self._downloads.copy()

    def get_event_log(self) -> list[dict[str, Any]]:
        """Get the event log."""
        return [e.to_dict() for e in self._event_log]

    def clear_event_log(self) -> None:
        """Clear the event log."""
        self._event_log.clear()

    async def cleanup(self) -> None:
        """Cleanup lifecycle hooks."""
        self._event_log.clear()
        self._pending_dialogs.clear()
