"""
Test cases for the code intelligence harness
"""

import pytest
import tempfile
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import (
    ToolRegistry,
    ContextManager,
    StateStore,
    LifecycleHooks,
    Evaluator,
    ExecutionLoop
)


def test_tool_registry():
    """Test tool registry functionality"""
    registry = ToolRegistry()

    # Test that tools are registered
    tools = registry.list_tools()
    assert len(tools) > 0, "No tools registered"
    assert "read_file" in tools
    assert "write_file" in tools
    assert "execute_command" in tools


def test_context_manager():
    """Test context manager functionality"""
    context = ContextManager(max_context_size=1000)

    # Test adding items
    item_id = context.add_item("test content", {"type": "test"})
    assert item_id is not None

    # Test context stats
    stats = context.get_stats()
    assert stats["total_items"] == 1

    # Test getting context
    prompt, stats = context.get_context("test prompt")
    assert "test content" in prompt


def test_state_store():
    """Test state store functionality"""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        state = StateStore(working_dir=tmpdir)

        # Test saving and loading state
        state.save_state("test_key", "test_value")
        assert state.load_state("test_key") == "test_value"

        # Test snapshot creation
        snapshot_id = state.create_snapshot("test snapshot")
        assert snapshot_id is not None

        # Test listing snapshots
        snapshots = state.list_snapshots()
        assert len(snapshots) == 1


def test_evaluator():
    """Test evaluator functionality"""
    evaluator = Evaluator()

    # Test logging steps
    evaluator.log_step("TEST_STATE", "test_action", {"test": "details"}, {"result": "test"})
    assert len(evaluator.steps) == 1

    # Test summary
    summary = evaluator.get_execution_summary()
    assert summary["total_steps"] == 1

    # Test JSONL output
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        output_file = evaluator.write_jsonl(tmp_path)
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0
    finally:
        os.unlink(tmp_path)


def test_execution_loop_initialization():
    """Test execution loop initialization"""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)

        # Create all required components
        state_store = StateStore(tmpdir)
        tool_registry = ToolRegistry()
        context_manager = ContextManager()
        lifecycle_hooks = LifecycleHooks()
        evaluator = Evaluator()

        # Create execution loop
        executor = ExecutionLoop(
            state_store,
            tool_registry,
            context_manager,
            lifecycle_hooks,
            evaluator
        )

        assert executor.current_state is not None


def test_command_execution_tool():
    """Test command execution tool"""
    registry = ToolRegistry()

    # Test executing a simple command
    result = registry.execute_tool("execute_command", command="echo 'hello world'")
    assert result["returncode"] == 0
    assert "hello world" in result["stdout"]


def test_file_operations():
    """Test file operation tools"""
    registry = ToolRegistry()

    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
        tmp.write("initial content")
        tmp_path = tmp.name

    try:
        # Test read file
        result = registry.execute_tool("read_file", file_path=tmp_path)
        assert result["content"] == "initial content"

        # Test edit file
        registry.execute_tool(
            "edit_file",
            file_path=tmp_path,
            old_string="initial",
            new_string="modified"
        )

        with open(tmp_path, 'r') as f:
            content = f.read()
            assert "modified content" in content

    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    pytest.main([__file__])