"""Tests for the Lifecycle Hooks module."""

import pytest

from harness.state import StateStore
from harness.context import ContextManager
from harness.lifecycle import LifecycleHooks, HookPhase, HookResult


class TestHookResult:
    def test_success_result(self):
        result = HookResult.success("Operation completed")
        assert result.passed is True
        assert result.message == "Operation completed"
        assert result.should_continue is True

    def test_failure_result(self):
        result = HookResult.failure("Operation failed", should_continue=False)
        assert result.passed is False
        assert result.message == "Operation failed"
        assert result.should_continue is False

    def test_result_with_data(self):
        result = HookResult.success("OK", data={"count": 5})
        assert result.data == {"count": 5}


class TestLifecycleHooks:
    @pytest.fixture
    def hooks(self):
        store = StateStore()
        context = ContextManager(store)
        return LifecycleHooks(store, context)

    def test_pre_search_dedup_no_executed(self, hooks):
        result = hooks.pre_search_dedup(["query1", "query2"])
        assert result.passed is True
        assert result.data["new"] == ["query1", "query2"]
        assert result.data["deduped"] == 0

    def test_pre_search_dedup_with_executed(self, hooks):
        hooks._state.record_query("query1")
        result = hooks.pre_search_dedup(["query1", "query2", "query3"])
        assert result.passed is True
        assert result.data["new"] == ["query2", "query3"]
        assert result.data["deduped"] == 1

    def test_pre_search_dedup_all_executed(self, hooks):
        hooks._state.record_query("query1")
        hooks._state.record_query("query2")
        result = hooks.pre_search_dedup(["query1", "query2"])
        assert result.passed is False
        assert result.should_continue is False

    def test_pre_search_url_dedup(self, hooks):
        hooks._state.add_source("https://example.com", "Example", "high")
        result = hooks.pre_search_url_dedup([
            "https://example.com",
            "https://new-site.com",
        ])
        assert result.passed is True
        assert result.data["new"] == ["https://new-site.com"]
        assert result.data["deduped"] == 1

    def test_pre_draft_evidence_check_insufficient(self, hooks):
        result = hooks.pre_draft_evidence_check("Introduction", min_sources=5, min_facts=10)
        assert result.passed is False
        assert "0/5 sources" in result.message

    def test_pre_draft_evidence_check_sufficient(self, hooks):
        for i in range(5):
            source = hooks._state.add_source(f"https://example{i}.com", f"Example {i}", "high")
            for j in range(3):
                hooks._state.add_fact(f"Fact {i}-{j}", source.id)

        result = hooks.pre_draft_evidence_check("Introduction", min_sources=5, min_facts=10)
        assert result.passed is True

    def test_post_draft_citation_check_valid(self, hooks):
        source = hooks._state.add_source("https://example.com", "Example", "high")
        hooks._state.add_citation_mapping(source.id, [1])

        content = "According to research [1], this is true."
        result = hooks.post_draft_citation_check(content)
        assert result.passed is True
        assert result.data["orphaned"] == 0

    def test_post_draft_citation_check_orphaned(self, hooks):
        content = "According to research [1] and [2], this is true."
        result = hooks.post_draft_citation_check(content)
        assert result.passed is False
        assert 1 in result.data["orphaned"]
        assert 2 in result.data["orphaned"]

    def test_verify_citation_integrity(self, hooks):
        source = hooks._state.add_source("https://example.com", "Example", "high")
        mapping = hooks._state.add_citation_mapping(source.id, [1])
        hooks._state.add_section_draft("Introduction", f"Test [{ mapping.inline_number}] content", [mapping.inline_number])

        result = hooks.verify_citation_integrity()
        assert result.passed is True

    def test_pre_hop_check_under_limit(self, hooks):
        result = hooks.pre_hop_check(
            current_hop=1,
            max_hops=3,
            gaps=["Gap 1", "Gap 2"],
        )
        assert result.passed is True
        assert result.should_continue is True

    def test_pre_hop_check_at_limit(self, hooks):
        result = hooks.pre_hop_check(
            current_hop=3,
            max_hops=3,
            gaps=["Gap 1"],
        )
        assert result.passed is False
        assert result.should_continue is False

    def test_pre_hop_check_no_gaps(self, hooks):
        result = hooks.pre_hop_check(
            current_hop=1,
            max_hops=3,
            gaps=[],
        )
        assert result.passed is True
        assert "No gaps" in result.message

    def test_check_convergence_not_converged(self, hooks):
        result = hooks.check_convergence(
            min_sources=10,
            required_sections=["Introduction", "Findings"],
            new_facts_this_hop=5,
        )
        assert result.data["converged"] is False

    def test_check_convergence_converged(self, hooks):
        for i in range(20):
            hooks._state.add_source(f"https://example{i}.com", f"Example {i}", "high")

        result = hooks.check_convergence(
            min_sources=10,
            required_sections=["Introduction", "Findings"],
            new_facts_this_hop=1,
        )
        assert result.data["converged"] is True

    def test_validate_fact_provenance_valid(self, hooks):
        source = hooks._state.add_source("https://example.com", "Example", "high")
        fact = hooks._state.add_fact("Test fact", source.id)

        result = hooks.validate_fact_provenance(fact.id)
        assert result.passed is True

    def test_validate_fact_provenance_invalid(self, hooks):
        fact = hooks._state.add_fact("Orphan fact", 999)

        result = hooks.validate_fact_provenance(fact.id)
        assert result.passed is False

    def test_validate_all_facts_provenance(self, hooks):
        source = hooks._state.add_source("https://example.com", "Example", "high")
        hooks._state.add_fact("Valid fact", source.id)
        hooks._state.add_fact("Another valid fact", source.id)

        result = hooks.validate_all_facts_provenance()
        assert result.passed is True

    def test_check_section_coverage_complete(self, hooks):
        hooks._state.add_section_draft("Introduction", "Content")
        hooks._state.add_section_draft("Findings", "Content")

        result = hooks.check_section_coverage(["Introduction", "Findings"])
        assert result.passed is True

    def test_check_section_coverage_incomplete(self, hooks):
        hooks._state.add_section_draft("Introduction", "Content")

        result = hooks.check_section_coverage(["Introduction", "Findings", "Conclusion"])
        assert result.passed is False
        assert "Findings" in str(result.data["missing"])

    def test_register_custom_hook(self, hooks):
        def custom_hook(**kwargs):
            return HookResult.success("Custom hook executed")

        hooks.register_hook(HookPhase.PRE_SEARCH, custom_hook)

        results = hooks.run_phase_hooks(HookPhase.PRE_SEARCH, queries=["test"])
        assert any("Custom hook executed" in r.message for r in results)

    def test_run_phase_hooks_pre_search(self, hooks):
        results = hooks.run_phase_hooks(
            HookPhase.PRE_SEARCH,
            queries=["query1", "query2"],
            urls=["https://example.com"],
        )
        assert len(results) >= 2

    def test_run_phase_hooks_pre_draft(self, hooks):
        results = hooks.run_phase_hooks(
            HookPhase.PRE_DRAFT,
            section_name="Introduction",
            min_sources=1,
            min_facts=1,
        )
        assert len(results) >= 1

    def test_run_phase_hooks_post_draft(self, hooks):
        results = hooks.run_phase_hooks(
            HookPhase.POST_DRAFT,
            content="Test content with [1] citation",
        )
        assert len(results) >= 1

    def test_run_phase_hooks_pre_hop(self, hooks):
        results = hooks.run_phase_hooks(
            HookPhase.PRE_HOP,
            current_hop=0,
            max_hops=3,
            gaps=["Gap 1"],
        )
        assert len(results) >= 1
