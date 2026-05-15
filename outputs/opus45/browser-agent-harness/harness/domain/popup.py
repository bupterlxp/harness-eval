"""
domain/popup.py - Popup detection and handling strategies.

Handles three types of popups:
1. Cookie consent banner (bottom fixed banner)
2. Modal dialogs (centered overlays)
3. Alert/toast messages (temporary notifications)
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine


class PopupType(str, Enum):
    """Types of popups the harness can handle."""
    COOKIE_BANNER = "cookie_banner"
    MODAL = "modal"
    ALERT = "alert"
    REJECT_MODAL = "reject_modal"
    SUCCESS_MODAL = "success_modal"
    SESSION_MODAL = "session_modal"
    UNKNOWN = "unknown"


@dataclass
class PopupInfo:
    """Information about a detected popup."""
    popup_type: PopupType
    selector: str
    close_selector: str | None
    is_blocking: bool
    requires_input: bool = False
    input_selector: str | None = None


class PopupHandler:
    """
    Detects and handles popups without blocking the main task flow.

    Strategy:
    1. Non-blocking detection - quick check after page load
    2. Auto-close for known popup types
    3. Continue original task after popup is handled
    """

    POPUP_DEFINITIONS: dict[str, PopupInfo] = {
        "cookie_banner": PopupInfo(
            popup_type=PopupType.COOKIE_BANNER,
            selector="#cookie-banner.active, .cookie-banner.active",
            close_selector="button:has-text('接受所有 Cookie'), button.accept, .cookie-banner .btn-primary",
            is_blocking=True,
            requires_input=False,
        ),
        "reject_modal": PopupInfo(
            popup_type=PopupType.REJECT_MODAL,
            selector="#reject-modal.active",
            close_selector="button:has-text('确认拒绝'), #reject-modal .btn-danger",
            is_blocking=True,
            requires_input=True,
            input_selector="#reject-comment",
        ),
        "success_modal": PopupInfo(
            popup_type=PopupType.SUCCESS_MODAL,
            selector="#success-modal.active",
            close_selector="#success-modal a.btn-primary, #success-modal .btn",
            is_blocking=False,
            requires_input=False,
        ),
        "session_modal": PopupInfo(
            popup_type=PopupType.SESSION_MODAL,
            selector="#session-modal.active",
            close_selector="button:has-text('继续使用'), #session-modal .btn-primary",
            is_blocking=True,
            requires_input=False,
        ),
        "generic_modal": PopupInfo(
            popup_type=PopupType.MODAL,
            selector=".modal-overlay.active",
            close_selector=".modal .btn-primary, .modal-close, button:has-text('确定'), button:has-text('关闭')",
            is_blocking=True,
            requires_input=False,
        ),
    }

    def __init__(self, page: Any) -> None:
        self._page = page
        self._custom_handlers: dict[PopupType, Callable[..., Coroutine[Any, Any, bool]]] = {}

    def register_handler(
        self,
        popup_type: PopupType,
        handler: Callable[..., Coroutine[Any, Any, bool]],
    ) -> None:
        """Register a custom handler for a popup type."""
        self._custom_handlers[popup_type] = handler

    async def detect(self) -> PopupInfo | None:
        """Detect if any popup is currently visible."""
        for name, info in self.POPUP_DEFINITIONS.items():
            try:
                selectors = info.selector.split(", ")
                for sel in selectors:
                    if await self._page.is_visible(sel):
                        return info
            except Exception:
                continue

        return None

    async def detect_type(self) -> PopupType | None:
        """Detect popup type without full info."""
        info = await self.detect()
        return info.popup_type if info else None

    async def close(
        self,
        popup_type: PopupType | str | None = None,
        input_value: str | None = None,
    ) -> bool:
        """
        Close a popup, optionally filling input first.

        Args:
            popup_type: Specific popup to close, or None to auto-detect
            input_value: Value to fill if popup requires input

        Returns:
            True if popup was closed successfully
        """
        if popup_type in self._custom_handlers:
            return await self._custom_handlers[popup_type](input_value)

        if popup_type is None:
            info = await self.detect()
        elif isinstance(popup_type, str):
            info = self.POPUP_DEFINITIONS.get(popup_type)
        else:
            info = next(
                (i for i in self.POPUP_DEFINITIONS.values() if i.popup_type == popup_type),
                None,
            )

        if not info:
            return False

        try:
            if info.requires_input and info.input_selector and input_value:
                await self._page.fill(info.input_selector, input_value)
                await asyncio.sleep(0.2)

            if info.close_selector:
                close_selectors = info.close_selector.split(", ")
                for sel in close_selectors:
                    try:
                        if await self._page.is_visible(sel):
                            await self._page.click(sel, timeout=2000)
                            await asyncio.sleep(0.3)
                            return True
                    except Exception:
                        continue

            return False

        except Exception:
            return False

    async def close_cookie_banner(self) -> bool:
        """Convenience method to close cookie consent banner."""
        return await self.close(PopupType.COOKIE_BANNER)

    async def close_modal(self, input_value: str | None = None) -> bool:
        """Convenience method to close any modal dialog."""
        return await self.close(PopupType.MODAL, input_value)

    async def close_reject_modal(self, reason: str) -> bool:
        """Close reject modal with reason filled in."""
        return await self.close(PopupType.REJECT_MODAL, reason)

    async def dismiss_success_modal(self) -> bool:
        """Dismiss success notification modal."""
        return await self.close(PopupType.SUCCESS_MODAL)

    async def extend_session(self) -> bool:
        """Click continue on session expiry modal."""
        return await self.close(PopupType.SESSION_MODAL)

    async def wait_for_popup(
        self,
        popup_type: PopupType | str,
        timeout_ms: int = 5000,
    ) -> bool:
        """Wait for a specific popup to appear."""
        if isinstance(popup_type, str):
            info = self.POPUP_DEFINITIONS.get(popup_type)
        else:
            info = next(
                (i for i in self.POPUP_DEFINITIONS.values() if i.popup_type == popup_type),
                None,
            )

        if not info:
            return False

        try:
            selectors = info.selector.split(", ")
            selector = ", ".join(selectors)
            await self._page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
            return True
        except Exception:
            return False

    async def wait_for_popup_close(
        self,
        popup_type: PopupType | str,
        timeout_ms: int = 5000,
    ) -> bool:
        """Wait for a popup to close/disappear."""
        if isinstance(popup_type, str):
            info = self.POPUP_DEFINITIONS.get(popup_type)
        else:
            info = next(
                (i for i in self.POPUP_DEFINITIONS.values() if i.popup_type == popup_type),
                None,
            )

        if not info:
            return True

        try:
            selectors = info.selector.split(", ")
            for sel in selectors:
                try:
                    await self._page.wait_for_selector(sel, state="hidden", timeout=timeout_ms)
                except Exception:
                    continue
            return True
        except Exception:
            return False

    async def handle_all_blocking(self) -> int:
        """
        Handle all currently visible blocking popups.

        Returns the number of popups closed.
        """
        closed = 0
        max_iterations = 5

        for _ in range(max_iterations):
            info = await self.detect()
            if not info or not info.is_blocking:
                break

            if info.requires_input:
                break

            if await self.close(info.popup_type):
                closed += 1
                await asyncio.sleep(0.3)
            else:
                break

        return closed

    async def is_popup_visible(self, popup_type: PopupType | str) -> bool:
        """Check if a specific popup type is visible."""
        if isinstance(popup_type, str):
            info = self.POPUP_DEFINITIONS.get(popup_type)
        else:
            info = next(
                (i for i in self.POPUP_DEFINITIONS.values() if i.popup_type == popup_type),
                None,
            )

        if not info:
            return False

        try:
            selectors = info.selector.split(", ")
            for sel in selectors:
                if await self._page.is_visible(sel):
                    return True
        except Exception:
            pass

        return False
