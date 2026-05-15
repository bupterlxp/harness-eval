#!/usr/bin/env python3
"""
Simple wrapper script to demonstrate the bug fixes.
"""

import os
import sys
import subprocess


def main():
    print("=== Applying fixes to buggy_server.py ===\n")

    # Fix BUG 1: Non-ASCII character handling
    print("Fixing BUG 1: Non-ASCII character handling in JSON responses")
    with open("samples/buggy_server.py", "r") as f:
        content = f.read()
    content = content.replace('# BUG 1: does not encode to bytes properly for non-ASCII characters\n        self.wfile.write(json.dumps(data))', '        self.wfile.write(json.dumps(data).encode("utf-8"))')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 2: AND instead of OR in WHERE clause
    print("Fixing BUG 2: AND instead of OR in list filtering")
    content = content.replace('sql += " WHERE " + " OR ".join(conditions)  # BUG 2: should be AND, not OR', 'sql += " WHERE " + " AND ".join(conditions)  # BUG 2: should be AND, not OR')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 3: Add ORDER BY clause
    print("Fixing BUG 3: Add ORDER BY created_at DESC")
    content = content.replace('# BUG 3: missing ORDER BY, results are not deterministic\n        rows = conn.execute(sql, params).fetchall()', '        # BUG 3: missing ORDER BY, results are not deterministic\n        sql += " ORDER BY created_at DESC"\n        rows = conn.execute(sql, params).fetchall()')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 4: SQL injection protection
    print("Fixing BUG 4: SQL injection vulnerability")
    content = content.replace('row = conn.execute(f"SELECT * FROM tasks WHERE id = {task_id}").fetchone()', 'row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 5: Proper status validation
    print("Fixing BUG 5: Proper status validation")
    content = content.replace('        if status not in valid_statuses:\n            status = "todo"  # silently corrects instead of returning error', '        if status not in valid_statuses:\n            self._send_json({"error": "Invalid status"}, 400)\n            return')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 6: Don't close connection before query
    print("Fixing BUG 6: Don't close connection before query")
    content = content.replace('        conn.close()\n        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()', '        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()\n        conn.close()')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 7: Update updated_at timestamp
    print("Fixing BUG 7: Update updated_at timestamp")
    content = content.replace('        # BUG 7: does not update the updated_at timestamp', '        updates["updated_at"] = datetime.now().isoformat()\n        # BUG 7: update the updated_at timestamp')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    # Fix BUG 8: Return 404 for non-existent delete
    print("Fixing BUG 8: Return 404 for non-existent task deletion")
    content = content.replace('            self._send_json({"message": "Task deleted"})', '            self._send_json({"error": "Task not found"}, 404)')
    with open("samples/buggy_server.py", "w") as f:
        f.write(content)

    print("\n✅ All 8 bugs fixed!")
    print("\nRunning tests to verify...")

    # Run tests
    result = subprocess.run(["python", "-m", "pytest", "samples/test_server.py", "-v"],
                          capture_output=True, text=True)

    print(f"\nTest results:\n{result.stdout}")

    if result.stderr:
        print(f"\nErrors/Warnings:\n{result.stderr}")

    if result.returncode == 0:
        print("\n✅ All tests passed!")
    else:
        print(f"\n❌ Tests failed with exit code {result.returncode}")

    # Show git diff
    print("\n=== Git diff of changes ===")
    subprocess.run(["git", "diff", "samples/buggy_server.py"])


if __name__ == "__main__":
    main()