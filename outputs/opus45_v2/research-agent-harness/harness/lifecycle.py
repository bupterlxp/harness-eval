"""Lifecycle Hooks (L) - Research boundary control and validation hooks."""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Callable
from enum import Enum

from harness.state import StateStore
from harness.context import ContextManager


class HookPhase(Enum):
    PRE_SEARCH = "pre_search"
    POST_SEARCH = "post_search"
    PRE_EXTRACT = "pre_extract"
    POST_EXTRACT = "post_extract"
    PRE_DRAFT = "pre_draft"
    POST_DRAFT = "post_draft"
    PRE_CITE = "pre_cite"
    POST_CITE = "post_cite"
    PRE_HOP = "pre_hop"
    POST_HOP = "post_hop"


@dataclass
class HookResult:
    """Result of a lifecycle hook execution."""
    passed: bool
    message: str
    data: dict[str, Any] | None = None
    should_continue: bool = True

    @classmethod
    def success(cls, message: str = "OK", data: dict[str, Any] | None = None) -> HookResult:
        return cls(passed=True, message=message, data=data)

    @classmethod
    def failure(cls, message: str, data: dict[str, Any] | None = None, should_continue: bool = True) -> HookResult:
        return cls(passed=False, message=message, data=data, should_continue=should_continue)


class LifecycleHooks:
    """Manages lifecycle hooks for research boundary control."""

    def __init__(self, state: StateStore, context: ContextManager):
        self._state = state
        self._context = context
        self._custom_hooks: dict[HookPhase, list[Callable[..., HookResult]]] = {
            phase: [] for phase in HookPhase
        }

    def register_hook(self, phase: HookPhase, hook: Callable[..., HookResult]) -> None:
        """Register a custom hook for a phase."""
        self._custom_hooks[phase].append(hook)

    def _run_custom_hooks(self, phase: HookPhase, **kwargs: Any) -> list[HookResult]:
        """Run all custom hooks for a phase."""
        results = []
        for hook in self._custom_hooks[phase]:
            try:
                result = hook(**kwargs)
                results.append(result)
            except Exception as e:
                results.append(HookResult.failure(f"Hook error: {e}"))
        return results

    def pre_search_dedup(self, queries: list[str]) -> HookResult:
        """Pre-search hook: deduplicate queries against already-executed queries."""
        executed = set(self._state._queries_executed)
        new_queries = [q for q in queries if q not in executed]
        deduped_count = len(queries) - len(new_queries)

        if not new_queries:
            return HookResult.failure(
                f"All {len(queries)} queries already executed",
                data={"original": queries, "new": [], "deduped": deduped_count},
                should_continue=False,
            )

        return HookResult.success(
            f"Deduped {deduped_count} queries, {len(new_queries)} remaining",
            data={"original": queries, "new": new_queries, "deduped": deduped_count},
        )

    def pre_search_url_dedup(self, urls: list[str]) -> HookResult:
        """Pre-search hook: filter out already-seen URLs."""
        new_urls = [url for url in urls if not self._state.is_url_seen(url)]
        deduped_count = len(urls) - len(new_urls)

        return HookResult.success(
            f"URL dedup: {deduped_count} duplicates removed, {len(new_urls)} new",
            data={"original": urls, "new": new_urls, "deduped": deduped_count},
        )

    def pre_draft_evidence_check(
        self,
        section_name: str,
        min_sources: int = 3,
        min_facts: int = 5,
    ) -> HookResult:
        """Pre-draft hook: check if we have sufficient evidence before drafting."""
        total_sources = len(self._state.sources)
        total_facts = len(self._state.facts)

        issues = []
        if total_sources < min_sources:
            issues.append(f"Only {total_sources}/{min_sources} sources")
        if total_facts < min_facts:
            issues.append(f"Only {total_facts}/{min_facts} facts")

        if issues:
            return HookResult.failure(
                f"Insufficient evidence for {section_name}: {'; '.join(issues)}",
                data={
                    "total_sources": total_sources,
                    "total_facts": total_facts,
                    "min_sources": min_sources,
                    "min_facts": min_facts,
                },
            )

        high_cred_sources = len([s for s in self._state.sources if s.credibility == "high"])

        return HookResult.success(
            f"Evidence sufficient: {total_sources} sources ({high_cred_sources} high-cred), {total_facts} facts",
            data={
                "total_sources": total_sources,
                "high_credibility_sources": high_cred_sources,
                "total_facts": total_facts,
            },
        )

    def post_draft_citation_check(self, content: str) -> HookResult:
        """Post-draft hook: verify citation integrity in drafted content."""
        inline_citations = set(int(m) for m in re.findall(r"\[(\d+)\]", content))

        available_citations = set(m.inline_number for m in self._state.citation_mappings)

        orphaned = inline_citations - available_citations
        unused = available_citations - inline_citations

        if orphaned:
            return HookResult.failure(
                f"Citation integrity failed: orphaned citations {orphaned}",
                data={
                    "inline_citations": list(inline_citations),
                    "available_citations": list(available_citations),
                    "orphaned": list(orphaned),
                    "unused": list(unused),
                },
            )

        return HookResult.success(
            f"Citation check passed: {len(inline_citations)} inline, {len(unused)} unused in refs",
            data={
                "total_citations": len(inline_citations),
                "orphaned": 0,
                "unused": len(unused),
            },
        )

    def verify_citation_integrity(self) -> HookResult:
        """Comprehensive citation integrity verification."""
        all_section_content = " ".join(
            draft.content for draft in self._state.section_drafts
        )

        inline_citations = set(int(m) for m in re.findall(r"\[(\d+)\]", all_section_content))
        available_citations = set(m.inline_number for m in self._state.citation_mappings)

        orphaned = inline_citations - available_citations
        unused = available_citations - inline_citations

        integrity_data = {
            "total_citations": len(inline_citations),
            "orphaned": len(orphaned),
            "unused": len(unused),
            "orphaned_list": list(orphaned),
            "unused_list": list(unused),
        }

        if orphaned:
            return HookResult.failure(
                f"Orphaned citations found: {orphaned}",
                data=integrity_data,
            )

        return HookResult.success(
            "Citation integrity verified",
            data=integrity_data,
        )

    def pre_hop_check(
        self,
        current_hop: int,
        max_hops: int,
        gaps: list[str],
    ) -> HookResult:
        """Pre-hop hook: check if another hop is warranted and allowed."""
        if current_hop >= max_hops:
            return HookResult.failure(
                f"Max hops ({max_hops}) reached",
                data={"current_hop": current_hop, "max_hops": max_hops, "gaps": gaps},
                should_continue=False,
            )

        if not gaps:
            return HookResult.success(
                "No gaps remaining, hop not needed",
                data={"current_hop": current_hop, "gaps": []},
            )

        return HookResult.success(
            f"Hop {current_hop + 1}/{max_hops} warranted: {len(gaps)} gaps",
            data={"current_hop": current_hop, "max_hops": max_hops, "gaps": gaps},
        )

    def check_convergence(
        self,
        min_sources: int,
        required_sections: list[str],
        new_facts_this_hop: int,
        convergence_threshold: int = 2,
    ) -> HookResult:
        """Check if research has converged (enough evidence, diminishing returns)."""
        sources = len(self._state.sources)
        facts = len(self._state.facts)
        gaps = self._state.gaps

        reasons = []

        if sources >= min_sources and not gaps:
            reasons.append(f"Met min sources ({sources}/{min_sources}) with no gaps")

        if new_facts_this_hop < convergence_threshold:
            reasons.append(f"Diminishing returns ({new_facts_this_hop} new facts)")

        if sources >= min_sources * 2:
            reasons.append(f"Abundant sources ({sources})")

        converged = len(reasons) > 0

        return HookResult.success(
            f"Convergence {'reached' if converged else 'not reached'}: {'; '.join(reasons) if reasons else 'still gathering'}",
            data={
                "converged": converged,
                "reasons": reasons,
                "total_sources": sources,
                "total_facts": facts,
                "gaps_remaining": gaps,
                "new_facts_this_hop": new_facts_this_hop,
            },
        )

    def validate_fact_provenance(self, fact_id: int) -> HookResult:
        """Validate that a fact has proper provenance."""
        fact = self._state.get_fact(fact_id)
        if not fact:
            return HookResult.failure(f"Fact {fact_id} not found")

        source = self._state.get_source(fact.source_id)
        if not source:
            return HookResult.failure(
                f"Fact {fact_id} references non-existent source {fact.source_id}"
            )

        return HookResult.success(
            f"Fact {fact_id} has valid provenance to source {source.id} ({source.url})",
            data={"fact_id": fact_id, "source_id": source.id, "source_url": source.url},
        )

    def validate_all_facts_provenance(self) -> HookResult:
        """Validate provenance for all facts."""
        invalid_facts = []
        for fact in self._state.facts:
            result = self.validate_fact_provenance(fact.id)
            if not result.passed:
                invalid_facts.append(fact.id)

        if invalid_facts:
            return HookResult.failure(
                f"{len(invalid_facts)} facts lack valid provenance",
                data={"invalid_fact_ids": invalid_facts},
            )

        return HookResult.success(
            f"All {len(self._state.facts)} facts have valid provenance"
        )

    def check_section_coverage(self, required_sections: list[str]) -> HookResult:
        """Check if all required sections have been drafted."""
        drafted = set(d.name for d in self._state.section_drafts if d.content)
        required = set(required_sections)
        missing = required - drafted

        if missing:
            return HookResult.failure(
                f"Missing sections: {missing}",
                data={"required": list(required), "drafted": list(drafted), "missing": list(missing)},
            )

        return HookResult.success(
            f"All {len(required)} required sections drafted",
            data={"sections": list(drafted)},
        )

    def run_phase_hooks(self, phase: HookPhase, **kwargs: Any) -> list[HookResult]:
        """Run all hooks for a phase including custom hooks."""
        results = []

        if phase == HookPhase.PRE_SEARCH:
            if "queries" in kwargs:
                results.append(self.pre_search_dedup(kwargs["queries"]))
            if "urls" in kwargs:
                results.append(self.pre_search_url_dedup(kwargs["urls"]))

        elif phase == HookPhase.PRE_DRAFT:
            section_name = kwargs.get("section_name", "unknown")
            min_sources = kwargs.get("min_sources", 3)
            min_facts = kwargs.get("min_facts", 5)
            results.append(self.pre_draft_evidence_check(section_name, min_sources, min_facts))

        elif phase == HookPhase.POST_DRAFT:
            if "content" in kwargs:
                results.append(self.post_draft_citation_check(kwargs["content"]))

        elif phase == HookPhase.PRE_HOP:
            current_hop = kwargs.get("current_hop", 0)
            max_hops = kwargs.get("max_hops", 3)
            gaps = kwargs.get("gaps", [])
            results.append(self.pre_hop_check(current_hop, max_hops, gaps))

        results.extend(self._run_custom_hooks(phase, **kwargs))

        return results
