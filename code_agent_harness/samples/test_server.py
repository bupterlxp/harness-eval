"""
Test suite for the task management server.
All tests should pass after bugs are fixed.
"""

import json
import os
import sqlite3
import threading
import time
import unittest
from http.client import HTTPConnection
from datetime import datetime

# Set test DB path before importing server
os.environ["DB_PATH"] = "test_tasks.db"

from buggy_server import TaskHandler, init_db, get_db
from http.server import HTTPServer


class TestTaskServer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Start test server in a background thread."""
        if os.path.exists("test_tasks.db"):
            os.remove("test_tasks.db")
        init_db()
        cls.server = HTTPServer(("127.0.0.1", 0), TaskHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        if os.path.exists("test_tasks.db"):
            os.remove("test_tasks.db")

    def setUp(self):
        """Clear database before each test."""
        conn = get_db()
        conn.execute("DELETE FROM tasks")
        conn.commit()
        conn.close()

    def _request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port)
        headers = {"Content-Type": "application/json"}
        data = json.dumps(body).encode() if body else None
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        return resp.status, json.loads(raw)

    # --- Test Create ---

    def test_create_task_basic(self):
        status, data = self._request("POST", "/tasks", {
            "title": "Fix login bug",
            "description": "Users cannot login with email"
        })
        self.assertEqual(status, 201)
        self.assertEqual(data["title"], "Fix login bug")
        self.assertEqual(data["status"], "todo")
        self.assertIn("id", data)

    def test_create_task_with_unicode(self):
        """BUG 1: non-ASCII characters should work."""
        status, data = self._request("POST", "/tasks", {
            "title": "修复登录问题",
            "description": "用户无法使用邮箱登录"
        })
        self.assertEqual(status, 201)
        self.assertEqual(data["title"], "修复登录问题")

    def test_create_task_missing_title(self):
        status, data = self._request("POST", "/tasks", {
            "description": "No title provided"
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_create_task_invalid_status_returns_error(self):
        """BUG 5: invalid status should return 400, not silently correct."""
        status, data = self._request("POST", "/tasks", {
            "title": "Test task",
            "status": "invalid_status"
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- Test Read ---

    def test_get_task(self):
        _, created = self._request("POST", "/tasks", {"title": "Task 1"})
        status, data = self._request("GET", f"/tasks/{created['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "Task 1")

    def test_get_task_not_found(self):
        status, data = self._request("GET", "/tasks/99999")
        self.assertEqual(status, 404)

    def test_get_task_sql_injection(self):
        """BUG 4: SQL injection should be prevented."""
        status, data = self._request("GET", "/tasks/1 OR 1=1")
        self.assertIn(status, [400, 404])

    # --- Test List with Filters ---

    def test_list_tasks_filter_and_logic(self):
        """BUG 2: multiple filters should use AND, not OR."""
        self._request("POST", "/tasks", {"title": "T1", "status": "todo", "assignee": "alice"})
        self._request("POST", "/tasks", {"title": "T2", "status": "done", "assignee": "alice"})
        self._request("POST", "/tasks", {"title": "T3", "status": "todo", "assignee": "bob"})

        status, data = self._request("GET", "/tasks?status=todo&assignee=alice")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["tasks"][0]["title"], "T1")

    def test_list_tasks_ordered(self):
        """BUG 3: results should be ordered by created_at DESC."""
        self._request("POST", "/tasks", {"title": "First"})
        time.sleep(0.01)
        self._request("POST", "/tasks", {"title": "Second"})

        status, data = self._request("GET", "/tasks")
        self.assertEqual(data["tasks"][0]["title"], "Second")

    # --- Test Update ---

    def test_update_task(self):
        _, created = self._request("POST", "/tasks", {"title": "Original"})
        status, data = self._request("PUT", f"/tasks/{created['id']}", {
            "title": "Updated"
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "Updated")

    def test_update_task_updates_timestamp(self):
        """BUG 7: updated_at should change on update."""
        _, created = self._request("POST", "/tasks", {"title": "Original"})
        original_updated = created["updated_at"]
        time.sleep(0.01)

        _, updated = self._request("PUT", f"/tasks/{created['id']}", {
            "title": "Updated"
        })
        self.assertNotEqual(updated["updated_at"], original_updated)

    def test_update_nonexistent_task(self):
        status, _ = self._request("PUT", "/tasks/99999", {"title": "X"})
        self.assertEqual(status, 404)

    # --- Test Delete ---

    def test_delete_task(self):
        _, created = self._request("POST", "/tasks", {"title": "To Delete"})
        status, _ = self._request("DELETE", f"/tasks/{created['id']}")
        self.assertEqual(status, 200)

        status, _ = self._request("GET", f"/tasks/{created['id']}")
        self.assertEqual(status, 404)

    def test_delete_nonexistent_returns_404(self):
        """BUG 8: deleting non-existent task should return 404."""
        status, _ = self._request("DELETE", "/tasks/99999")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
