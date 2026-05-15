"""
A simple HTTP API server for a task management system.
Contains several bugs that need to be identified and fixed.
"""

import json
import sqlite3
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime


DB_PATH = os.environ.get("DB_PATH", "tasks.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'todo',
            priority INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            due_date TEXT,
            assignee TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


class TaskHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        # BUG 1: does not encode to bytes properly for non-ASCII characters
        self.wfile.write(json.dumps(data))

    def _read_body(self):
        length = self.headers.get("Content-Length")
        if length:
            return json.loads(self.rfile.read(int(length)))
        return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/tasks":
            self._handle_list_tasks(parse_qs(parsed.query))
        elif path.startswith("/tasks/"):
            task_id = path.split("/")[-1]
            self._handle_get_task(task_id)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/tasks":
            body = self._read_body()
            self._handle_create_task(body)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/tasks/"):
            task_id = parsed.path.split("/")[-1]
            body = self._read_body()
            self._handle_update_task(task_id, body)
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/tasks/"):
            task_id = parsed.path.split("/")[-1]
            self._handle_delete_task(task_id)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_list_tasks(self, query_params):
        conn = get_db()
        status_filter = query_params.get("status", [None])[0]
        assignee_filter = query_params.get("assignee", [None])[0]

        sql = "SELECT * FROM tasks"
        params = []
        conditions = []

        if status_filter:
            conditions.append("status = ?")
            params.append(status_filter)
        if assignee_filter:
            conditions.append("assignee = ?")
            params.append(assignee_filter)

        if conditions:
            sql += " WHERE " + " OR ".join(conditions)  # BUG 2: should be AND, not OR

        # BUG 3: missing ORDER BY, results are not deterministic
        rows = conn.execute(sql, params).fetchall()
        tasks = [dict(row) for row in rows]
        conn.close()
        self._send_json({"tasks": tasks, "count": len(tasks)})

    def _handle_get_task(self, task_id):
        conn = get_db()
        # BUG 4: SQL injection vulnerability - task_id not parameterized
        row = conn.execute(f"SELECT * FROM tasks WHERE id = {task_id}").fetchone()
        conn.close()
        if row:
            self._send_json(dict(row))
        else:
            self._send_json({"error": "Task not found"}, 404)

    def _handle_create_task(self, body):
        title = body.get("title")
        if not title:
            self._send_json({"error": "Title is required"}, 400)
            return

        description = body.get("description", "")
        status = body.get("status", "todo")
        priority = body.get("priority", 0)
        due_date = body.get("due_date")
        assignee = body.get("assignee", "")

        # BUG 5: status validation is wrong - allows invalid statuses
        valid_statuses = ["todo", "in_progress", "done"]
        if status not in valid_statuses:
            status = "todo"  # silently corrects instead of returning error

        now = datetime.now().isoformat()

        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO tasks (title, description, status, priority, created_at, updated_at, due_date, assignee)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, description, status, priority, now, now, due_date, assignee)
        )
        task_id = cursor.lastrowid
        conn.commit()

        # BUG 6: fetches task AFTER closing connection
        conn.close()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self._send_json(dict(row), 201)

    def _handle_update_task(self, task_id, body):
        conn = get_db()
        existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            conn.close()
            self._send_json({"error": "Task not found"}, 404)
            return

        updates = {}
        for field in ["title", "description", "status", "priority", "due_date", "assignee"]:
            if field in body:
                updates[field] = body[field]

        if not updates:
            conn.close()
            self._send_json({"error": "No fields to update"}, 400)
            return

        # BUG 7: does not update the updated_at timestamp
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        self._send_json(dict(row))

    def _handle_delete_task(self, task_id):
        conn = get_db()
        existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not existing:
            conn.close()
            # BUG 8: returns 200 instead of 404 for non-existent task
            self._send_json({"message": "Task deleted"})
            return

        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        self._send_json({"message": "Task deleted"})


def main():
    init_db()
    server = HTTPServer(("0.0.0.0", 8080), TaskHandler)
    print("Server running on http://0.0.0.0:8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
