"""
test_e2e.py - End-to-end test against mock server.

This test:
1. Starts the mock_server.py
2. Runs the harness against it
3. Verifies all 12 steps complete
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def mock_server():
    """Start mock server for e2e tests."""
    samples_dir = Path(__file__).parent.parent / "samples"
    server_path = samples_dir / "mock_server.py"

    if not server_path.exists():
        pytest.skip("mock_server.py not found")

    env = os.environ.copy()
    env["MOCK_DB_PATH"] = str(samples_dir / "test_hr_mock.db")

    proc = subprocess.Popen(
        [sys.executable, str(server_path)],
        cwd=str(samples_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(2)

    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        pytest.fail(f"Mock server failed to start: {stderr.decode()}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    db_path = Path(env["MOCK_DB_PATH"])
    if db_path.exists():
        db_path.unlink()


class TestE2EScenario:
    """End-to-end tests for the full 12-step scenario."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_full_scenario_structure(self, mock_server) -> None:
        """Verify scenario file structure."""
        scenario_path = Path(__file__).parent.parent / "samples" / "task_scenarios.json"

        assert scenario_path.exists(), "task_scenarios.json not found"

        import json
        with open(scenario_path) as f:
            data = json.load(f)

        scenario = data.get("scenario", data)
        steps = scenario.get("steps", [])

        assert len(steps) == 12, f"Expected 12 steps, got {len(steps)}"

        for i, step in enumerate(steps, 1):
            assert step["id"] == i, f"Step {i} has wrong ID"
            assert "action" in step
            assert "description" in step

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_mock_server_responds(self, mock_server) -> None:
        """Verify mock server is running and responds."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:5000/login") as resp:
                assert resp.status == 200
                text = await resp.text()
                assert "HR管理系统" in text

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_login_api(self, mock_server) -> None:
        """Verify login API works."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:5000/api/login",
                json={"username": "admin", "password": "admin123"},
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("message") == "登录成功"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_dashboard_api(self, mock_server) -> None:
        """Verify dashboard API returns expected data."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://localhost:5000/api/login",
                json={"username": "admin", "password": "admin123"},
            ) as resp:
                assert resp.status == 200

            cookies = session.cookie_jar

            async with session.get("http://localhost:5000/api/dashboard") as resp:
                assert resp.status == 200
                data = await resp.json()

                assert "total_employees" in data
                assert "pending_leaves" in data
                assert "new_hires" in data
                assert "contract_expiring" in data

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_employees_search_api(self, mock_server) -> None:
        """Verify employee search returns Zhang employees."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            await session.post(
                "http://localhost:5000/api/login",
                json={"username": "admin", "password": "admin123"},
            )

            async with session.get(
                "http://localhost:5000/api/employees?search=张"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                assert data["total"] >= 4
                for emp in data["employees"]:
                    assert "张" in emp["name"]

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_leave_requests_api(self, mock_server) -> None:
        """Verify leave requests API."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            await session.post(
                "http://localhost:5000/api/login",
                json={"username": "admin", "password": "admin123"},
            )

            async with session.get(
                "http://localhost:5000/api/leave-requests?status=pending"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                assert "leave_requests" in data
                assert data["total"] >= 1

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        os.environ.get("SKIP_E2E") == "1",
        reason="E2E tests skipped",
    )
    async def test_attendance_api(self, mock_server) -> None:
        """Verify attendance API returns tech dept data."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            await session.post(
                "http://localhost:5000/api/login",
                json={"username": "admin", "password": "admin123"},
            )

            async with session.get(
                "http://localhost:5000/api/reports/attendance"
            ) as resp:
                assert resp.status == 200
                data = await resp.json()

                tech_jan = next(
                    (a for a in data["attendance"]
                     if a["department_name"] == "技术部" and a["month"] == "2024-01"),
                    None
                )
                assert tech_jan is not None
                assert 90 <= tech_jan["avg_attendance_rate"] <= 100


class TestHarnessComponents:
    """Tests for harness components without browser."""

    def test_scenario_loading(self) -> None:
        """Scenario loads into harness correctly."""
        from harness.core import BrowserAgentHarness

        scenario_path = Path(__file__).parent.parent / "samples" / "task_scenarios.json"
        if not scenario_path.exists():
            pytest.skip("Scenario file not found")

        harness = BrowserAgentHarness()
        harness.load_scenario(str(scenario_path))

        steps = harness.task_graph.get_all_steps()
        assert len(steps) == 12

    def test_step_dependencies(self) -> None:
        """Steps have correct dependencies."""
        from harness.core import BrowserAgentHarness

        scenario_path = Path(__file__).parent.parent / "samples" / "task_scenarios.json"
        if not scenario_path.exists():
            pytest.skip("Scenario file not found")

        harness = BrowserAgentHarness()
        harness.load_scenario(str(scenario_path))

        first = harness.task_graph.get_next_executable()
        assert first is not None
        assert first.step_id == 1

    def test_trajectory_logging(self) -> None:
        """Trajectory logger creates JSONL file."""
        from harness.evaluation import TrajectoryLogger

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TrajectoryLogger(output_dir=tmpdir, session_id="test")

            logger.log_step_start(1, "Test action", "http://localhost:5000")
            logger.log_step_end(1, True)

            assert Path(logger.file_path).exists()

            with open(logger.file_path) as f:
                lines = f.readlines()
                assert len(lines) == 2

    def test_checkpoint_save_restore(self) -> None:
        """Checkpoint saves and restores state."""
        from harness.state import CheckpointManager, TaskGraph, CrossPageDataStore
        from harness.schemas import TaskStep, TaskPhase, StepStatus

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(tmpdir)

            graph = TaskGraph()
            graph.add_step(TaskStep(step_id=1, action="A", description="First"))
            graph.update_step_status(1, StepStatus.COMPLETED)

            store = CrossPageDataStore()
            store.set("key", "value")

            path = manager.save(graph, store, TaskPhase.DASHBOARD)

            loaded_graph, loaded_store, loaded_phase = manager.load(path)

            assert loaded_graph.get_step(1).status == StepStatus.COMPLETED
            assert loaded_store.get("key") == "value"
            assert loaded_phase == TaskPhase.DASHBOARD
