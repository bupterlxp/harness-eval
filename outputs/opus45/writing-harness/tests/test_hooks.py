"""
test_hooks.py - Tests for L component lifecycle hooks

Tests hook registration, event dispatch, and decoupling from component logic.
"""

import pytest
from datetime import datetime

from harness.lifecycle import (
    HookManager, LifecycleEventType, LifecycleEvent,
    FunctionHook, ApprovalHook, AuditHook
)


class TestHookRegistration:
    """Test hook registration and lookup"""

    def test_register_function_hook(self):
        """Can register a function as a hook"""
        manager = HookManager()

        @manager.on(LifecycleEventType.SESSION_START)
        def on_start(event):
            event.data["started"] = True
            return event

        hooks = manager.get_hooks(LifecycleEventType.SESSION_START)
        assert len(hooks) == 1
        assert hooks[0].name == "on_start"

    def test_register_multiple_event_types(self):
        """Hook can register for multiple event types"""
        manager = HookManager()

        @manager.on([LifecycleEventType.SESSION_START, LifecycleEventType.SESSION_END])
        def on_session(event):
            return event

        start_hooks = manager.get_hooks(LifecycleEventType.SESSION_START)
        end_hooks = manager.get_hooks(LifecycleEventType.SESSION_END)

        assert len(start_hooks) == 1
        assert len(end_hooks) == 1

    def test_unregister_hook(self):
        """Can unregister a hook by name"""
        manager = HookManager()

        @manager.on(LifecycleEventType.SESSION_START)
        def temporary_hook(event):
            return event

        assert len(manager.get_hooks(LifecycleEventType.SESSION_START)) == 1

        manager.unregister("temporary_hook")

        assert len(manager.get_hooks(LifecycleEventType.SESSION_START)) == 0

    def test_priority_ordering(self):
        """Hooks execute in priority order (higher first)"""
        manager = HookManager()
        execution_order = []

        @manager.on(LifecycleEventType.SESSION_START, priority=10)
        def low_priority(event):
            execution_order.append("low")
            return event

        @manager.on(LifecycleEventType.SESSION_START, priority=50)
        def high_priority(event):
            execution_order.append("high")
            return event

        @manager.on(LifecycleEventType.SESSION_START, priority=30)
        def mid_priority(event):
            execution_order.append("mid")
            return event

        event = LifecycleEvent(
            event_type=LifecycleEventType.SESSION_START,
            session_id="test"
        )
        manager.emit(event)

        assert execution_order == ["high", "mid", "low"]


class TestEventEmission:
    """Test event emission and handling"""

    def test_emit_simple(self):
        """Can emit simple events"""
        manager = HookManager()
        received = []

        @manager.on(LifecycleEventType.STATE_TRANSITION)
        def on_transition(event):
            received.append(event)
            return event

        manager.emit_simple(
            LifecycleEventType.STATE_TRANSITION,
            "session-123",
            {"from": "INIT", "to": "PARSE_SPEC"}
        )

        assert len(received) == 1
        assert received[0].session_id == "session-123"
        assert received[0].data["from"] == "INIT"

    def test_event_modification(self):
        """Hooks can modify event data"""
        manager = HookManager()

        @manager.on(LifecycleEventType.TOOL_PRE_EXECUTE)
        def add_timestamp(event):
            event.data["hook_timestamp"] = "2024-01-01"
            return event

        event = manager.emit_simple(
            LifecycleEventType.TOOL_PRE_EXECUTE,
            "test",
            {"tool_name": "draft_scene"}
        )

        assert event.data["hook_timestamp"] == "2024-01-01"

    def test_cancellable_events(self):
        """Cancellable events can be cancelled by hooks"""
        manager = HookManager()

        @manager.on(LifecycleEventType.TOOL_PRE_EXECUTE, priority=100)
        def cancel_dangerous(event):
            if event.data.get("dangerous"):
                event.cancelled = True
                event.cancel_reason = "Dangerous operation blocked"
            return event

        @manager.on(LifecycleEventType.TOOL_PRE_EXECUTE, priority=50)
        def should_not_run(event):
            event.data["reached_second_hook"] = True
            return event

        event = LifecycleEvent(
            event_type=LifecycleEventType.TOOL_PRE_EXECUTE,
            session_id="test",
            data={"dangerous": True},
            cancellable=True
        )

        result = manager.emit(event)

        assert result.cancelled
        assert result.cancel_reason == "Dangerous operation blocked"
        assert "reached_second_hook" not in result.data


class TestApprovalHook:
    """Test approval gate functionality"""

    def test_approval_required_for_dangerous_tools(self):
        """Dangerous tools require approval"""
        manager = HookManager()
        hook = manager.create_approval_hook(lambda t, a: False)

        event = LifecycleEvent(
            event_type=LifecycleEventType.TOOL_PRE_EXECUTE,
            session_id="test",
            data={"tool_name": "draft_scene", "requires_approval": True, "args": {}},
            cancellable=True
        )

        result = manager.emit(event)
        assert result.cancelled

    def test_approval_granted(self):
        """Approved operations proceed"""
        manager = HookManager()
        hook = manager.create_approval_hook(lambda t, a: True)

        event = LifecycleEvent(
            event_type=LifecycleEventType.TOOL_PRE_EXECUTE,
            session_id="test",
            data={"tool_name": "draft_scene", "requires_approval": True, "args": {}},
            cancellable=True
        )

        result = manager.emit(event)
        assert not result.cancelled

    def test_pre_approve_tool(self):
        """Can pre-approve specific tools"""
        hook = ApprovalHook(approval_handler=lambda t, a: False)

        hook.pre_approve("safe_tool")

        assert hook.is_approved("safe_tool")
        assert not hook.is_approved("other_tool")

    def test_safe_operations_bypass_approval(self):
        """Safe operations don't require approval"""
        manager = HookManager()
        manager.create_approval_hook(lambda t, a: False)

        event = LifecycleEvent(
            event_type=LifecycleEventType.TOOL_PRE_EXECUTE,
            session_id="test",
            data={"tool_name": "check_consistency", "requires_approval": False, "args": {}},
            cancellable=True
        )

        result = manager.emit(event)
        assert not result.cancelled


class TestAuditHook:
    """Test audit logging functionality"""

    def test_audit_captures_all_events(self):
        """Audit hook captures all event types"""
        manager = HookManager()
        audit = manager.create_audit_hook()

        manager.emit_simple(LifecycleEventType.SESSION_START, "test")
        manager.emit_simple(LifecycleEventType.STATE_TRANSITION, "test", {"from": "A", "to": "B"})
        manager.emit_simple(LifecycleEventType.SESSION_END, "test")

        log = audit.get_log()
        assert len(log) == 3

        types = [e["event_type"] for e in log]
        assert "session_start" in types
        assert "state_transition" in types
        assert "session_end" in types

    def test_audit_records_timestamps(self):
        """Audit entries have timestamps"""
        manager = HookManager()
        audit = manager.create_audit_hook()

        manager.emit_simple(LifecycleEventType.SESSION_START, "test")

        log = audit.get_log()
        assert len(log) == 1
        assert "timestamp" in log[0]

    def test_filter_by_event_type(self):
        """Can filter audit log by event type"""
        manager = HookManager()
        audit = manager.create_audit_hook()

        manager.emit_simple(LifecycleEventType.SESSION_START, "test")
        manager.emit_simple(LifecycleEventType.TOOL_PRE_EXECUTE, "test")
        manager.emit_simple(LifecycleEventType.TOOL_POST_EXECUTE, "test")
        manager.emit_simple(LifecycleEventType.SESSION_END, "test")

        tool_events = audit.get_events_by_type(LifecycleEventType.TOOL_PRE_EXECUTE)
        assert len(tool_events) == 1


class TestHookDecoupling:
    """Test that hooks are decoupled from component logic"""

    def test_hooks_dont_know_about_tools(self):
        """Hooks receive data but don't import tool implementations"""
        manager = HookManager()
        received_data = []

        @manager.on(LifecycleEventType.TOOL_PRE_EXECUTE)
        def generic_hook(event):
            received_data.append(event.data.get("tool_name"))
            return event

        manager.emit_simple(
            LifecycleEventType.TOOL_PRE_EXECUTE,
            "test",
            {"tool_name": "some_tool", "args": {}}
        )

        assert received_data == ["some_tool"]

    def test_hooks_isolated_from_errors(self):
        """Hook errors don't crash the system"""
        manager = HookManager()

        @manager.on(LifecycleEventType.SESSION_START)
        def broken_hook(event):
            raise RuntimeError("Hook crashed!")

        @manager.on(LifecycleEventType.SESSION_START, priority=-10)
        def working_hook(event):
            event.data["working"] = True
            return event

        event = LifecycleEvent(
            event_type=LifecycleEventType.SESSION_START,
            session_id="test"
        )

        result = manager.emit(event)
        assert "hook_error" in result.data
        assert result.data.get("working") is True
