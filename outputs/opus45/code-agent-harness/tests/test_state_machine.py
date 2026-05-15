"""Tests for the state machine component."""

import pytest
from harness.execution import (
    ExecutionStateMachine,
    FixLoopStateMachine,
    MainState,
    FixState,
    Event,
)


class TestFixLoopStateMachine:
    """Tests for the nested fix loop state machine."""

    def test_initial_state(self):
        sm = FixLoopStateMachine()
        assert sm.state == FixState.LOCATE

    def test_happy_path(self):
        sm = FixLoopStateMachine()

        sm.step(Event.LOCATE_COMPLETE)
        assert sm.state == FixState.ANALYZE

        sm.step(Event.ANALYZE_COMPLETE)
        assert sm.state == FixState.FIX

        sm.step(Event.FIX_APPLIED)
        assert sm.state == FixState.VERIFY

        sm.step(Event.VERIFY_PASSED)
        assert sm.state == FixState.COMMIT

        sm.step(Event.COMMIT_COMPLETE)
        assert sm.state == FixState.DONE
        assert sm.is_done

    def test_verify_failure_retry(self):
        sm = FixLoopStateMachine()
        sm.step(Event.LOCATE_COMPLETE)
        sm.step(Event.ANALYZE_COMPLETE)
        sm.step(Event.FIX_APPLIED)

        sm.step(Event.VERIFY_FAILED)
        assert sm.state == FixState.ANALYZE
        assert sm._attempt_count == 1

    def test_max_attempts_blocked(self):
        sm = FixLoopStateMachine()
        sm._max_attempts = 2

        for _ in range(2):
            sm.state = FixState.VERIFY
            sm.step(Event.VERIFY_FAILED)

        assert sm.state == FixState.BLOCKED
        assert sm.is_blocked

    def test_reset(self):
        sm = FixLoopStateMachine()
        sm.step(Event.LOCATE_COMPLETE)
        sm._attempt_count = 2

        sm.reset()
        assert sm.state == FixState.LOCATE
        assert sm._attempt_count == 0


class TestExecutionStateMachine:
    """Tests for the main execution state machine."""

    def test_initial_state(self):
        sm = ExecutionStateMachine()
        assert sm.state == MainState.IDLE

    def test_start_transition(self):
        sm = ExecutionStateMachine()
        sm.step(Event.START)
        assert sm.state == MainState.INDEX

    def test_index_to_test(self):
        sm = ExecutionStateMachine()
        sm.step(Event.START)
        sm.step(Event.INDEX_COMPLETE)
        assert sm.state == MainState.TEST

    def test_full_workflow_transitions(self):
        sm = ExecutionStateMachine()

        sm.step(Event.START)
        assert sm.state == MainState.INDEX

        sm.step(Event.INDEX_COMPLETE)
        assert sm.state == MainState.TEST

        sm.step(Event.TEST_COMPLETE)
        assert sm.state == MainState.CLASSIFY

        sm.step(Event.CLASSIFY_COMPLETE)
        assert sm.state == MainState.PRIORITIZE

        sm.step(Event.PRIORITIZE_COMPLETE)
        assert sm.state == MainState.FIX_LOOP

        sm.step(Event.ALL_BUGS_FIXED)
        assert sm.state == MainState.REGRESSION

        sm.step(Event.REGRESSION_PASSED)
        assert sm.state == MainState.REPORT

        sm.step(Event.REPORT_COMPLETE)
        assert sm.state == MainState.COMPLETED
        assert sm.is_terminal

    def test_error_leads_to_failed(self):
        sm = ExecutionStateMachine()
        sm.step(Event.START)
        sm.step(Event.ERROR)
        assert sm.state == MainState.FAILED
        assert sm.is_terminal

    def test_abort_leads_to_failed(self):
        sm = ExecutionStateMachine()
        sm.step(Event.START)
        sm.step(Event.INDEX_COMPLETE)
        sm.step(Event.ABORT)
        assert sm.state == MainState.FAILED

    def test_regression_failure_returns_to_fix(self):
        sm = ExecutionStateMachine()
        sm.state = MainState.REGRESSION
        sm.step(Event.REGRESSION_FAILED)
        assert sm.state == MainState.FIX_LOOP

    def test_get_state_info(self):
        sm = ExecutionStateMachine()
        sm.step(Event.START)

        info = sm.get_state_info()
        assert info["main_state"] == "INDEX"
        assert info["is_terminal"] is False

    def test_fix_state_info(self):
        sm = ExecutionStateMachine()
        sm.state = MainState.FIX_LOOP
        sm.fix_loop.state = FixState.ANALYZE

        info = sm.get_state_info()
        assert info["fix_state"] == "ANALYZE"
