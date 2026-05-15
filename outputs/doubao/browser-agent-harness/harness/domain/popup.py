import re
from typing import List, Dict, Optional, Tuple
from playwright.sync_api import Page

from .schemas import PopupType


class PopupHandler:
    """Handles detection and closing of various popup types"""

    # Common popup selectors patterns
    COOKIE_PATTERNS = [
        r".*cookie.*",
        r".*consent.*",
        r".*gdpr.*",
        r".*accept.*cookie.*",
        r".*agree.*cookie.*"
    ]

    MODAL_PATTERNS = [
        r".*modal.*",
        r".*dialog.*",
        r".*popup.*"
    ]

    SUCCESS_PATTERNS = [
        r".*success.*",
        r".*complete.*",
        r".*done.*"
    ]

    ERROR_PATTERNS = [
        r".*error.*",
        r".*fail.*",
        r".*warning.*"
    ]

    def __init__(self, page: Page):
        self.page = page

    def detect_popups(self) -> List[Tuple[str, PopupType]]:
        """Detect all popups on current page"""
        popups = []

        # Check for cookie consent banners
        cookie_selectors = self._find_elements_by_pattern(self.COOKIE_PATTERNS)
        for selector in cookie_selectors:
            popups.append((selector, PopupType.COOKIE_CONSENT))

        # Check for modal dialogs
        modal_selectors = self._find_elements_by_pattern(self.MODAL_PATTERNS)
        for selector in modal_selectors:
            popups.append((selector, PopupType.MODAL))

        # Check for success messages
        success_selectors = self._find_elements_by_pattern(self.SUCCESS_PATTERNS)
        for selector in success_selectors:
            popups.append((selector, PopupType.SUCCESS))

        # Check for error messages
        error_selectors = self._find_elements_by_pattern(self.ERROR_PATTERNS)
        for selector in error_selectors:
            popups.append((selector, PopupType.ERROR))

        return popups

    def close_popup(self, selector: str, popup_type: PopupType) -> bool:
        """Close popup using appropriate strategy"""
        try:
            # Different strategies for different popup types
            if popup_type == PopupType.COOKIE_CONSENT:
                return self._close_cookie_consent(selector)
            elif popup_type == PopupType.MODAL:
                return self._close_modal(selector)
            elif popup_type in [PopupType.SUCCESS, PopupType.ERROR]:
                return self._close_alert(selector)
            else:
                # Default click strategy
                self.page.click(selector)
                return True
        except Exception as e:
            print(f"Failed to close popup {selector} ({popup_type}): {e}")
            return False

    def close_all_popups(self) -> int:
        """Detect and close all popups on page"""
        closed_count = 0
        popups = self.detect_popups()

        for selector, popup_type in popups:
            if self.close_popup(selector, popup_type):
                closed_count += 1

        return closed_count

    def _find_elements_by_pattern(self, patterns: List[str]) -> List[str]:
        """Find elements matching pattern in id, class, or text"""
        selectors = []

        # Check IDs and classes
        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)

            # Check by id
            try:
                elements = self.page.query_selector_all(f"[id*='{pattern}']")
                for elem in elements:
                    selectors.append(f"#{elem.get_attribute('id')}")
            except:
                pass

            # Check by class
            try:
                elements = self.page.query_selector_all(f"[class*='{pattern}']")
                for elem in elements:
                    classes = elem.get_attribute('class') or ''
                    for cls in classes.split():
                        if regex.search(cls.lower()):
                            selectors.append(f".{cls}")
            except:
                pass

        # Check by text content
        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)
            try:
                elements = self.page.query_selector_all("*:has-text('')")
                for elem in elements:
                    text = elem.text_content() or ''
                    if regex.search(text.lower()):
                        # Try to find a close button
                        button = elem.query_selector("button, [type='button'], .close")
                        if button:
                            selectors.append(button.get_attribute('id') or
                                           button.get_attribute('class') or
                                           "button")
            except:
                pass

        return list(set(selectors))

    def _close_cookie_consent(self, selector: str) -> bool:
        """Close cookie consent banner"""
        try:
            # Look for accept/allow buttons
            buttons = self.page.query_selector_all(f"{selector} button")
            for btn in buttons:
                text = btn.text_content().lower()
                if any(word in text for word in ["accept", "allow", "agree", "ok", "got it"]):
                    btn.click()
                    return True

            # If no specific button found, just click the selector
            self.page.click(selector)
            return True
        except Exception as e:
            print(f"Cookie consent close failed: {e}")
            return False

    def _close_modal(self, selector: str) -> bool:
        """Close modal dialog"""
        try:
            # Look for close buttons
            close_selectors = ["button.close", ".modal-header .close", ".modal-footer .btn-secondary"]

            for close_selector in close_selectors:
                try:
                    close_btn = self.page.query_selector(f"{selector} {close_selector}")
                    if close_btn:
                        close_btn.click()
                        return True
                except:
                    continue

            # If modal has an overlay, click that
            overlay = self.page.query_selector(".modal-backdrop, .modal-overlay")
            if overlay:
                overlay.click()
                return True

            # Fallback: click escape key
            self.page.keyboard.press("Escape")
            return True
        except Exception as e:
            print(f"Modal close failed: {e}")
            return False

    def _close_alert(self, selector: str) -> bool:
        """Close alert/notification"""
        try:
            # Look for close buttons
            close_btn = self.page.query_selector(f"{selector} .close, {selector} button")
            if close_btn:
                close_btn.click()
                return True

            # Auto-dismiss alerts
            self.page.evaluate(f"document.querySelector('{selector}').remove()")
            return True
        except Exception as e:
            print(f"Alert close failed: {e}")
            return False