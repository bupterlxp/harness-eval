"""
lifecycle.py - Lifecycle hooks for the browser agent harness.

Implements:
- pre_navigate: Record source URL
- post_navigate: Wait for load + popup detection
- pre_click: Verify element visibility and clickability
- on_timeout: Screenshot + record + retry decision
- on_popup: Auto-close strategy
- pre_submit: User confirmation for approval/submit actions
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine

from harness.schemas import PageState, Screenshot


class HookType(str, Enum):
    """Types of lifecycle hooks."""
    PRE_NAVIGATE = "pre_navigate"
    POST_NAVIGATE = "post_navigate"
    PRE_CLICK = "pre_click"
    POST_CLICK = "post_click"
    PRE_FILL = "pre_fill"
    POST_FILL = "post_fill"
    PRE_SUBMIT = "pre_submit"
    POST_SUBMIT = "post_submit"
    ON_TIMEOUT = "on_timeout"
    ON_POPUP = "on_popup"
    ON_ERROR = "on_error"
    ON_RETRY = "on_retry"


@dataclass
class HookContext:
    """Context passed to lifecycle hooks."""
    hook_type: HookType
    step_id: int | None
    current_url: str | None
    target_url: str | None = None
    selector: str | None = None
    action_description: str | None = None
    error: Exception | None = None
    retry_count: int = 0
    max_retries: int = 3
    extra: dict[str, Any] | None = None


@dataclass
class HookResult:
    """Result from a lifecycle hook."""
    should_continue: bool = True
    should_retry: bool = False
    modified_params: dict[str, Any] | None = None
    screenshot_path: str | None = None
    user_approved: bool | None = None
    message: str | None = None


HookHandler = Callable[[HookContext], Coroutine[Any, Any, HookResult]]


class LifecycleManager:
    """Manages lifecycle hooks for browser operations."""

    def __init__(self) -> None:
        self._hooks: dict[HookType, list[HookHandler]] = {ht: [] for ht in HookType}
        self._popup_strategies: dict[str, Callable[..., Coroutine[Any, Any, bool]]] = {}
        self._approval_callback: Callable[[str], Coroutine[Any, Any, bool]] | None = None
        self._screenshot_callback: Callable[[str], Coroutine[Any, Any, str]] | None = None
        self._log_callback: Callable[[str], None] | None = None

    def register_hook(self, hook_type: HookType, handler: HookHandler) -> None:
        """Register a lifecycle hook handler."""
        self._hooks[hook_type].append(handler)

    def set_approval_callback(
        self,
        callback: Callable[[str], Coroutine[Any, Any, bool]],
    ) -> None:
        """Set callback for user approval requests."""
        self._approval_callback = callback

    def set_screenshot_callback(
        self,
        callback: Callable[[str], Coroutine[Any, Any, str]],
    ) -> None:
        """Set callback for taking screenshots."""
        self._screenshot_callback = callback

    def set_log_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for logging messages."""
        self._log_callback = callback

    def _log(self, message: str) -> None:
        """Log a message if callback is set."""
        if self._log_callback:
            self._log_callback(message)

    async def trigger(self, context: HookContext) -> HookResult:
        """Trigger all hooks for a given type."""
        result = HookResult()

        for handler in self._hooks[context.hook_type]:
            try:
                hook_result = await handler(context)
                if not hook_result.should_continue:
                    return hook_result
                if hook_result.should_retry:
                    result.should_retry = True
                if hook_result.modified_params:
                    result.modified_params = {
                        **(result.modified_params or {}),
                        **hook_result.modified_params,
                    }
                if hook_result.screenshot_path:
                    result.screenshot_path = hook_result.screenshot_path
                if hook_result.user_approved is not None:
                    result.user_approved = hook_result.user_approved
                if hook_result.message:
                    result.message = hook_result.message
            except Exception as e:
                self._log(f"Hook error ({context.hook_type}): {e}")
                continue

        return result

    async def pre_navigate(
        self,
        step_id: int | None,
        current_url: str | None,
        target_url: str,
    ) -> HookResult:
        """Trigger pre-navigation hooks."""
        context = HookContext(
            hook_type=HookType.PRE_NAVIGATE,
            step_id=step_id,
            current_url=current_url,
            target_url=target_url,
        )
        self._log(f"Navigating from {current_url} to {target_url}")
        return await self.trigger(context)

    async def post_navigate(
        self,
        step_id: int | None,
        url: str,
        page_state: PageState | None,
    ) -> HookResult:
        """Trigger post-navigation hooks."""
        context = HookContext(
            hook_type=HookType.POST_NAVIGATE,
            step_id=step_id,
            current_url=url,
            extra={"page_state": page_state},
        )
        result = await self.trigger(context)

        if page_state and page_state.has_popup:
            self._log(f"Popup detected: {page_state.popup_type}")
            popup_result = await self.on_popup(
                step_id=step_id,
                url=url,
                popup_type=page_state.popup_type or "unknown",
            )
            if popup_result.message:
                result.message = popup_result.message

        return result

    async def pre_click(
        self,
        step_id: int | None,
        url: str | None,
        selector: str,
        is_visible: bool,
        is_enabled: bool,
    ) -> HookResult:
        """Trigger pre-click hooks. Checks element visibility."""
        context = HookContext(
            hook_type=HookType.PRE_CLICK,
            step_id=step_id,
            current_url=url,
            selector=selector,
            extra={"is_visible": is_visible, "is_enabled": is_enabled},
        )

        if not is_visible:
            self._log(f"Element not visible: {selector}")
            return HookResult(
                should_continue=False,
                message=f"Element not visible: {selector}",
            )

        if not is_enabled:
            self._log(f"Element not enabled: {selector}")
            return HookResult(
                should_continue=False,
                message=f"Element not enabled: {selector}",
            )

        return await self.trigger(context)

    async def pre_submit(
        self,
        step_id: int | None,
        url: str | None,
        selector: str,
        action_description: str,
    ) -> HookResult:
        """Trigger pre-submit hooks. Requires user approval."""
        context = HookContext(
            hook_type=HookType.PRE_SUBMIT,
            step_id=step_id,
            current_url=url,
            selector=selector,
            action_description=action_description,
        )

        result = await self.trigger(context)

        if self._approval_callback:
            approved = await self._approval_callback(action_description)
            result.user_approved = approved
            if not approved:
                result.should_continue = False
                result.message = f"User denied action: {action_description}"
                self._log(result.message)
        else:
            result.user_approved = True

        return result

    async def on_timeout(
        self,
        step_id: int | None,
        url: str | None,
        operation: str,
        retry_count: int,
        max_retries: int,
    ) -> HookResult:
        """Handle timeout events. Decides whether to retry."""
        context = HookContext(
            hook_type=HookType.ON_TIMEOUT,
            step_id=step_id,
            current_url=url,
            action_description=operation,
            retry_count=retry_count,
            max_retries=max_retries,
        )

        self._log(f"Timeout on {operation} (attempt {retry_count + 1}/{max_retries})")

        screenshot_path = None
        if self._screenshot_callback:
            screenshot_path = await self._screenshot_callback(f"timeout_{step_id}_{retry_count}")

        result = await self.trigger(context)
        result.screenshot_path = screenshot_path

        if retry_count < max_retries - 1:
            result.should_retry = True
            self._log(f"Will retry {operation}")
        else:
            result.should_continue = False
            result.message = f"Max retries exceeded for {operation}"
            self._log(result.message)

        return result

    async def on_popup(
        self,
        step_id: int | None,
        url: str | None,
        popup_type: str,
    ) -> HookResult:
        """Handle popup detection. Triggers auto-close strategy."""
        context = HookContext(
            hook_type=HookType.ON_POPUP,
            step_id=step_id,
            current_url=url,
            extra={"popup_type": popup_type},
        )

        result = await self.trigger(context)

        if popup_type in self._popup_strategies:
            strategy = self._popup_strategies[popup_type]
            try:
                closed = await strategy()
                if closed:
                    result.message = f"Closed {popup_type} popup"
                    self._log(result.message)
            except Exception as e:
                self._log(f"Failed to close {popup_type}: {e}")

        return result

    async def on_error(
        self,
        step_id: int | None,
        url: str | None,
        error: Exception,
        operation: str,
    ) -> HookResult:
        """Handle error events."""
        context = HookContext(
            hook_type=HookType.ON_ERROR,
            step_id=step_id,
            current_url=url,
            action_description=operation,
            error=error,
        )

        self._log(f"Error on {operation}: {error}")

        screenshot_path = None
        if self._screenshot_callback:
            screenshot_path = await self._screenshot_callback(f"error_{step_id}")

        result = await self.trigger(context)
        result.screenshot_path = screenshot_path
        result.message = str(error)

        return result

    def register_popup_strategy(
        self,
        popup_type: str,
        strategy: Callable[..., Coroutine[Any, Any, bool]],
    ) -> None:
        """Register an auto-close strategy for a popup type."""
        self._popup_strategies[popup_type] = strategy

    def get_registered_popup_types(self) -> list[str]:
        """Get all registered popup types."""
        return list(self._popup_strategies.keys())


class DefaultHooks:
    """Default hook implementations."""

    @staticmethod
    async def log_navigation(context: HookContext) -> HookResult:
        """Log navigation events."""
        return HookResult(message=f"Navigating to {context.target_url}")

    @staticmethod
    async def validate_url(context: HookContext) -> HookResult:
        """Validate target URL."""
        if context.target_url and not context.target_url.startswith(("http://", "https://")):
            return HookResult(
                should_continue=False,
                message=f"Invalid URL: {context.target_url}",
            )
        return HookResult()

    @staticmethod
    async def check_same_page(context: HookContext) -> HookResult:
        """Check if navigating to same page."""
        if context.current_url == context.target_url:
            return HookResult(message="Already on target page")
        return HookResult()


def create_default_lifecycle_manager() -> LifecycleManager:
    """Create a lifecycle manager with default hooks."""
    manager = LifecycleManager()

    manager.register_hook(HookType.PRE_NAVIGATE, DefaultHooks.validate_url)
    manager.register_hook(HookType.PRE_NAVIGATE, DefaultHooks.check_same_page)

    return manager
