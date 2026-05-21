"""Tests for the State Store module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from harness.state import StateStore, TaskState, StepState, StepStatus


class TestStepState:
    """Tests for StepState dataclass."""

    def test_step_state_creation(self):
        step = StepState(
            step_id=1,
            description="Click login button",
            status=StepStatus.PENDING,
        )
        assert step.step_id == 1
        assert step.description == "Click login button"
        assert step.status == StepStatus.PENDING
        assert step.retry_count == 0

    def test_step_state_to_dict(self):
        step = StepState(
            step_id=1,
            description="Test step",
            status=StepStatus.COMPLETED,
            action_type="click",
            target_element="#button",
        )
        data = step.to_dict()
        assert data["step_id"] == 1
        assert data["status"] == "completed"
        assert data["action_type"] == "click"

    def test_step_state_from_dict(self):
        data = {
            "step_id": 2,
            "description": "Type text",
            "status": "in_progress",
            "action_type": "type_text",
            "action_params": {"text": "hello"},
            "target_element": "#input",
            "result": None,
            "error": None,
            "recovery_action": None,
            "retry_count": 1,
            "screenshot_path": None,
            "url_before": "https://example.com",
            "url_after": None,
            "timestamp_start": None,
            "timestamp_end": None,
        }
        step = StepState.from_dict(data)
        assert step.step_id == 2
        assert step.status == StepStatus.IN_PROGRESS
        assert step.retry_count == 1


class TestTaskState:
    """Tests for TaskState dataclass."""

    def test_task_state_creation(self):
        task = TaskState(
            task_id="test123",
            target_url="https://example.com",
            task_description="Test task",
        )
        assert task.task_id == "test123"
        assert task.status == "in_progress"
        assert task.current_step == 0
        assert len(task.steps) == 0

    def test_task_state_serialization(self):
        task = TaskState(
            task_id="test123",
            target_url="https://example.com",
            task_description="Test task",
        )
        task.steps.append(StepState(step_id=0, description="First step"))

        data = task.to_dict()
        assert data["task_id"] == "test123"
        assert len(data["steps"]) == 1

        restored = TaskState.from_dict(data)
        assert restored.task_id == "test123"
        assert len(restored.steps) == 1
        assert restored.steps[0].step_id == 0


class TestStateStore:
    """Tests for StateStore."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_initialize_task(self, temp_dir):
        store = StateStore(temp_dir)
        task = store.initialize_task(
            task_id="task1",
            target_url="https://example.com",
            task_description="Test task",
            max_steps=10,
        )

        assert task.task_id == "task1"
        assert task.max_steps == 10
        assert Path(temp_dir, "task_state.json").exists()

    def test_load_or_create_new(self, temp_dir):
        store = StateStore(temp_dir)
        task, resumed = store.load_or_create(
            task_id="task1",
            target_url="https://example.com",
            task_description="Test task",
        )

        assert not resumed
        assert task.task_id == "task1"

    def test_load_or_create_resume(self, temp_dir):
        store1 = StateStore(temp_dir)
        store1.initialize_task(
            task_id="task1",
            target_url="https://example.com",
            task_description="Test task",
        )
        store1.add_step(StepState(step_id=0, description="Step 0", status=StepStatus.COMPLETED))
        store1.add_step(StepState(step_id=1, description="Step 1", status=StepStatus.COMPLETED))

        store2 = StateStore(temp_dir)
        task, resumed = store2.load_or_create(
            task_id="task1",
            target_url="https://example.com",
            task_description="Test task",
        )

        assert resumed
        assert len(task.steps) == 2

    def test_add_step(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")

        step = StepState(step_id=0, description="First step")
        store.add_step(step)

        assert len(store.task_state.steps) == 1
        assert store.task_state.current_step == 0

    def test_mark_step_completed(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")
        store.add_step(StepState(step_id=0, description="Step"))

        store.mark_step_completed(0, result={"data": "value"})

        assert store.task_state.steps[0].status == StepStatus.COMPLETED
        assert store.task_state.steps[0].result == {"data": "value"}

    def test_mark_step_failed(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")
        store.add_step(StepState(step_id=0, description="Step"))

        store.mark_step_failed(0, error="Element not found", recovery="retried")

        assert store.task_state.steps[0].status == StepStatus.FAILED
        assert len(store.task_state.errors) == 1
        assert store.task_state.errors[0]["error"] == "Element not found"

    def test_get_last_successful_step(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")

        store.add_step(StepState(step_id=0, description="Step 0", status=StepStatus.COMPLETED))
        store.add_step(StepState(step_id=1, description="Step 1", status=StepStatus.COMPLETED))
        store.add_step(StepState(step_id=2, description="Step 2", status=StepStatus.FAILED))

        assert store.get_last_successful_step() == 1

    def test_get_resume_point(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")

        store.add_step(StepState(step_id=0, description="Step 0", status=StepStatus.COMPLETED))
        store.add_step(StepState(step_id=1, description="Step 1", status=StepStatus.FAILED))

        assert store.get_resume_point() == 1

    def test_increment_retry(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")
        store.add_step(StepState(step_id=0, description="Step"))

        count = store.increment_retry(0)
        assert count == 1

        count = store.increment_retry(0)
        assert count == 2

    def test_add_screenshot(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")

        store.add_screenshot("/path/to/screenshot.png")
        assert "/path/to/screenshot.png" in store.task_state.screenshots

    def test_add_download(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")

        store.add_download("/path/to/file.pdf")
        assert "/path/to/file.pdf" in store.task_state.downloads

    def test_update_extracted_data(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")

        store.update_extracted_data({"key1": "value1"})
        store.update_extracted_data({"key2": "value2"})

        assert store.task_state.extracted_data == {"key1": "value1", "key2": "value2"}

    def test_get_result(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")
        store.set_task_status("success")
        store.update_extracted_data({"title": "Test Page"})
        store.add_screenshot("/path/screenshot.png")

        result = store.get_result()

        assert result["status"] == "success"
        assert result["extracted_data"] == {"title": "Test Page"}
        assert "/path/screenshot.png" in result["screenshots"]
        assert "trajectory" in result

    def test_save_result(self, temp_dir):
        store = StateStore(temp_dir)
        store.initialize_task("task1", "https://example.com", "Test")
        store.set_task_status("success")

        result_path = store.save_result()

        assert Path(result_path).exists()
        with open(result_path) as f:
            data = json.load(f)
        assert data["status"] == "success"
