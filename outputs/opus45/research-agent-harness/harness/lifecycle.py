"""Lifecycle Hooks (L) - Quality control hooks for the research pipeline.

Hooks:
- pre_search: Deduplication check before executing searches
- post_search: Source quality filtering after search results
- pre_draft: Evidence sufficiency check before drafting
- post_draft: Citation integrity validation after drafting
- on_rate_limit: Backoff handling when rate limited
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Any, Awaitable
import asyncio
import re


class HookResult(Enum):
    """Result of a hook execution."""
    CONTINUE = "continue"  # Proceed with the operation
    SKIP = "skip"  # Skip this operation
    RETRY = "retry"  # Retry the operation
    ABORT = "abort"  # Abort the entire pipeline


@dataclass
class HookContext:
    """Context passed to hooks."""
    hook_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)
    previous_result: Optional[HookResult] = None


@dataclass
class HookResponse:
    """Response from a hook."""
    result: HookResult
    message: str = ""
    modified_data: Optional[dict[str, Any]] = None
    wait_seconds: float = 0.0


class PreSearchHook:
    """Pre-search hook for deduplication checking."""

    def __init__(self, query_history_fn: Callable[[], set[str]]) -> None:
        self._get_query_history = query_history_fn

    async def execute(self, ctx: HookContext) -> HookResponse:
        """Check if query is a duplicate."""
        query_text = ctx.data.get("query_text", "")
        if not query_text:
            return HookResponse(result=HookResult.CONTINUE)

        normalized = self._normalize(query_text)
        history = self._get_query_history()

        if normalized in history:
            return HookResponse(
                result=HookResult.SKIP,
                message=f"Duplicate query skipped: {query_text[:50]}..."
            )

        for existing in history:
            if self._similarity(normalized, existing) > 0.85:
                return HookResponse(
                    result=HookResult.SKIP,
                    message=f"Similar query already executed: {query_text[:50]}..."
                )

        return HookResponse(result=HookResult.CONTINUE)

    def _normalize(self, text: str) -> str:
        """Normalize query text for comparison."""
        return " ".join(text.lower().split())

    def _similarity(self, a: str, b: str) -> float:
        """Simple Jaccard similarity between queries."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)


class PostSearchHook:
    """Post-search hook for source quality filtering."""

    def __init__(self, min_reliability_score: float = 0.3) -> None:
        self.min_reliability_score = min_reliability_score

    async def execute(self, ctx: HookContext) -> HookResponse:
        """Filter sources by quality."""
        sources = ctx.data.get("sources", [])
        if not sources:
            return HookResponse(result=HookResult.CONTINUE)

        filtered = []
        removed = []

        for source in sources:
            score = source.get("reliability_score", 0.5)
            if score >= self.min_reliability_score:
                filtered.append(source)
            else:
                removed.append(source.get("url", "unknown"))

        message = ""
        if removed:
            message = f"Filtered {len(removed)} low-quality sources"

        return HookResponse(
            result=HookResult.CONTINUE,
            message=message,
            modified_data={"sources": filtered, "removed_sources": removed}
        )


class PreDraftHook:
    """Pre-draft hook for evidence sufficiency check."""

    def __init__(self, min_evidence_per_section: int = 2) -> None:
        self.min_evidence_per_section = min_evidence_per_section

    async def execute(self, ctx: HookContext) -> HookResponse:
        """Check if sufficient evidence exists for drafting."""
        section_name = ctx.data.get("section_name", "")
        evidence_count = ctx.data.get("evidence_count", 0)

        if evidence_count < self.min_evidence_per_section:
            return HookResponse(
                result=HookResult.SKIP,
                message=f"Insufficient evidence for {section_name}: "
                       f"{evidence_count}/{self.min_evidence_per_section}"
            )

        return HookResponse(result=HookResult.CONTINUE)


class PostDraftHook:
    """Post-draft hook for citation integrity validation."""

    def __init__(self, citation_validator: Callable[[str], list[int]]) -> None:
        self._validate_citations = citation_validator

    async def execute(self, ctx: HookContext) -> HookResponse:
        """Validate citation integrity in draft."""
        draft_content = ctx.data.get("content", "")
        if not draft_content:
            return HookResponse(result=HookResult.CONTINUE)

        broken_citations = self._validate_citations(draft_content)

        if broken_citations:
            return HookResponse(
                result=HookResult.RETRY,
                message=f"Broken citations found: {broken_citations}",
                modified_data={"broken_citations": broken_citations}
            )

        citation_pattern = r'\[(\d+)\]'
        citations = re.findall(citation_pattern, draft_content)

        if not citations:
            return HookResponse(
                result=HookResult.CONTINUE,
                message="Warning: No citations in draft"
            )

        return HookResponse(result=HookResult.CONTINUE)


class OnRateLimitHook:
    """Rate limit hook with exponential backoff."""

    def __init__(self, max_wait: float = 300.0, base_multiplier: float = 1.5) -> None:
        self.max_wait = max_wait
        self.base_multiplier = base_multiplier
        self._consecutive_limits: dict[str, int] = {}

    async def execute(self, ctx: HookContext) -> HookResponse:
        """Handle rate limit with backoff."""
        tool_name = ctx.data.get("tool_name", "unknown")
        suggested_wait = ctx.data.get("wait_seconds", 60.0)

        consecutive = self._consecutive_limits.get(tool_name, 0) + 1
        self._consecutive_limits[tool_name] = consecutive

        wait_time = min(
            suggested_wait * (self.base_multiplier ** (consecutive - 1)),
            self.max_wait
        )

        return HookResponse(
            result=HookResult.RETRY,
            message=f"Rate limited on {tool_name}, waiting {wait_time:.1f}s "
                   f"(attempt {consecutive})",
            wait_seconds=wait_time
        )

    def reset(self, tool_name: str) -> None:
        """Reset consecutive limit counter after successful call."""
        self._consecutive_limits[tool_name] = 0


class LifecycleManager:
    """Manages all lifecycle hooks."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[[HookContext], Awaitable[HookResponse]]]] = {
            "pre_search": [],
            "post_search": [],
            "pre_draft": [],
            "post_draft": [],
            "on_rate_limit": [],
        }
        self._hook_log: list[dict] = []

    def register_hook(
        self,
        hook_name: str,
        hook_fn: Callable[[HookContext], Awaitable[HookResponse]]
    ) -> None:
        """Register a hook function."""
        if hook_name in self._hooks:
            self._hooks[hook_name].append(hook_fn)

    def register_pre_search(
        self,
        query_history_fn: Callable[[], set[str]]
    ) -> PreSearchHook:
        """Register and return pre-search hook."""
        hook = PreSearchHook(query_history_fn)
        self._hooks["pre_search"].append(hook.execute)
        return hook

    def register_post_search(
        self,
        min_reliability_score: float = 0.3
    ) -> PostSearchHook:
        """Register and return post-search hook."""
        hook = PostSearchHook(min_reliability_score)
        self._hooks["post_search"].append(hook.execute)
        return hook

    def register_pre_draft(
        self,
        min_evidence_per_section: int = 2
    ) -> PreDraftHook:
        """Register and return pre-draft hook."""
        hook = PreDraftHook(min_evidence_per_section)
        self._hooks["pre_draft"].append(hook.execute)
        return hook

    def register_post_draft(
        self,
        citation_validator: Callable[[str], list[int]]
    ) -> PostDraftHook:
        """Register and return post-draft hook."""
        hook = PostDraftHook(citation_validator)
        self._hooks["post_draft"].append(hook.execute)
        return hook

    def register_on_rate_limit(
        self,
        max_wait: float = 300.0
    ) -> OnRateLimitHook:
        """Register and return rate limit hook."""
        hook = OnRateLimitHook(max_wait)
        self._hooks["on_rate_limit"].append(hook.execute)
        return hook

    async def run_hooks(
        self,
        hook_name: str,
        data: dict[str, Any]
    ) -> HookResponse:
        """Run all hooks for a given event."""
        if hook_name not in self._hooks:
            return HookResponse(result=HookResult.CONTINUE)

        ctx = HookContext(hook_name=hook_name, data=data)
        final_response = HookResponse(result=HookResult.CONTINUE)

        for hook_fn in self._hooks[hook_name]:
            response = await hook_fn(ctx)

            self._hook_log.append({
                "hook_name": hook_name,
                "timestamp": datetime.now().isoformat(),
                "result": response.result.value,
                "message": response.message,
            })

            if response.result == HookResult.ABORT:
                return response
            elif response.result == HookResult.SKIP:
                return response
            elif response.result == HookResult.RETRY:
                final_response = response

            if response.modified_data:
                ctx.data.update(response.modified_data)
                final_response.modified_data = ctx.data

            ctx.previous_result = response.result

        return final_response

    def get_hook_log(self) -> list[dict]:
        """Get log of all hook executions."""
        return self._hook_log.copy()
