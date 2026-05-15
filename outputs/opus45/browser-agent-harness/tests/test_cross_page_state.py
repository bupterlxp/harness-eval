"""
test_cross_page_state.py - Tests for cross-page state persistence.

Verifies:
- Login session maintained across navigation
- Extracted data preserved after page changes
- Context manager tracks navigation history
"""

import pytest
from harness.state import CrossPageDataStore, CheckpointManager, TaskGraph
from harness.context import ContextManager, PageContext, TaskContext, NavigationHistory
from harness.schemas import (
    DashboardStats,
    EmployeeInfo,
    InteractableElement,
    LeaveRequest,
    PageState,
    Screenshot,
    StepStatus,
    TaskPhase,
    TaskStep,
)


class TestCrossPageDataStore:
    """Tests for CrossPageDataStore."""

    def test_set_and_get(self) -> None:
        """Basic key-value storage works."""
        store = CrossPageDataStore()

        store.set("login_success", True)
        store.set("user_name", "admin")
        store.set("employee_count", 50)

        assert store.get("login_success") is True
        assert store.get("user_name") == "admin"
        assert store.get("employee_count") == 50

    def test_get_with_default(self) -> None:
        """get returns default for missing keys."""
        store = CrossPageDataStore()

        assert store.get("missing") is None
        assert store.get("missing", "default") == "default"

    def test_has(self) -> None:
        """has correctly checks key existence."""
        store = CrossPageDataStore()

        store.set("exists", True)

        assert store.has("exists") is True
        assert store.has("not_exists") is False

    def test_dashboard_stats(self) -> None:
        """Dashboard stats are stored and retrieved correctly."""
        store = CrossPageDataStore()

        stats = DashboardStats(
            total_employees=50,
            pending_leaves=8,
            new_hires=3,
            contract_expiring=2,
        )
        store.set_dashboard_stats(stats)

        retrieved = store.get_dashboard_stats()
        assert retrieved is not None
        assert retrieved.total_employees == 50
        assert retrieved.pending_leaves == 8

    def test_employee_storage(self) -> None:
        """Employee info is stored and retrieved by ID."""
        store = CrossPageDataStore()

        emp = EmployeeInfo(
            employee_id=51,
            name="张伟",
            department="技术部",
            position="高级工程师",
            hire_date="2021-03-15",
            annual_leave_balance=8.5,
            performance_score=85.2,
        )
        store.add_employee(emp)

        retrieved = store.get_employee(51)
        assert retrieved is not None
        assert retrieved.name == "张伟"
        assert retrieved.department == "技术部"

    def test_session_cookies(self) -> None:
        """Session cookies are stored."""
        store = CrossPageDataStore()

        store.set_session_cookie("session_id", "abc123")
        store.set_session_cookie("csrf_token", "xyz789")

        cookies = store.get_session_cookies()
        assert cookies["session_id"] == "abc123"
        assert cookies["csrf_token"] == "xyz789"

    def test_get_all_extracted_data(self) -> None:
        """All extracted data is aggregated correctly."""
        store = CrossPageDataStore()

        store.set("step_1_done", True)
        store.set_dashboard_stats(DashboardStats(total_employees=50))
        store.add_employee(EmployeeInfo(employee_id=1, name="Test"))

        all_data = store.get_all_extracted_data()

        assert "step_1_done" in all_data
        assert "dashboard" in all_data
        assert "employees" in all_data

    def test_serialization_roundtrip(self) -> None:
        """Store can be serialized and restored."""
        store = CrossPageDataStore()

        store.set("key1", "value1")
        store.set_session_cookie("session", "abc")

        data = store.to_dict()
        restored = CrossPageDataStore.from_dict(data)

        assert restored.get("key1") == "value1"
        assert restored.get_session_cookies()["session"] == "abc"


class TestNavigationHistory:
    """Tests for NavigationHistory."""

    def test_push_and_get_current(self) -> None:
        """Navigation entries are tracked."""
        history = NavigationHistory()

        history.push("http://localhost:5000/login", "Login", step_id=2)
        history.push("http://localhost:5000/dashboard", "Dashboard", step_id=3)

        current = history.get_current()
        assert current is not None
        assert current.url == "http://localhost:5000/dashboard"
        assert current.step_id == 3

    def test_get_previous(self) -> None:
        """Previous entry is retrievable."""
        history = NavigationHistory()

        history.push("http://localhost:5000/login", "Login")
        history.push("http://localhost:5000/dashboard", "Dashboard")

        prev = history.get_previous()
        assert prev is not None
        assert prev.url == "http://localhost:5000/login"

    def test_can_go_back(self) -> None:
        """can_go_back reflects history state."""
        history = NavigationHistory()

        assert history.can_go_back() is False

        history.push("http://localhost:5000/login", "Login")
        assert history.can_go_back() is False

        history.push("http://localhost:5000/dashboard", "Dashboard")
        assert history.can_go_back() is True

    def test_find_by_url(self) -> None:
        """Find entry by URL."""
        history = NavigationHistory()

        history.push("http://localhost:5000/login", "Login", step_id=2)
        history.push("http://localhost:5000/dashboard", "Dashboard", step_id=4)
        history.push("http://localhost:5000/employees", "Employees", step_id=5)

        entry = history.find_by_url("http://localhost:5000/dashboard")
        assert entry is not None
        assert entry.step_id == 4

    def test_max_entries_limit(self) -> None:
        """History is trimmed to max entries."""
        history = NavigationHistory(max_entries=3)

        for i in range(5):
            history.push(f"http://localhost:5000/page{i}", f"Page {i}")

        all_history = history.get_history(limit=10)
        assert len(all_history) == 3
        assert all_history[0].url == "http://localhost:5000/page2"


class TestPageContext:
    """Tests for PageContext."""

    def test_update_state(self) -> None:
        """Page state is updated correctly."""
        ctx = PageContext()

        state = PageState(
            url="http://localhost:5000/login",
            title="Login",
            has_popup=True,
            popup_type="cookie_banner",
        )
        ctx.update(state)

        assert ctx.current_url == "http://localhost:5000/login"
        assert ctx.current_title == "Login"
        assert ctx.has_popup is True
        assert ctx.popup_type == "cookie_banner"

    def test_find_element_by_text(self) -> None:
        """Find element by text content."""
        ctx = PageContext()

        elements = [
            InteractableElement(
                tag="button",
                element_type="submit",
                selector="#login-btn",
                text="登 录",
                placeholder=None,
                aria_label=None,
                name=None,
                element_id="login-btn",
            ),
            InteractableElement(
                tag="button",
                element_type="button",
                selector="#reset-btn",
                text="重置",
                placeholder=None,
                aria_label=None,
                name=None,
                element_id="reset-btn",
            ),
        ]

        state = PageState(
            url="http://localhost:5000/login",
            title="Login",
            interactable_elements=elements,
        )
        ctx.update(state)

        found = ctx.find_element_by_text("登 录")
        assert found is not None
        assert found.selector == "#login-btn"

    def test_popup_state_management(self) -> None:
        """Popup state is managed independently."""
        ctx = PageContext()

        state = PageState(url="http://localhost:5000", title="Test")
        ctx.update(state)

        assert ctx.has_popup is False

        ctx.set_popup_state(True, "cookie_banner")
        assert ctx.has_popup is True
        assert ctx.popup_type == "cookie_banner"

        ctx.set_popup_state(False)
        assert ctx.has_popup is False
        assert ctx.popup_type is None


class TestTaskContext:
    """Tests for TaskContext."""

    def test_step_tracking(self) -> None:
        """Steps are tracked correctly."""
        ctx = TaskContext()

        step1 = TaskStep(step_id=1, action="Init", description="Initialize")
        step2 = TaskStep(step_id=2, action="Login", description="Login")

        ctx.add_step(step1)
        ctx.add_step(step2)

        assert ctx.get_step(1) == step1
        assert ctx.get_step(2) == step2

    def test_current_step(self) -> None:
        """Current step is tracked."""
        ctx = TaskContext()

        step1 = TaskStep(step_id=1, action="Init", description="Initialize")
        ctx.add_step(step1)

        assert ctx.current_step is None

        ctx.set_current_step(1)
        assert ctx.current_step == step1

        ctx.set_current_step(None)
        assert ctx.current_step is None

    def test_extracted_data_storage(self) -> None:
        """Extracted data is stored across steps."""
        ctx = TaskContext()

        ctx.store_extracted_data("dashboard_stats", {"total": 50})
        ctx.store_extracted_data("search_count", 5)

        assert ctx.get_extracted_data("dashboard_stats") == {"total": 50}
        assert ctx.get_extracted_data("search_count") == 5

        all_data = ctx.get_all_extracted_data()
        assert len(all_data) == 2


class TestContextManager:
    """Tests for unified ContextManager."""

    def test_on_page_load(self) -> None:
        """on_page_load updates all contexts."""
        manager = ContextManager()

        state = PageState(
            url="http://localhost:5000/dashboard",
            title="Dashboard",
        )
        manager.on_page_load(state, step_id=4)

        assert manager.page.current_url == "http://localhost:5000/dashboard"
        assert manager.navigation.get_current().url == "http://localhost:5000/dashboard"
        assert manager.navigation.get_current().step_id == 4

    def test_get_full_context(self) -> None:
        """Full context summary is generated."""
        manager = ContextManager()

        state = PageState(
            url="http://localhost:5000/employees",
            title="Employees",
        )
        manager.on_page_load(state, step_id=5)

        step = TaskStep(step_id=5, action="Search", description="Search employees")
        step.status = StepStatus.RUNNING
        manager.task.add_step(step)
        manager.task.set_current_step(5)

        summary = manager.get_full_context()

        assert "employees" in summary.lower()
        assert "search" in summary.lower()


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_save_and_load(self, tmp_path) -> None:
        """Checkpoint save and load works."""
        manager = CheckpointManager(str(tmp_path / "checkpoints"))

        graph = TaskGraph()
        step1 = TaskStep(step_id=1, action="Test", description="Test")
        graph.add_step(step1, dependencies=[])
        graph.update_step_status(1, StepStatus.COMPLETED)

        store = CrossPageDataStore()
        store.set("test_key", "test_value")

        checkpoint_path = manager.save(graph, store, TaskPhase.DASHBOARD, "test_checkpoint")

        loaded_graph, loaded_store, loaded_phase = manager.load(checkpoint_path)

        assert loaded_graph.get_step(1).status == StepStatus.COMPLETED
        assert loaded_store.get("test_key") == "test_value"
        assert loaded_phase == TaskPhase.DASHBOARD

    def test_list_checkpoints(self, tmp_path) -> None:
        """Checkpoints are listed."""
        manager = CheckpointManager(str(tmp_path / "checkpoints"))

        graph = TaskGraph()
        store = CrossPageDataStore()

        manager.save(graph, store, TaskPhase.INIT, "cp1")
        manager.save(graph, store, TaskPhase.LOGIN, "cp2")

        checkpoints = manager.list_checkpoints()
        assert len(checkpoints) == 2
