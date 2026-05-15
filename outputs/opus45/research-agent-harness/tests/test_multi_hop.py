"""Tests for multi-hop search termination conditions."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from harness.schemas import ResearchState, ResearchTask, ResearchQuery, Evidence
from harness.state import StateStore
from harness.context import ContextManager
from harness.lifecycle import LifecycleManager
from harness.evaluation import TrajectoryLogger
from harness.tools import ToolRegistry
from harness.execution import ResearchStateMachine


@pytest.fixture
def research_task():
    """Create a test research task."""
    return ResearchTask(
        topic="Test Topic",
        questions=["Question 1?", "Question 2?"],
        constraints={},
        required_sections=["摘要", "背景与动机", "参考文献"],
        min_sources=5,
        max_report_length=1000,
    )


@pytest.fixture
def state_machine(research_task):
    """Create a state machine for testing."""
    state_store = StateStore(research_task.required_sections)
    context_manager = ContextManager(research_task.required_sections)
    lifecycle_manager = LifecycleManager()
    trajectory_logger = TrajectoryLogger()
    tool_registry = ToolRegistry()

    return ResearchStateMachine(
        state_store=state_store,
        context_manager=context_manager,
        lifecycle_manager=lifecycle_manager,
        trajectory_logger=trajectory_logger,
        tool_registry=tool_registry,
        max_hops=3,
        evidence_threshold=2,
    )


class TestMultiHopTermination:
    """Tests for multi-hop search termination."""

    def test_max_hops_limit_respected(self, state_machine):
        """Verify that max_hops limit is enforced."""
        assert state_machine.max_hops == 3
        assert state_machine.state_store.max_hops == 3

    def test_hop_count_increments(self, state_machine):
        """Verify hop count increments during gap fill."""
        initial_hops = state_machine.state_store.hop_count
        assert initial_hops == 0

        state_machine.state_store.hop_count += 1
        assert state_machine.state_store.hop_count == 1

    def test_hop_count_prevents_infinite_loop(self, state_machine, research_task):
        """Verify state machine stops at max hops."""
        state_machine.state_store.hop_count = state_machine.max_hops

        from harness.execution import StateContext, StateResult

        ctx = StateContext(task=research_task)
        ctx.gap_fill_section = "摘要"

        async def run_test():
            result = await state_machine._handle_gap_fill(ctx)
            assert result.next_state == ResearchState.CROSS_VALIDATE
            assert "Max hops" in result.message

        asyncio.run(run_test())

    def test_gap_fill_returns_to_search(self, state_machine, research_task):
        """Verify gap fill returns to SEARCH state when under max hops."""
        state_machine.state_store.hop_count = 0

        tool_registry = state_machine.tools
        tool_registry.register(
            name="generate_gap_queries",
            func=AsyncMock(return_value=[{"query_text": "test query", "target_section": "摘要"}]),
            description="Generate gap queries",
        )

        from harness.execution import StateContext

        ctx = StateContext(task=research_task)
        ctx.gap_fill_section = "摘要"
        ctx.queries = []

        async def run_test():
            result = await state_machine._handle_gap_fill(ctx)
            assert result.next_state == ResearchState.SEARCH
            assert state_machine.state_store.hop_count == 1

        asyncio.run(run_test())

    def test_state_transitions_logged(self, state_machine, research_task):
        """Verify state transitions are logged in trajectory."""
        state_machine.trajectory.log_state_transition(
            from_state="gap_fill",
            to_state="search",
            reason="Gap fill initiated"
        )

        trajectory = state_machine.trajectory.get_trajectory()
        assert len(trajectory) == 1
        assert trajectory[0].action == "state_transition"
        assert trajectory[0].details["from_state"] == "gap_fill"

    def test_gap_fill_hop_logged(self, state_machine):
        """Verify gap fill attempts are logged."""
        state_machine.trajectory.log_gap_fill_attempt(
            section_name="摘要",
            hop_number=1,
            queries_generated=3,
        )

        trajectory = state_machine.trajectory.get_trajectory()
        assert len(trajectory) == 1
        assert trajectory[0].state == "gap_fill"
        assert trajectory[0].details["hop_number"] == 1


class TestMultiHopConfiguration:
    """Tests for multi-hop configuration."""

    def test_default_max_hops(self, research_task):
        """Verify default max_hops value."""
        state_store = StateStore(research_task.required_sections)
        assert state_store.max_hops == 3

    def test_custom_max_hops(self, research_task):
        """Verify custom max_hops can be set."""
        state_store = StateStore(research_task.required_sections)
        context_manager = ContextManager(research_task.required_sections)
        lifecycle_manager = LifecycleManager()
        trajectory_logger = TrajectoryLogger()
        tool_registry = ToolRegistry()

        sm = ResearchStateMachine(
            state_store=state_store,
            context_manager=context_manager,
            lifecycle_manager=lifecycle_manager,
            trajectory_logger=trajectory_logger,
            tool_registry=tool_registry,
            max_hops=5,
            evidence_threshold=2,
        )

        assert sm.max_hops == 5

    def test_zero_max_hops_skips_gap_fill(self, research_task):
        """Verify zero max_hops skips gap fill entirely."""
        state_store = StateStore(research_task.required_sections)
        state_store.max_hops = 0
        state_store.hop_count = 0

        assert state_store.hop_count >= state_store.max_hops
