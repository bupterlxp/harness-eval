"""
domain/__init__.py - Domain-specific components for short story writing
"""

from harness.domain.tools import get_domain_tools
from harness.domain.prompts import PROMPTS

__all__ = ["get_domain_tools", "PROMPTS"]
