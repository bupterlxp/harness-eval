"""Tests for TODO app."""
import pytest
from app import TodoApp


@pytest.fixture
def app():
    return TodoApp()


def test_add_todo(app):
    todo = app.add("Buy groceries")
    assert todo.title == "Buy groceries"
    assert todo.id == 1
    assert todo.completed is False


def test_add_multiple(app):
    t1 = app.add("Task 1")
    t2 = app.add("Task 2")
    assert t1.id == 1
    assert t2.id == 2
    assert app.count()["total"] == 2


def test_get_by_id(app):
    app.add("Task A")
    app.add("Task B")
    result = app.get(2)
    assert result is not None
    assert result.title == "Task B"


def test_get_nonexistent(app):
    result = app.get(999)
    assert result is None


def test_complete_todo(app):
    app.add("Task to complete")
    assert app.complete(1) is True
    todo = app.get(1)
    assert todo is not None
    assert todo.completed is True


def test_delete_todo(app):
    app.add("Task to delete")
    assert app.delete(1) is True
    assert app.get(1) is None
    assert app.count()["total"] == 0


def test_list_incomplete_only(app):
    app.add("Done task")
    app.add("Pending task")
    app.complete(1)
    pending = app.list_todos(include_completed=False)
    assert len(pending) == 1
    assert pending[0].title == "Pending task"


def test_count(app):
    app.add("A")
    app.add("B")
    app.add("C")
    app.complete(1)
    counts = app.count()
    assert counts["total"] == 3
    assert counts["completed"] == 1
    assert counts["pending"] == 2


def test_priority(app):
    app.add("Low", priority=1)
    app.add("High", priority=3)
    app.add("High 2", priority=3)
    high = app.get_by_priority(3)
    assert len(high) == 2
