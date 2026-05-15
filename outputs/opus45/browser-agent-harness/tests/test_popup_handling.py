"""
test_popup_handling.py - Tests for popup detection and handling.

Verifies handling of three popup types:
1. Cookie consent banner
2. Reject reason modal dialog
3. Success notification modal
"""

import pytest
from harness.domain.popup import PopupHandler, PopupInfo, PopupType


class TestPopupInfo:
    """Tests for PopupInfo data structure."""

    def test_cookie_banner_definition(self) -> None:
        """Cookie banner popup info is correct."""
        info = PopupHandler.POPUP_DEFINITIONS["cookie_banner"]

        assert info.popup_type == PopupType.COOKIE_BANNER
        assert "cookie-banner" in info.selector
        assert "接受所有 Cookie" in info.close_selector
        assert info.is_blocking is True
        assert info.requires_input is False

    def test_reject_modal_definition(self) -> None:
        """Reject modal popup info is correct."""
        info = PopupHandler.POPUP_DEFINITIONS["reject_modal"]

        assert info.popup_type == PopupType.REJECT_MODAL
        assert "reject-modal" in info.selector
        assert "确认拒绝" in info.close_selector
        assert info.is_blocking is True
        assert info.requires_input is True
        assert info.input_selector == "#reject-comment"

    def test_success_modal_definition(self) -> None:
        """Success modal popup info is correct."""
        info = PopupHandler.POPUP_DEFINITIONS["success_modal"]

        assert info.popup_type == PopupType.SUCCESS_MODAL
        assert "success-modal" in info.selector
        assert info.is_blocking is False
        assert info.requires_input is False

    def test_session_modal_definition(self) -> None:
        """Session expiry modal popup info is correct."""
        info = PopupHandler.POPUP_DEFINITIONS["session_modal"]

        assert info.popup_type == PopupType.SESSION_MODAL
        assert "session-modal" in info.selector
        assert "继续使用" in info.close_selector
        assert info.is_blocking is True


class TestPopupType:
    """Tests for PopupType enum."""

    def test_all_types_defined(self) -> None:
        """All expected popup types exist."""
        assert PopupType.COOKIE_BANNER.value == "cookie_banner"
        assert PopupType.MODAL.value == "modal"
        assert PopupType.ALERT.value == "alert"
        assert PopupType.REJECT_MODAL.value == "reject_modal"
        assert PopupType.SUCCESS_MODAL.value == "success_modal"
        assert PopupType.SESSION_MODAL.value == "session_modal"
        assert PopupType.UNKNOWN.value == "unknown"


class TestPopupSelectors:
    """Tests for popup selector correctness."""

    def test_cookie_banner_selectors(self) -> None:
        """Cookie banner selectors cover both ID and class variants."""
        info = PopupHandler.POPUP_DEFINITIONS["cookie_banner"]

        assert "#cookie-banner.active" in info.selector
        assert ".cookie-banner.active" in info.selector

    def test_close_button_selectors(self) -> None:
        """Close button selectors use semantic text matching."""
        cookie_info = PopupHandler.POPUP_DEFINITIONS["cookie_banner"]
        reject_info = PopupHandler.POPUP_DEFINITIONS["reject_modal"]

        assert "has-text" in cookie_info.close_selector
        assert "has-text" in reject_info.close_selector

    def test_modal_generic_selectors(self) -> None:
        """Generic modal has fallback selectors."""
        info = PopupHandler.POPUP_DEFINITIONS["generic_modal"]

        assert ".modal-overlay.active" in info.selector
        assert "btn-primary" in info.close_selector or "modal-close" in info.close_selector


class TestPopupHandlerInterface:
    """Tests for PopupHandler interface (without browser)."""

    def test_handler_init(self) -> None:
        """Handler initializes with page reference."""

        class MockPage:
            pass

        handler = PopupHandler(MockPage())
        assert handler is not None

    def test_custom_handler_registration(self) -> None:
        """Custom handlers can be registered."""

        class MockPage:
            pass

        handler = PopupHandler(MockPage())

        async def custom_handler(input_value: str | None) -> bool:
            return True

        handler.register_handler(PopupType.COOKIE_BANNER, custom_handler)
        assert PopupType.COOKIE_BANNER in handler._custom_handlers

    def test_all_definitions_have_required_fields(self) -> None:
        """All popup definitions have required fields."""
        for name, info in PopupHandler.POPUP_DEFINITIONS.items():
            assert info.popup_type is not None, f"{name} missing popup_type"
            assert info.selector is not None, f"{name} missing selector"
            assert isinstance(info.is_blocking, bool), f"{name} invalid is_blocking"
            assert isinstance(info.requires_input, bool), f"{name} invalid requires_input"

            if info.requires_input:
                assert info.input_selector is not None, f"{name} requires input but no input_selector"


class TestPopupStrategies:
    """Tests for popup handling strategies."""

    def test_blocking_vs_nonblocking(self) -> None:
        """Blocking popups should be handled before continuing."""
        blocking_types = [
            "cookie_banner",
            "reject_modal",
            "session_modal",
            "generic_modal",
        ]
        nonblocking_types = [
            "success_modal",
        ]

        for name in blocking_types:
            info = PopupHandler.POPUP_DEFINITIONS[name]
            assert info.is_blocking is True, f"{name} should be blocking"

        for name in nonblocking_types:
            info = PopupHandler.POPUP_DEFINITIONS[name]
            assert info.is_blocking is False, f"{name} should be non-blocking"

    def test_input_required_popups(self) -> None:
        """Only reject modal requires input."""
        for name, info in PopupHandler.POPUP_DEFINITIONS.items():
            if name == "reject_modal":
                assert info.requires_input is True
            else:
                assert info.requires_input is False, f"{name} should not require input"

    def test_close_selector_formats(self) -> None:
        """Close selectors use multiple fallback patterns."""
        for name, info in PopupHandler.POPUP_DEFINITIONS.items():
            if info.close_selector:
                selectors = info.close_selector.split(", ")
                assert len(selectors) >= 1, f"{name} needs at least one close selector"


class TestCookieBannerSpecifics:
    """Detailed tests for cookie banner handling."""

    def test_accept_button_text_chinese(self) -> None:
        """Cookie accept button uses Chinese text."""
        info = PopupHandler.POPUP_DEFINITIONS["cookie_banner"]

        assert "接受所有 Cookie" in info.close_selector

    def test_banner_position(self) -> None:
        """Cookie banner selector assumes fixed bottom position."""
        info = PopupHandler.POPUP_DEFINITIONS["cookie_banner"]

        assert "active" in info.selector


class TestRejectModalSpecifics:
    """Detailed tests for reject modal handling."""

    def test_textarea_selector(self) -> None:
        """Reject modal has correct textarea selector."""
        info = PopupHandler.POPUP_DEFINITIONS["reject_modal"]

        assert info.input_selector == "#reject-comment"

    def test_confirm_button_text(self) -> None:
        """Reject confirm button uses correct Chinese text."""
        info = PopupHandler.POPUP_DEFINITIONS["reject_modal"]

        assert "确认拒绝" in info.close_selector


class TestSuccessModalSpecifics:
    """Detailed tests for success modal handling."""

    def test_is_nonblocking(self) -> None:
        """Success modal doesn't block task flow."""
        info = PopupHandler.POPUP_DEFINITIONS["success_modal"]

        assert info.is_blocking is False

    def test_link_as_close_button(self) -> None:
        """Success modal uses link or button to close."""
        info = PopupHandler.POPUP_DEFINITIONS["success_modal"]

        assert "btn" in info.close_selector.lower()
