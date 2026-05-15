"""Tool Registry (T) - Manages research tools with rate limiting and retry.

Provides a unified interface for registering and executing tools with:
- Rate limiting per tool
- Retry strategies with exponential backoff
- Tool metadata and safety classification
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Awaitable
from functools import wraps


class ToolSafety(Enum):
    """Safety classification for tools."""
    SAFE = "safe"  # Read-only, no side effects
    MODERATE = "moderate"  # May have limited side effects
    UNSAFE = "unsafe"  # Can modify external state


@dataclass
class RateLimitConfig:
    """Rate limiting configuration for a tool."""
    max_calls_per_minute: int = 60
    max_calls_per_hour: int = 1000
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""
    name: str
    description: str
    safety: ToolSafety
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    parameters: dict[str, str] = field(default_factory=dict)


class RateLimiter:
    """Token bucket rate limiter with sliding window."""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self._minute_calls: list[float] = []
        self._hour_calls: list[float] = []

    def can_proceed(self) -> bool:
        """Check if a call can proceed under rate limits."""
        now = time.time()
        self._cleanup(now)

        if len(self._minute_calls) >= self.config.max_calls_per_minute:
            return False
        if len(self._hour_calls) >= self.config.max_calls_per_hour:
            return False
        return True

    def record_call(self) -> None:
        """Record a successful call."""
        now = time.time()
        self._minute_calls.append(now)
        self._hour_calls.append(now)

    def time_until_available(self) -> float:
        """Return seconds until next call is allowed."""
        now = time.time()
        self._cleanup(now)

        if len(self._minute_calls) >= self.config.max_calls_per_minute:
            oldest = self._minute_calls[0]
            return max(0, 60 - (now - oldest))

        if len(self._hour_calls) >= self.config.max_calls_per_hour:
            oldest = self._hour_calls[0]
            return max(0, 3600 - (now - oldest))

        return 0

    def _cleanup(self, now: float) -> None:
        """Remove expired entries from sliding windows."""
        self._minute_calls = [t for t in self._minute_calls if now - t < 60]
        self._hour_calls = [t for t in self._hour_calls if now - t < 3600]


class ToolExecutionError(Exception):
    """Error during tool execution."""

    def __init__(self, tool_name: str, message: str, retryable: bool = True) -> None:
        super().__init__(f"Tool '{tool_name}' failed: {message}")
        self.tool_name = tool_name
        self.retryable = retryable


class RateLimitExceeded(ToolExecutionError):
    """Rate limit exceeded for a tool."""

    def __init__(self, tool_name: str, wait_seconds: float) -> None:
        super().__init__(tool_name, f"Rate limit exceeded, wait {wait_seconds:.1f}s", retryable=True)
        self.wait_seconds = wait_seconds


@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    retries: int = 0
    execution_time: float = 0.0


class ToolRegistry:
    """Registry for research tools with rate limiting and retry support."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable] = {}
        self._metadata: dict[str, ToolMetadata] = {}
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._on_rate_limit: Optional[Callable[[str, float], Awaitable[None]]] = None

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        safety: ToolSafety = ToolSafety.SAFE,
        rate_limit: Optional[RateLimitConfig] = None,
        parameters: Optional[dict[str, str]] = None,
    ) -> None:
        """Register a tool with metadata."""
        metadata = ToolMetadata(
            name=name,
            description=description,
            safety=safety,
            rate_limit=rate_limit or RateLimitConfig(),
            parameters=parameters or {},
        )
        self._tools[name] = func
        self._metadata[name] = metadata
        self._rate_limiters[name] = RateLimiter(metadata.rate_limit)

    def set_rate_limit_callback(
        self,
        callback: Callable[[str, float], Awaitable[None]]
    ) -> None:
        """Set callback for rate limit events."""
        self._on_rate_limit = callback

    def get_tool(self, name: str) -> Optional[Callable]:
        """Get a registered tool by name."""
        return self._tools.get(name)

    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """Get tool metadata."""
        return self._metadata.get(name)

    def list_tools(self) -> list[ToolMetadata]:
        """List all registered tools."""
        return list(self._metadata.values())

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool with rate limiting and retry."""
        if name not in self._tools:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {name}"
            )

        func = self._tools[name]
        metadata = self._metadata[name]
        rate_limiter = self._rate_limiters[name]
        config = metadata.rate_limit

        start_time = time.time()
        retries = 0

        while retries <= config.retry_max_attempts:
            if not rate_limiter.can_proceed():
                wait_time = rate_limiter.time_until_available()
                if self._on_rate_limit:
                    await self._on_rate_limit(name, wait_time)
                await asyncio.sleep(wait_time)
                continue

            try:
                rate_limiter.record_call()
                if asyncio.iscoroutinefunction(func):
                    result = await func(**kwargs)
                else:
                    result = func(**kwargs)

                return ToolResult(
                    success=True,
                    data=result,
                    retries=retries,
                    execution_time=time.time() - start_time,
                )

            except ToolExecutionError as e:
                if not e.retryable or retries >= config.retry_max_attempts:
                    return ToolResult(
                        success=False,
                        error=str(e),
                        retries=retries,
                        execution_time=time.time() - start_time,
                    )

                delay = min(
                    config.retry_base_delay * (2 ** retries),
                    config.retry_max_delay
                )
                await asyncio.sleep(delay)
                retries += 1

            except Exception as e:
                if retries >= config.retry_max_attempts:
                    return ToolResult(
                        success=False,
                        error=str(e),
                        retries=retries,
                        execution_time=time.time() - start_time,
                    )

                delay = min(
                    config.retry_base_delay * (2 ** retries),
                    config.retry_max_delay
                )
                await asyncio.sleep(delay)
                retries += 1

        return ToolResult(
            success=False,
            error="Max retries exceeded",
            retries=retries,
            execution_time=time.time() - start_time,
        )

    def execute_sync(self, name: str, **kwargs: Any) -> ToolResult:
        """Synchronous wrapper for execute."""
        return asyncio.get_event_loop().run_until_complete(
            self.execute(name, **kwargs)
        )


def tool(
    name: str,
    description: str,
    safety: ToolSafety = ToolSafety.SAFE,
    rate_limit: Optional[RateLimitConfig] = None,
    parameters: Optional[dict[str, str]] = None,
) -> Callable:
    """Decorator to mark a function as a tool."""
    def decorator(func: Callable) -> Callable:
        func._tool_metadata = {
            "name": name,
            "description": description,
            "safety": safety,
            "rate_limit": rate_limit,
            "parameters": parameters,
        }
        return func
    return decorator


def register_tools_from_module(registry: ToolRegistry, module: Any) -> None:
    """Register all decorated tools from a module."""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if callable(attr) and hasattr(attr, "_tool_metadata"):
            meta = attr._tool_metadata
            registry.register(
                name=meta["name"],
                func=attr,
                description=meta["description"],
                safety=meta["safety"],
                rate_limit=meta["rate_limit"],
                parameters=meta["parameters"],
            )
