"""
test_state_machine.py - Tests for E component state machine

Tests safety (no invalid states) and liveness (progress guaranteed).
"""

import pytest
from harness.schemas import ExecutionState, EventType
from harness.execution import ExecutionLoop, InvalidTransitionError


class TestStateMachineTransitions:
    """Test valid state transitions"""

    def test_all_states_have_transitions_defined(self):
        """Every state must have at least error handling"""
        for state in ExecutionState:
            assert state in ExecutionLoop.VALID_TRANSITIONS, f"State {state} missing from transition table"

    def test_init_transitions(self):
        """INIT state can only go to PARSE_SPEC or ERROR"""
        valid = ExecutionLoop.VALID_TRANSITIONS[ExecutionState.INIT]
        assert EventType.START in valid
        assert valid[EventType.START] == ExecutionState.PARSE_SPEC
        assert EventType.ERROR_OCCURRED in valid
        assert valid[EventType.ERROR_OCCURRED] == ExecutionState.ERROR

    def test_complete_is_terminal(self):
        """COMPLETE state has no outgoing transitions"""
        valid = ExecutionLoop.VALID_TRANSITIONS[ExecutionState.COMPLETE]
        assert len(valid) == 0, "COMPLETE should be terminal"

    def test_error_can_resume(self):
        """ERROR state can transition to INIT via RESUME"""
        valid = ExecutionLoop.VALID_TRANSITIONS[ExecutionState.ERROR]
        assert EventType.RESUME in valid
        assert valid[EventType.RESUME] == ExecutionState.INIT

    def test_all_working_states_can_error(self):
        """All non-terminal states should handle ERROR_OCCURRED"""
        working_states = [
            ExecutionState.PARSE_SPEC,
            ExecutionState.NARRATOR_VOICE,
            ExecutionState.PLOT_OUTLINE,
            ExecutionState.SCENE_OUTLINE,
            ExecutionState.DRAFT_SCENE,
            ExecutionState.CONSISTENCY_CHECK,
            ExecutionState.STYLE_REVISION,
            ExecutionState.FINAL_ASSEMBLY,
        ]
        for state in working_states:
            valid = ExecutionLoop.VALID_TRANSITIONS[state]
            assert EventType.ERROR_OCCURRED in valid, f"{state} must handle ERROR_OCCURRED"
            assert valid[EventType.ERROR_OCCURRED] == ExecutionState.ERROR

    def test_all_working_states_can_suspend(self):
        """All working states should handle SUSPEND"""
        working_states = [
            ExecutionState.PARSE_SPEC,
            ExecutionState.NARRATOR_VOICE,
            ExecutionState.PLOT_OUTLINE,
            ExecutionState.SCENE_OUTLINE,
            ExecutionState.DRAFT_SCENE,
            ExecutionState.CONSISTENCY_CHECK,
            ExecutionState.STYLE_REVISION,
            ExecutionState.FINAL_ASSEMBLY,
        ]
        for state in working_states:
            valid = ExecutionLoop.VALID_TRANSITIONS[state]
            assert EventType.SUSPEND in valid, f"{state} must handle SUSPEND"
            assert valid[EventType.SUSPEND] == ExecutionState.SUSPENDED


class TestStateMachineSafety:
    """Test safety property: system never enters invalid state"""

    def test_no_unreachable_states(self):
        """Every state must be reachable from INIT"""
        reachable = {ExecutionState.INIT}
        changed = True

        while changed:
            changed = False
            for state in list(reachable):
                for event, next_state in ExecutionLoop.VALID_TRANSITIONS.get(state, {}).items():
                    if next_state not in reachable:
                        reachable.add(next_state)
                        changed = True

        for state in ExecutionState:
            assert state in reachable, f"State {state} is unreachable"

    def test_happy_path_reaches_complete(self):
        """Normal execution path leads to COMPLETE"""
        path = [
            (ExecutionState.INIT, EventType.START, ExecutionState.PARSE_SPEC),
            (ExecutionState.PARSE_SPEC, EventType.SPEC_PARSED, ExecutionState.NARRATOR_VOICE),
            (ExecutionState.NARRATOR_VOICE, EventType.VOICE_GENERATED, ExecutionState.PLOT_OUTLINE),
            (ExecutionState.PLOT_OUTLINE, EventType.PLOT_GENERATED, ExecutionState.SCENE_OUTLINE),
            (ExecutionState.SCENE_OUTLINE, EventType.SCENES_OUTLINED, ExecutionState.DRAFT_SCENE),
            (ExecutionState.DRAFT_SCENE, EventType.ALL_SCENES_DRAFTED, ExecutionState.CONSISTENCY_CHECK),
            (ExecutionState.CONSISTENCY_CHECK, EventType.CONSISTENCY_PASSED, ExecutionState.STYLE_REVISION),
            (ExecutionState.STYLE_REVISION, EventType.STYLE_REVISED, ExecutionState.FINAL_ASSEMBLY),
            (ExecutionState.FINAL_ASSEMBLY, EventType.ASSEMBLY_COMPLETE, ExecutionState.COMPLETE),
        ]

        for from_state, event, to_state in path:
            valid = ExecutionLoop.VALID_TRANSITIONS[from_state]
            assert event in valid, f"Event {event} not valid from {from_state}"
            assert valid[event] == to_state, f"Wrong target state for {from_state} + {event}"


class TestStateMachineLiveness:
    """Test liveness property: progress is always possible"""

    def test_no_deadlock_states(self):
        """No state should be a deadlock (except terminal states)"""
        terminal_states = {ExecutionState.COMPLETE}

        for state in ExecutionState:
            if state in terminal_states:
                continue

            valid = ExecutionLoop.VALID_TRANSITIONS.get(state, {})
            assert len(valid) > 0, f"State {state} is a deadlock"

    def test_scene_loop_can_exit(self):
        """DRAFT_SCENE state must be able to exit the loop"""
        valid = ExecutionLoop.VALID_TRANSITIONS[ExecutionState.DRAFT_SCENE]
        assert EventType.ALL_SCENES_DRAFTED in valid
        assert valid[EventType.ALL_SCENES_DRAFTED] == ExecutionState.CONSISTENCY_CHECK

    def test_consistency_failure_can_recover(self):
        """Consistency failure loops back but doesn't deadlock"""
        valid = ExecutionLoop.VALID_TRANSITIONS[ExecutionState.CONSISTENCY_CHECK]
        assert EventType.CONSISTENCY_FAILED in valid
        assert EventType.CONSISTENCY_PASSED in valid


class TestSevenBeatCoverage:
    """Test that state machine supports the seven-beat narrative structure"""

    def test_has_scene_drafting_state(self):
        """State machine must have scene drafting capability"""
        assert ExecutionState.DRAFT_SCENE in ExecutionLoop.VALID_TRANSITIONS

    def test_scene_can_loop(self):
        """Multiple scenes can be drafted sequentially"""
        valid = ExecutionLoop.VALID_TRANSITIONS[ExecutionState.DRAFT_SCENE]
        assert EventType.SCENE_DRAFTED in valid
        assert valid[EventType.SCENE_DRAFTED] == ExecutionState.DRAFT_SCENE

    def test_plot_outline_precedes_scenes(self):
        """Plot outline must come before scene drafting"""
        assert EventType.PLOT_GENERATED in ExecutionLoop.VALID_TRANSITIONS[ExecutionState.PLOT_OUTLINE]
        assert ExecutionLoop.VALID_TRANSITIONS[ExecutionState.PLOT_OUTLINE][EventType.PLOT_GENERATED] == ExecutionState.SCENE_OUTLINE

        assert EventType.SCENES_OUTLINED in ExecutionLoop.VALID_TRANSITIONS[ExecutionState.SCENE_OUTLINE]
        assert ExecutionLoop.VALID_TRANSITIONS[ExecutionState.SCENE_OUTLINE][EventType.SCENES_OUTLINED] == ExecutionState.DRAFT_SCENE
