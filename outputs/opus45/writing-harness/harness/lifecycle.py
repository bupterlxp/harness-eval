"""
lifecycle.py - L: Lifecycle Hooks Manager

Implements pre/post hook bus for boundary events, decoupled from component logic.
Covers at least 5 event types including approval gates and audit logging.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable
import uuid


class LifecycleEventType(str, Enum):
    """Types of lifecycle events"""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    STATE_TRANSITION = "state_transition"
    TOOL_PRE_EXECUTE = "tool_pre_execute"
    TOOL_POST_EXECUTE = "tool_post_execute"
    SNAPSHOT_CREATED = "snapshot_created"
    SNAPSHOT_RESTORED = "snapshot_restored"
    CONTEXT_COMPRESSED = "context_compressed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    ERROR_OCCURRED = "error_occurred"
    SCENE_DRAFTED = "scene_drafted"
    TRAJECTORY_RECORDED = "trajectory_recorded"


@dataclass
class LifecycleEvent:
    """Event passed through the hook system"""
    event_type: LifecycleEventType
    session_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    data: dict[str, Any] = field(default_factory=dict)
    source_component: str = ""
    cancellable: bool = False
    cancelled: bool = False
    cancel_reason: str = ""


class Hook(ABC):
    """Abstract base class for hooks"""

    name: str
    event_types: list[LifecycleEventType]
    priority: int = 0

    @abstractmethod
    def execute(self, event: LifecycleEvent) -> LifecycleEvent:
        """Execute the hook, potentially modifying the event"""
        pass


class FunctionHook(Hook):
    """Hook wrapping a simple function"""

    def __init__(
        self,
        name: str,
        event_types: list[LifecycleEventType],
        handler: Callable[[LifecycleEvent], LifecycleEvent | None],
        priority: int = 0
    ):
        self.name = name
        self.event_types = event_types
        self._handler = handler
        self.priority = priority

    def execute(self, event: LifecycleEvent) -> LifecycleEvent:
        result = self._handler(event)
        return result if result is not None else event


class ApprovalHook(Hook):
    """Hook that requests user approval for dangerous operations"""

    def __init__(
        self,
        name: str = "approval_gate",
        approval_handler: Callable[[str, dict[str, Any]], bool] | None = None
    ):
        self.name = name
        self.event_types = [LifecycleEventType.TOOL_PRE_EXECUTE]
        self.priority = 100
        self._approval_handler = approval_handler
        self._approved_operations: set[str] = set()

    def execute(self, event: LifecycleEvent) -> LifecycleEvent:
        tool_name = event.data.get("tool_name", "")
        requires_approval = event.data.get("requires_approval", False)

        if not requires_approval:
            return event

        operation_key = f"{tool_name}:{hash(str(event.data.get('args', {})))}"

        if operation_key in self._approved_operations:
            return event

        if self._approval_handler:
            approved = self._approval_handler(tool_name, event.data.get("args", {}))
            if approved:
                self._approved_operations.add(operation_key)
                return event
            else:
                event.cancelled = True
                event.cancel_reason = f"User denied approval for {tool_name}"
                return event

        event.cancelled = True
        event.cancel_reason = f"No approval handler for {tool_name}"
        return event

    def pre_approve(self, tool_name: str) -> None:
        """Pre-approve all calls to a specific tool"""
        self._approved_operations.add(f"{tool_name}:*")

    def is_approved(self, tool_name: str) -> bool:
        """Check if a tool is pre-approved"""
        return f"{tool_name}:*" in self._approved_operations


class AuditHook(Hook):
    """Hook that logs all events for audit trail"""

    def __init__(self, name: str = "audit_logger", log_path: str | None = None):
        self.name = name
        self.event_types = list(LifecycleEventType)
        self.priority = -100
        self._log: list[dict[str, Any]] = []
        self._log_path = log_path

    def execute(self, event: LifecycleEvent) -> LifecycleEvent:
        record = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "session_id": event.session_id,
            "timestamp": event.timestamp.isoformat(),
            "source": event.source_component,
            "data_keys": list(event.data.keys()),
            "cancelled": event.cancelled,
            "cancel_reason": event.cancel_reason
        }
        self._log.append(record)

        if self._log_path:
            import json
            with open(self._log_path, "a") as f:
                f.write(json.dumps(record) + "\n")

        return event

    def get_log(self) -> list[dict[str, Any]]:
        """Get the audit log"""
        return self._log.copy()

    def get_events_by_type(self, event_type: LifecycleEventType) -> list[dict[str, Any]]:
        """Get events filtered by type"""
        return [e for e in self._log if e["event_type"] == event_type.value]


class HookManager:
    """
    L component: Manages lifecycle hooks.

    Provides:
    - Registration of pre/post hooks
    - Event dispatch to registered hooks
    - Priority ordering
    - Cancellation support
    """

    def __init__(self):
        self._hooks: dict[LifecycleEventType, list[Hook]] = {
            event_type: [] for event_type in LifecycleEventType
        }
        self._global_hooks: list[Hook] = []

    def register(self, hook: Hook) -> None:
        """Register a hook for its specified event types"""
        for event_type in hook.event_types:
            self._hooks[event_type].append(hook)
            self._hooks[event_type].sort(key=lambda h: -h.priority)

    def register_global(self, hook: Hook) -> None:
        """Register a hook that receives all events"""
        self._global_hooks.append(hook)
        self._global_hooks.sort(key=lambda h: -h.priority)

    def unregister(self, hook_name: str) -> None:
        """Unregister a hook by name"""
        for event_type in LifecycleEventType:
            self._hooks[event_type] = [
                h for h in self._hooks[event_type] if h.name != hook_name
            ]
        self._global_hooks = [h for h in self._global_hooks if h.name != hook_name]

    def emit(self, event: LifecycleEvent) -> LifecycleEvent:
        """
        Emit an event through the hook pipeline.

        Hooks are executed in priority order.
        If any hook cancels a cancellable event, processing stops.
        """
        all_hooks = self._global_hooks + self._hooks.get(event.event_type, [])
        all_hooks.sort(key=lambda h: -h.priority)

        for hook in all_hooks:
            try:
                event = hook.execute(event)
                if event.cancellable and event.cancelled:
                    break
            except Exception as e:
                event.data["hook_error"] = {
                    "hook": hook.name,
                    "error": str(e)
                }

        return event

    def emit_simple(
        self,
        event_type: LifecycleEventType,
        session_id: str,
        data: dict[str, Any] | None = None,
        source: str = "",
        cancellable: bool = False
    ) -> LifecycleEvent:
        """Convenience method to emit an event with minimal ceremony"""
        event = LifecycleEvent(
            event_type=event_type,
            session_id=session_id,
            data=data or {},
            source_component=source,
            cancellable=cancellable
        )
        return self.emit(event)

    def on(
        self,
        event_types: LifecycleEventType | list[LifecycleEventType],
        priority: int = 0
    ) -> Callable:
        """Decorator to register a function as a hook"""
        if isinstance(event_types, LifecycleEventType):
            event_types = [event_types]

        def decorator(func: Callable[[LifecycleEvent], LifecycleEvent | None]) -> Callable:
            hook = FunctionHook(
                name=func.__name__,
                event_types=event_types,
                handler=func,
                priority=priority
            )
            self.register(hook)
            return func

        return decorator

    def get_hooks(self, event_type: LifecycleEventType) -> list[Hook]:
        """Get all hooks registered for an event type"""
        return self._hooks.get(event_type, []).copy()

    def create_approval_hook(
        self,
        handler: Callable[[str, dict[str, Any]], bool] | None = None
    ) -> ApprovalHook:
        """Create and register an approval hook"""
        hook = ApprovalHook(approval_handler=handler)
        self.register(hook)
        return hook

    def create_audit_hook(self, log_path: str | None = None) -> AuditHook:
        """Create and register an audit hook"""
        hook = AuditHook(log_path=log_path)
        self.register_global(hook)
        return hook
