"""
state.py - State management for the browser agent harness.

Implements:
- TaskGraph: Directed graph of task steps with dependency tracking
- CrossPageDataStore: Persistent data storage across page navigations
- CheckpointManager: Save/restore execution state for resumption
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.schemas import (
    AttendanceReport,
    DashboardStats,
    EmployeeInfo,
    LeaveRequest,
    Screenshot,
    StepStatus,
    TaskPhase,
    TaskStep,
)


@dataclass
class TaskNode:
    """Node in the task graph."""
    step: TaskStep
    dependencies: list[int] = field(default_factory=list)
    dependents: list[int] = field(default_factory=list)


class TaskGraph:
    """Directed acyclic graph of task steps with dependency tracking."""

    def __init__(self) -> None:
        self._nodes: dict[int, TaskNode] = {}
        self._execution_order: list[int] = []

    def add_step(
        self,
        step: TaskStep,
        dependencies: list[int] | None = None,
    ) -> None:
        """Add a task step to the graph."""
        deps = dependencies or step.depends_on
        node = TaskNode(step=step, dependencies=deps)
        self._nodes[step.step_id] = node

        for dep_id in deps:
            if dep_id in self._nodes:
                self._nodes[dep_id].dependents.append(step.step_id)

        self._compute_execution_order()

    def _compute_execution_order(self) -> None:
        """Compute topological order for execution."""
        visited = set()
        order = []

        def visit(node_id: int) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            node = self._nodes.get(node_id)
            if node:
                for dep_id in node.dependencies:
                    visit(dep_id)
                order.append(node_id)

        for node_id in self._nodes:
            visit(node_id)

        self._execution_order = order

    def get_step(self, step_id: int) -> TaskStep | None:
        """Get a step by ID."""
        node = self._nodes.get(step_id)
        return node.step if node else None

    def get_all_steps(self) -> list[TaskStep]:
        """Get all steps in execution order."""
        return [self._nodes[sid].step for sid in self._execution_order if sid in self._nodes]

    def get_next_executable(self) -> TaskStep | None:
        """Get the next step that can be executed."""
        for step_id in self._execution_order:
            node = self._nodes.get(step_id)
            if not node:
                continue
            step = node.step
            if step.status != StepStatus.PENDING:
                continue

            deps_satisfied = all(
                self._nodes[dep_id].step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
                for dep_id in node.dependencies
                if dep_id in self._nodes
            )
            if deps_satisfied:
                return step

        return None

    def update_step_status(
        self,
        step_id: int,
        status: StepStatus,
        error_message: str | None = None,
    ) -> None:
        """Update the status of a step."""
        node = self._nodes.get(step_id)
        if node:
            node.step.status = status
            if error_message:
                node.step.error_message = error_message
            if status == StepStatus.RUNNING:
                node.step.started_at = datetime.now()
            elif status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED):
                node.step.completed_at = datetime.now()
                if node.step.started_at:
                    delta = node.step.completed_at - node.step.started_at
                    node.step.duration_ms = int(delta.total_seconds() * 1000)

    def can_continue(self) -> bool:
        """Check if there are more steps to execute."""
        return self.get_next_executable() is not None

    def is_complete(self) -> bool:
        """Check if all steps are finished."""
        for node in self._nodes.values():
            if node.step.status == StepStatus.PENDING:
                return False
            if node.step.status == StepStatus.RUNNING:
                return False
        return True

    def get_stats(self) -> dict[str, int]:
        """Get execution statistics."""
        stats = {
            "total": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        }
        for node in self._nodes.values():
            stats["total"] += 1
            stats[node.step.status.value] += 1
        return stats

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph state for checkpointing."""
        return {
            "nodes": {
                str(sid): {
                    "step": node.step.to_dict(),
                    "dependencies": node.dependencies,
                    "dependents": node.dependents,
                }
                for sid, node in self._nodes.items()
            },
            "execution_order": self._execution_order,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskGraph":
        """Deserialize graph state from checkpoint."""
        graph = cls()
        for sid_str, node_data in data.get("nodes", {}).items():
            sid = int(sid_str)
            step_data = node_data["step"]
            step = TaskStep(
                step_id=step_data["step_id"],
                action=step_data["action"],
                description=step_data["description"],
                status=StepStatus(step_data["status"]),
                extracted_data=step_data.get("extracted_data", {}),
                screenshot_path=step_data.get("screenshot_path"),
                error_message=step_data.get("error_message"),
                retry_count=step_data.get("retry_count", 0),
                duration_ms=step_data.get("duration_ms"),
            )
            graph._nodes[sid] = TaskNode(
                step=step,
                dependencies=node_data.get("dependencies", []),
                dependents=node_data.get("dependents", []),
            )
        graph._execution_order = data.get("execution_order", [])
        return graph


class CrossPageDataStore:
    """Persistent data storage across page navigations."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._dashboard_stats: DashboardStats | None = None
        self._employees: dict[int, EmployeeInfo] = {}
        self._leave_requests: dict[int, LeaveRequest] = {}
        self._attendance_reports: list[AttendanceReport] = []
        self._screenshots: list[Screenshot] = []
        self._session_cookies: dict[str, str] = {}

    def set(self, key: str, value: Any) -> None:
        """Store a value."""
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value."""
        return self._data.get(key, default)

    def has(self, key: str) -> bool:
        """Check if a key exists."""
        return key in self._data

    def set_dashboard_stats(self, stats: DashboardStats) -> None:
        """Store dashboard statistics."""
        self._dashboard_stats = stats
        self._data["dashboard"] = stats.to_dict()

    def get_dashboard_stats(self) -> DashboardStats | None:
        """Retrieve dashboard statistics."""
        return self._dashboard_stats

    def add_employee(self, employee: EmployeeInfo) -> None:
        """Store employee information."""
        if employee.employee_id:
            self._employees[employee.employee_id] = employee
            self._data[f"employee_{employee.employee_id}"] = employee.to_dict()

    def get_employee(self, employee_id: int) -> EmployeeInfo | None:
        """Retrieve employee by ID."""
        return self._employees.get(employee_id)

    def add_leave_request(self, request: LeaveRequest) -> None:
        """Store leave request."""
        if request.request_id:
            self._leave_requests[request.request_id] = request
            self._data[f"leave_request_{request.request_id}"] = request.to_dict()

    def add_attendance_report(self, report: AttendanceReport) -> None:
        """Store attendance report."""
        self._attendance_reports.append(report)
        key = f"attendance_{report.department}_{report.month}"
        self._data[key] = report.to_dict()

    def add_screenshot(self, screenshot: Screenshot) -> None:
        """Store screenshot metadata."""
        self._screenshots.append(screenshot)

    def get_screenshots(self) -> list[Screenshot]:
        """Get all screenshots."""
        return self._screenshots

    def set_session_cookie(self, name: str, value: str) -> None:
        """Store session cookie."""
        self._session_cookies[name] = value

    def get_session_cookies(self) -> dict[str, str]:
        """Get all session cookies."""
        return self._session_cookies

    def get_all_extracted_data(self) -> dict[str, Any]:
        """Get all extracted data for final report."""
        result = dict(self._data)
        if self._dashboard_stats:
            result["dashboard"] = self._dashboard_stats.to_dict()
        if self._employees:
            result["employees"] = {
                eid: emp.to_dict() for eid, emp in self._employees.items()
            }
        if self._leave_requests:
            result["leave_requests"] = {
                rid: req.to_dict() for rid, req in self._leave_requests.items()
            }
        if self._attendance_reports:
            result["attendance"] = [r.to_dict() for r in self._attendance_reports]
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize store for checkpointing."""
        return {
            "data": self._data,
            "session_cookies": self._session_cookies,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrossPageDataStore":
        """Deserialize store from checkpoint."""
        store = cls()
        store._data = data.get("data", {})
        store._session_cookies = data.get("session_cookies", {})
        return store


class CheckpointManager:
    """Manages save/restore of execution state."""

    def __init__(self, checkpoint_dir: str = ".checkpoints") -> None:
        self._checkpoint_dir = Path(checkpoint_dir)
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        task_graph: TaskGraph,
        data_store: CrossPageDataStore,
        current_phase: TaskPhase,
        checkpoint_name: str | None = None,
    ) -> str:
        """Save current execution state."""
        name = checkpoint_name or f"checkpoint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        path = self._checkpoint_dir / f"{name}.json"

        state = {
            "timestamp": datetime.now().isoformat(),
            "current_phase": current_phase.value,
            "task_graph": task_graph.to_dict(),
            "data_store": data_store.to_dict(),
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        return str(path)

    def load(self, checkpoint_path: str) -> tuple[TaskGraph, CrossPageDataStore, TaskPhase]:
        """Load execution state from checkpoint."""
        with open(checkpoint_path, encoding="utf-8") as f:
            state = json.load(f)

        task_graph = TaskGraph.from_dict(state["task_graph"])
        data_store = CrossPageDataStore.from_dict(state["data_store"])
        current_phase = TaskPhase(state["current_phase"])

        return task_graph, data_store, current_phase

    def list_checkpoints(self) -> list[str]:
        """List available checkpoints."""
        return [str(p) for p in self._checkpoint_dir.glob("*.json")]

    def get_latest(self) -> str | None:
        """Get the most recent checkpoint."""
        checkpoints = list(self._checkpoint_dir.glob("*.json"))
        if not checkpoints:
            return None
        return str(max(checkpoints, key=os.path.getmtime))
