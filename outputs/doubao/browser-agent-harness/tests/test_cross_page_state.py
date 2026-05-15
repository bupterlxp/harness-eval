import pytest
from unittest.mock import patch
from harness.context import ContextManager
from harness.schemas import PageState


def test_cross_page_state_persistence():
    """Test that state persists across page navigation"""
    config = {
        "screenshot_dir": "screenshots"
    }

    context = ContextManager(config)
    context.initialize_task("test_state")

    # Simulate data extraction on first page
    data1 = {"total_employees": 50, "pending_leaves": 8}
    context.save_extracted_data(data1)

    # Navigate to second page
    page2 = PageState(
        url="http://localhost:5000/employees",
        title="Employee List",
        loaded=True
    )
    context.update_page_state(page2)

    # Extract data on second page
    data2 = {"first_employee_name": "张三", "department": "技术部"}
    context.save_extracted_data(data2)

    # Verify all data is preserved
    all_data = context.get_extracted_data()
    assert all_data["total_employees"] == 50
    assert all_data["pending_leaves"] == 8
    assert all_data["first_employee_name"] == "张三"
    assert all_data["department"] == "技术部"

    # Verify navigation history
    assert len(context.navigation_history) == 1
    assert context.navigation_history[0] == "http://localhost:5000/employees"


def test_context_serialization():
    """Test context save/load functionality"""
    import os
    import tempfile

    config = {
        "screenshot_dir": "screenshots"
    }

    context = ContextManager(config)
    context.initialize_task("test_serialize")

    # Add some test data
    context.save_extracted_data({"key1": "value1", "key2": 42})
    context.add_screenshot("screenshot1.png")
    context.add_screenshot("screenshot2.png")
    context.mark_step_completed(1, type('obj', (), {'data': {'test': 'data'}})())

    # Save to temp file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        temp_path = f.name

    saved_path = context.save_context(temp_path)
    assert saved_path == temp_path
    assert os.path.exists(saved_path)

    # Load back
    new_context = ContextManager(config)
    new_context.load_context(temp_path)

    # Verify data
    assert new_context.task_context.task_id == "test_serialize"
    assert new_context.get_extracted_data()["key1"] == "value1"
    assert new_context.get_extracted_data()["key2"] == 42
    assert len(new_context.task_context.screenshots) == 2
    assert len(new_context.task_context.completed_steps) == 1

    # Cleanup
    os.unlink(temp_path)