import logging
import datetime
from typing import Dict, List, Callable, Any, Optional
from enum import Enum
from dataclasses import dataclass
from abc import ABC, abstractmethod
from pydantic import BaseModel


class HookEventType(str, Enum):
    """Types of lifecycle events"""
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PRE_GENERATION = "pre_generation"
    POST_GENERATION = "post_generation"
    STATE_SAVE = "state_save"
    STATE_RESTORE = "state_restore"
    ERROR = "error"
    APPROVAL_REQUEST = "approval_request"


@dataclass
class HookEvent:
    """Event data passed to hook handlers"""
    event_type: HookEventType
    timestamp: float
    data: Dict[str, Any]
    source: Optional[str] = None


class ApprovalRequest(BaseModel):
    """Model for approval requests"""
    tool_name: str
    parameters: Dict[str, Any]
    description: str
    risk_level: str = "medium"


class ApprovalResponse(BaseModel):
    """Model for approval responses"""
    approved: bool
    modified_parameters: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class HookHandler(ABC):
    """Abstract base class for hook handlers"""

    @abstractmethod
    def handle_event(self, event: HookEvent) -> None:
        """Handle a lifecycle event"""
        pass


class LoggingHookHandler(HookHandler):
    """Simple logging hook handler"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def handle_event(self, event: HookEvent) -> None:
        message = f"[{event.timestamp:.2f}] {event.event_type.value}: {event.source or 'unknown'} - {event.data}"
        self.logger.info(message)


class ApprovalHookHandler(HookHandler):
    """Hook handler for approval requests"""

    def __init__(self, approval_callback: Callable[[ApprovalRequest], ApprovalResponse]):
        self.approval_callback = approval_callback

    def handle_event(self, event: HookEvent) -> None:
        if event.event_type == HookEventType.APPROVAL_REQUEST:
            request = ApprovalRequest(**event.data)
            response = self.approval_callback(request)
            event.data["approval_response"] = response.dict()


class HookManager:
    """Manages lifecycle hooks and event dispatching"""

    def __init__(self):
        self._handlers: Dict[HookEventType, List[HookHandler]] = {
            event_type: [] for event_type in HookEventType
        }
        self._global_handlers: List[HookHandler] = []
        self.logger = logging.getLogger(__name__)

    def register_handler(self, handler: HookHandler, event_types: Optional[List[HookEventType]] = None) -> None:
        """Register a hook handler for specific event types"""
        if event_types is None:
            event_types = list(HookEventType)

        for event_type in event_types:
            self._handlers[event_type].append(handler)

    def register_global_handler(self, handler: HookHandler) -> None:
        """Register a handler that receives all event types"""
        self._global_handlers.append(handler)

    def unregister_handler(self, handler: HookHandler, event_types: Optional[List[HookEventType]] = None) -> None:
        """Unregister a hook handler"""
        if event_types is None:
            event_types = list(HookEventType)

        for event_type in event_types:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

    def dispatch_event(self, event: HookEvent) -> None:
        """Dispatch an event to all relevant handlers"""
        # Dispatch to type-specific handlers
        for handler in self._handlers.get(event.event_type, []):
            try:
                handler.handle_event(event)
            except Exception as e:
                self.logger.error(f"Error in hook handler for {event.event_type}: {str(e)}")

        # Dispatch to global handlers
        for handler in self._global_handlers:
            try:
                handler.handle_event(event)
            except Exception as e:
                self.logger.error(f"Error in global hook handler: {str(e)}")

    def trigger_tool_call(self, tool_name: str, parameters: Dict[str, Any]) -> None:
        """Trigger a tool call event"""
        event = HookEvent(
            event_type=HookEventType.TOOL_CALL,
            timestamp=datetime.now().timestamp(),
            source=tool_name,
            data={
                "tool_name": tool_name,
                "parameters": parameters
            }
        )
        self.dispatch_event(event)

    def trigger_tool_result(self, tool_name: str, result: Dict[str, Any], success: bool = True) -> None:
        """Trigger a tool result event"""
        event = HookEvent(
            event_type=HookEventType.TOOL_RESULT,
            timestamp=datetime.now().timestamp(),
            source=tool_name,
            data={
                "tool_name": tool_name,
                "result": result,
                "success": success
            }
        )
        self.dispatch_event(event)

    def trigger_pre_generation(self, generation_type: str, context: Dict[str, Any]) -> None:
        """Trigger a pre-generation event"""
        event = HookEvent(
            event_type=HookEventType.PRE_GENERATION,
            timestamp=datetime.now().timestamp(),
            source=generation_type,
            data={
                "generation_type": generation_type,
                "context": context
            }
        )
        self.dispatch_event(event)

    def trigger_post_generation(self, generation_type: str, result: Dict[str, Any]) -> None:
        """Trigger a post-generation event"""
        event = HookEvent(
            event_type=HookEventType.POST_GENERATION,
            timestamp=datetime.now().timestamp(),
            source=generation_type,
            data={
                "generation_type": generation_type,
                "result": result
            }
        )
        self.dispatch_event(event)

    def trigger_state_save(self, session_id: str, state_data: Dict[str, Any]) -> None:
        """Trigger a state save event"""
        event = HookEvent(
            event_type=HookEventType.STATE_SAVE,
            timestamp=datetime.now().timestamp(),
            source="state_store",
            data={
                "session_id": session_id,
                "state_data": state_data
            }
        )
        self.dispatch_event(event)

    def trigger_state_restore(self, session_id: str, snapshot_data: Dict[str, Any]) -> None:
        """Trigger a state restore event"""
        event = HookEvent(
            event_type=HookEventType.STATE_RESTORE,
            timestamp=datetime.now().timestamp(),
            source="state_store",
            data={
                "session_id": session_id,
                "snapshot_data": snapshot_data
            }
        )
        self.dispatch_event(event)

    def trigger_error(self, error_type: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Trigger an error event"""
        event = HookEvent(
            event_type=HookEventType.ERROR,
            timestamp=datetime.now().timestamp(),
            source=error_type,
            data={
                "error_type": error_type,
                "message": message,
                "context": context or {}
            }
        )
        self.dispatch_event(event)

    def request_approval(self, tool_name: str, parameters: Dict[str, Any], description: str, risk_level: str = "medium") -> ApprovalResponse:
        """Request approval for an action"""
        event = HookEvent(
            event_type=HookEventType.APPROVAL_REQUEST,
            timestamp=datetime.now().timestamp(),
            source=tool_name,
            data={
                "tool_name": tool_name,
                "parameters": parameters,
                "description": description,
                "risk_level": risk_level
            }
        )
        self.dispatch_event(event)

        # Extract approval response from event data
        approval_data = event.data.get("approval_response", {"approved": False})
        return ApprovalResponse(**approval_data)