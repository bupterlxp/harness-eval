"""
domain/ - Domain-specific modules for browser automation.

Contains:
- tools.py: Browser operation tool implementations
- popup.py: Popup detection and handling strategies
- prompts.py: LLM prompts for element location and data extraction
"""

from harness.domain.tools import BrowserToolExecutor
from harness.domain.popup import PopupHandler, PopupType
from harness.domain.prompts import PromptTemplates

__all__ = [
    "BrowserToolExecutor",
    "PopupHandler",
    "PopupType",
    "PromptTemplates",
]
