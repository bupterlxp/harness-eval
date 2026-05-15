import pytest
from unittest.mock import patch
from playwright.sync_api import Page
from harness.domain.popup import PopupHandler, PopupType


def test_popup_detection():
    """Test popup detection functionality"""
    # Mock page object
    mock_page = type('MockPage', (), {
        'query_selector_all': lambda self, selector: [],
        'query_selector': lambda self, selector: None
    })()

    handler = PopupHandler(mock_page)

    # Test cookie popup patterns
    with patch.object(handler, '_find_elements_by_pattern') as mock_find:
        mock_find.return_value = ["#cookie-consent"]

        popups = handler.detect_popups()
        assert len(popups) >= 1
        assert any(p[1] == PopupType.COOKIE_CONSENT for p in popups)


def test_close_cookie_consent():
    """Test closing cookie consent popups"""
    # Mock page with cookie consent elements
    mock_button = type('MockButton', (), {
        'text_content': lambda self: "Accept All Cookies",
        'click': lambda self: None
    })()

    mock_element = type('MockElement', (), {
        'query_selector_all': lambda self, selector: [mock_button],
        'get_attribute': lambda self, attr: 'cookie-consent-banner'
    })()

    mock_page = type('MockPage', (), {
        'query_selector_all': lambda self, selector: [mock_element],
        'keyboard': type('MockKeyboard', (), {'press': lambda self, key: None})()
    })()

    handler = PopupHandler(mock_page)

    with patch.object(handler, '_find_elements_by_pattern') as mock_find:
        mock_find.return_value = ["#cookie-consent"]

        # Test close success
        with patch.object(mock_button, 'click') as mock_click:
            success = handler.close_cookie_consent("#cookie-consent")
            assert success is True
            mock_click.assert_called_once()


def test_close_modal():
    """Test closing modal dialogs"""
    mock_page = type('MockPage', (), {
        'query_selector': lambda self, selector: None,
        'keyboard': type('MockKeyboard', (), {'press': lambda self, key: None})()
    })()

    handler = PopupHandler(mock_page)

    # Test escape key fallback
    with patch.object(mock_page.keyboard, 'press') as mock_press:
        success = handler._close_modal(".modal")
        assert success is True
        mock_press.assert_called_once_with("Escape")


def test_popup_auto_close():
    """Test automatic popup closing"""
    mock_page = type('MockPage', (), {
        'query_selector_all': lambda self, pattern: [],
        'query_selector': lambda self, selector: None,
        'keyboard': type('MockKeyboard', (), {'press': lambda self, key: None})()
    })()

    handler = PopupHandler(mock_page)

    # Test all popup types detected
    with patch.object(handler, 'detect_popups') as mock_detect:
        mock_detect.return_value = [
            ("#cookie-banner", PopupType.COOKIE_CONSENT),
            (".confirm-modal", PopupType.MODAL),
            (".success-message", PopupType.SUCCESS)
        ]

        with patch.object(handler, 'close_popup') as mock_close:
            mock_close.return_value = True
            count = handler.close_all_popups()
            assert count == 3
            assert mock_close.call_count == 3