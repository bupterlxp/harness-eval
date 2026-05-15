import pytest
import time
from unittest.mock import patch
from harness.execution import ExecutionEngine
from harness.schemas import TaskStatus


def test_retry_mechanism():
    """Test timeout retry mechanism"""
    config = {
        "base_url": "http://localhost:5000",
        "max_retries": 2,
        "default_timeout": 100
    }

    engine = ExecutionEngine(config)
    engine.start_task("test_retry")

    # Create a step that fails twice then succeeds
    fail_count = 0

    def flaky_step():
        nonlocal fail_count
        fail_count += 1
        if fail_count < 3:
            return TaskStatus.FAILED
        return TaskStatus.COMPLETED

    result = engine.execute_step(flaky_step, 1)
    assert result.status == TaskStatus.COMPLETED
    assert fail_count == 3  # 1 initial + 2 retries


def test_timeout_handling():
    """Test timeout error handling"""
    config = {
        "base_url": "http://localhost:5000",
        "max_retries": 2,
        "default_timeout": 100
    }

    engine = ExecutionEngine(config)
    engine.start_task("test_timeout")

    # Mock wait_for_element to always timeout
    with patch.object(engine.tools, 'wait_for_element', return_value=False):
        def failing_step():
            # This will fail because element never appears
            engine.tools.wait_for_element("#non-existent-element")
            return TaskStatus.COMPLETED

        result = engine.execute_step(failing_step, 1)
        assert result.status == TaskStatus.FAILED
        assert result.retry_count == 2  # Max retries reached