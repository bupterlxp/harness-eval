"""Tests for the Evaluation/Trajectory Recorder module."""

import json
import tempfile
from pathlib import Path

import pytest

from harness.evaluation import TrajectoryRecorder, TrajectoryEntry


class TestTrajectoryEntry:
    """Tests for TrajectoryEntry."""

    def test_entry_creation(self):
        entry = TrajectoryEntry(
            step_id=1,
            timestamp="2024-01-01T00:00:00",
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#button"},
        )
        assert entry.step_id == 1
        assert entry.action_type == "click"
        assert entry.success is True

    def test_entry_with_error(self):
        entry = TrajectoryEntry(
            step_id=1,
            timestamp="2024-01-01T00:00:00",
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#button"},
            success=False,
            error="Element not found",
        )
        assert entry.success is False
        assert entry.error == "Element not found"

    def test_to_dict(self):
        entry = TrajectoryEntry(
            step_id=1,
            timestamp="2024-01-01T00:00:00",
            url="https://example.com",
            action_type="navigate",
            action_params={"url": "https://example.com"},
            result={"status": 200},
        )
        data = entry.to_dict()

        assert data["step_id"] == 1
        assert data["action_type"] == "navigate"
        assert data["result"]["status"] == 200

    def test_to_jsonl(self):
        entry = TrajectoryEntry(
            step_id=1,
            timestamp="2024-01-01T00:00:00",
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#btn"},
        )
        jsonl = entry.to_jsonl()

        parsed = json.loads(jsonl)
        assert parsed["step_id"] == 1
        assert parsed["action_type"] == "click"


class TestTrajectoryRecorder:
    """Tests for TrajectoryRecorder."""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_init(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        assert recorder.output_dir == Path(temp_dir)
        assert recorder.trajectory_file == Path(temp_dir) / "trajectory.jsonl"
        assert len(recorder._entries) == 0

    def test_record(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#button"},
        )

        assert entry.step_id == 1
        assert len(recorder._entries) == 1
        assert recorder.trajectory_file.exists()

    def test_record_multiple(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        recorder.record(
            url="https://example.com",
            action_type="navigate",
            action_params={"url": "https://example.com"},
        )
        recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#login"},
        )
        recorder.record(
            url="https://example.com/dashboard",
            action_type="screenshot",
            action_params={},
        )

        assert len(recorder._entries) == 3
        assert recorder._entries[0].step_id == 1
        assert recorder._entries[2].step_id == 3

    def test_record_navigation(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_navigation(
            url="https://example.com",
            target_url="https://example.com/page",
        )

        assert entry.action_type == "navigate"
        assert entry.action_params["target_url"] == "https://example.com/page"

    def test_record_click(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_click(
            url="https://example.com",
            selector="#button",
            element_description="Submit button",
        )

        assert entry.action_type == "click"
        assert entry.target_element == "Submit button"

    def test_record_type(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_type(
            url="https://example.com",
            selector="#email",
            text="user@example.com",
            element_description="Email input",
        )

        assert entry.action_type == "type_text"
        assert entry.action_params["text"] == "user@example.com"

    def test_record_type_long_text(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        long_text = "A" * 100
        entry = recorder.record_type(
            url="https://example.com",
            selector="#input",
            text=long_text,
        )

        assert entry.action_params["text"].endswith("...")
        assert len(entry.action_params["text"]) < len(long_text)

    def test_record_extraction(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_extraction(
            url="https://example.com",
            extraction_type="text",
            selector="#content",
            data={"text": "Page content"},
        )

        assert entry.action_type == "extract_text"
        assert entry.result["text"] == "Page content"

    def test_record_screenshot(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_screenshot(
            url="https://example.com",
            screenshot_path="/path/to/screenshot.png",
            reason="checkpoint",
        )

        assert entry.action_type == "screenshot"
        assert entry.screenshot_path == "/path/to/screenshot.png"

    def test_record_error(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_error(
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#button"},
            error="Element not found",
            recovery_action="retried",
            screenshot_path="/path/to/error.png",
        )

        assert entry.success is False
        assert entry.error == "Element not found"
        assert entry.result["recovery"] == "retried"

    def test_record_llm_decision(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_llm_decision(
            url="https://example.com",
            reasoning="Need to click login button to proceed",
            decided_action="click",
            action_params={"selector": "#login"},
            page_context_summary="Login page with form",
        )

        assert entry.action_type == "llm_decision"
        assert entry.llm_reasoning == "Need to click login button to proceed"

    def test_record_task_event(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        entry = recorder.record_task_event(
            url="https://example.com",
            event_type="start",
            details={"task_id": "abc123"},
        )

        assert entry.action_type == "task_start"
        assert entry.action_params["task_id"] == "abc123"

    def test_get_entries(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={},
        )

        entries = recorder.get_entries()

        assert len(entries) == 1
        assert entries is not recorder._entries

    def test_get_trajectory_path(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        path = recorder.get_trajectory_path()

        assert path == str(Path(temp_dir) / "trajectory.jsonl")

    def test_get_summary_empty(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        summary = recorder.get_summary()

        assert summary["total_steps"] == 0
        assert summary["successful_steps"] == 0

    def test_get_summary(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        recorder.record(
            url="https://example.com",
            action_type="navigate",
            action_params={},
            success=True,
        )
        recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={},
            success=True,
        )
        recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={},
            success=False,
            error="Not found",
        )

        summary = recorder.get_summary()

        assert summary["total_steps"] == 3
        assert summary["successful_steps"] == 2
        assert summary["failed_steps"] == 1
        assert summary["action_types"]["click"] == 2
        assert summary["action_types"]["navigate"] == 1

    def test_load_from_file(self, temp_dir):
        recorder1 = TrajectoryRecorder(temp_dir)
        recorder1.record(
            url="https://example.com",
            action_type="navigate",
            action_params={"url": "https://example.com"},
        )
        recorder1.record(
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#button"},
        )

        recorder2 = TrajectoryRecorder(temp_dir)
        entries = recorder2.load_from_file()

        assert len(entries) == 2
        assert entries[0].action_type == "navigate"
        assert entries[1].action_type == "click"

    def test_load_from_empty_file(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)
        entries = recorder.load_from_file()

        assert len(entries) == 0

    def test_clear(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)
        recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={},
        )

        recorder.clear()

        assert len(recorder._entries) == 0
        assert recorder._step_counter == 0
        assert not recorder.trajectory_file.exists()

    def test_file_format(self, temp_dir):
        recorder = TrajectoryRecorder(temp_dir)

        recorder.record(
            url="https://example.com",
            action_type="navigate",
            action_params={"url": "https://example.com"},
        )
        recorder.record(
            url="https://example.com",
            action_type="click",
            action_params={"selector": "#btn"},
        )

        with open(recorder.trajectory_file) as f:
            lines = f.readlines()

        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "step_id" in data
            assert "action_type" in data
            assert "url" in data
