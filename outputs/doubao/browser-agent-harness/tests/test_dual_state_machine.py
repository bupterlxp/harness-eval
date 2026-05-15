import pytest
from harness.execution import ExecutionEngine
from harness.schemas import TaskStatus


def test_dual_state_machine():
    """Test the double state machine switching between task flow and page operations"""
    config = {
        "base_url": "http://localhost:5000",
        "max_retries": 1
    }

    engine = ExecutionEngine(config)

    # Test that we can initialize task flow
    engine.start_task("test_task")
    assert engine.task_running is True
    assert engine.current_step == 0

    # Test step execution
    def test_step():
        return TaskStatus.COMPLETED

    result = engine.execute_step(test_step, 1)
    assert result.status == TaskStatus.COMPLETED
    assert result.step_id == 1

    # Test task sequence
    test_steps = [
        {
            "id": 1,
            "action": "Test Step 1",
            "description": "First test step"
        },
        {
            "id": 2,
            "action": "Test Step 2",
            "description": "Second test step"
        }
    ]

    # We'll mock the navigation to avoid real browser calls
    from unittest.mock import patch
    with patch.object(engine.tools, 'navigate'):
        with patch.object(engine.tools, 'wait_for_load'):
            with patch.object(engine.tools, 'screenshot'):
                report = engine.run_task_sequence(test_steps)

                assert report["summary"]["total_steps"] == 2
                assert report["summary"]["completed_steps"] == 2
                assert report["summary"]["success_rate"] == 100.0