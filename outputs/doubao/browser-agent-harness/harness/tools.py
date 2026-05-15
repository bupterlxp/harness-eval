import os
import time
from typing import Dict, Optional, List, Any
from datetime import datetime
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from dataclasses import asdict

from .schemas import TaskStatus, PopupType, StepResult, PageState


class BrowserTools:
    """Tool registry for browser automation operations"""

    def __init__(self, config: Dict):
        self.config = config
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.download_dir = config.get("download_dir", "downloads")
        os.makedirs(self.download_dir, exist_ok=True)

    def launch_browser(self) -> None:
        """Launch browser instance"""
        if not self.browser:
            playwright = sync_playwright().start()
            self.browser = playwright.chromium.launch(headless=False)
            self.context = self.browser.new_context(
                viewport={"width": self.config["viewport_width"], "height": self.config["viewport_height"]}
            )
            self.page = self.context.new_page()
            self.page.set_default_timeout(self.config["default_timeout"])

    def close_browser(self) -> None:
        """Close browser instance"""
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()

    def navigate(self, url: str, wait_until: str = "networkidle") -> StepResult:
        """Navigate to a URL"""
        if not self.page:
            raise RuntimeError("Browser not launched")

        try:
            self.page.goto(url, wait_until=wait_until)
            return StepResult(
                step_id=0,
                status=TaskStatus.COMPLETED,
                url=url,
                data={"navigation": "success"}
            )
        except Exception as e:
            return StepResult(
                step_id=0,
                status=TaskStatus.FAILED,
                url=url,
                error_message=str(e)
            )

    def wait_for_element(self, selector: str, timeout: Optional[int] = None) -> bool:
        """Wait for element to be visible"""
        if not self.page:
            return False

        try:
            self.page.wait_for_selector(selector, timeout=timeout or self.config["default_timeout"])
            return True
        except Exception:
            return False

    def click(self, selector: str, wait_for_navigation: bool = False) -> StepResult:
        """Click an element"""
        if not self.page:
            raise RuntimeError("Browser not launched")

        try:
            if wait_for_navigation:
                with self.page.expect_navigation(wait_until="networkidle"):
                    self.page.click(selector)
            else:
                self.page.click(selector)

            return StepResult(
                step_id=0,
                status=TaskStatus.COMPLETED,
                url=self.page.url,
                data={"clicked": selector}
            )
        except Exception as e:
            return StepResult(
                step_id=0,
                status=TaskStatus.FAILED,
                url=self.page.url if self.page else "",
                error_message=str(e)
            )

    def fill(self, selector: str, text: str) -> StepResult:
        """Fill input field"""
        if not self.page:
            raise RuntimeError("Browser not launched")

        try:
            self.page.fill(selector, text)
            return StepResult(
                step_id=0,
                status=TaskStatus.COMPLETED,
                url=self.page.url,
                data={"filled": selector, "text_length": len(text)}
            )
        except Exception as e:
            return StepResult(
                step_id=0,
                status=TaskStatus.FAILED,
                url=self.page.url if self.page else "",
                error_message=str(e)
            )

    def select(self, selector: str, value: str) -> StepResult:
        """Select dropdown option"""
        if not self.page:
            raise RuntimeError("Browser not launched")

        try:
            self.page.select_option(selector, value)
            return StepResult(
                step_id=0,
                status=TaskStatus.COMPLETED,
                url=self.page.url,
                data={"selected": selector, "value": value}
            )
        except Exception as e:
            return StepResult(
                step_id=0,
                status=TaskStatus.FAILED,
                url=self.page.url if self.page else "",
                error_message=str(e)
            )

    def extract_text(self, selector: str) -> Optional[str]:
        """Extract text from element"""
        if not self.page:
            return None

        try:
            return self.page.text_content(selector)
        except Exception:
            return None

    def extract_all_text(self, selector: str) -> List[str]:
        """Extract all text from elements matching selector"""
        if not self.page:
            return []

        try:
            elements = self.page.query_selector_all(selector)
            return [elem.text_content().strip() for elem in elements]
        except Exception:
            return []

    def screenshot(self, path: str) -> Optional[str]:
        """Take screenshot"""
        if not self.page:
            return None

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.page.screenshot(path=path, full_page=True)
            return path
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return None

    def download_file(self, trigger_selector: str) -> Optional[str]:
        """Download file and save to download directory"""
        if not self.page:
            return None

        try:
            with self.page.expect_download() as download_info:
                self.page.click(trigger_selector)
            download = download_info.value

            filepath = os.path.join(self.download_dir, download.suggested_filename())
            download.save_as(filepath)
            return filepath
        except Exception as e:
            print(f"Download failed: {e}")
            return None

    def get_page_state(self) -> PageState:
        """Get current page state summary"""
        if not self.page:
            return PageState(url="", title="", loaded=False)

        try:
            title = self.page.title()
            interactive_elements = []

            # Get common interactive elements
            inputs = self.page.query_selector_all("input, select, textarea, button, a[href]")
            for elem in inputs:
                try:
                    selector = elem.get_attribute("data-testid") or elem.get_attribute("id") or elem.get_attribute("name")
                    if selector:
                        interactive_elements.append(selector)
                except:
                    pass

            key_text = self.page.query_selector_all("h1, h2, h3, .card, .stat, .count")
            key_text_content = [elem.text_content().strip() for elem in key_text if elem.text_content().strip()]

            return PageState(
                url=self.page.url,
                title=title,
                interactive_elements=interactive_elements,
                key_text_content=key_text_content,
                loaded=True
            )
        except Exception:
            return PageState(url=self.page.url if self.page else "", title="", loaded=False)

    def wait_for_load(self, timeout: Optional[int] = None) -> bool:
        """Wait for page to load completely"""
        if not self.page:
            return False

        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout or self.config["default_timeout"])
            return True
        except Exception:
            return False