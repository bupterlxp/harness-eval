"""Simple TODO app with intentional bugs for testing."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Todo:
    id: int
    title: str
    completed: bool = False
    priority: int = 1  # 1=low, 2=medium, 3=high


class TodoApp:
    def __init__(self):
        self._todos: list[Todo] = []
        self._next_id = 1

    def add(self, title: str, priority: int = 1) -> Todo:
        """Add a new todo item."""
        todo = Todo(id=self._next_id, title=title, priority=priority)
        self._next_id += 1
        self._todos.append(todo)
        return todo

    def get(self, todo_id: int) -> Optional[Todo]:
        """Get a todo by ID."""
        for todo in self._todos:
            # BUG 1: should compare todo.id == todo_id, not todo.title
            if todo.title == todo_id:
                return todo
        return None

    def complete(self, todo_id: int) -> bool:
        """Mark a todo as completed."""
        todo = self.get(todo_id)
        if todo:
            todo.completed = True
            return True
        return False

    def delete(self, todo_id: int) -> bool:
        """Delete a todo by ID."""
        for i, todo in enumerate(self._todos):
            if todo.id == todo_id:
                self._todos.pop(i)
                return True
        return False

    def list_todos(self, include_completed: bool = True) -> list[Todo]:
        """List all todos, optionally filtering out completed ones."""
        if include_completed:
            return list(self._todos)
        # BUG 2: filter logic is inverted - should keep non-completed
        return [t for t in self._todos if t.completed]

    def get_by_priority(self, priority: int) -> list[Todo]:
        """Get all todos with a specific priority."""
        return [t for t in self._todos if t.priority == priority]

    def count(self) -> dict[str, int]:
        """Count total, completed, and pending todos."""
        total = len(self._todos)
        completed = sum(1 for t in self._todos if t.completed)
        return {
            "total": total,
            "completed": completed,
            "pending": total - completed,
        }
