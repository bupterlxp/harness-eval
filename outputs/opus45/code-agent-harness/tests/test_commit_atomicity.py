"""Tests for commit atomicity."""

import pytest
from datetime import datetime

from harness.state import CommitLog, BugTracker
from harness.schemas import CommitRecord, BugReport, BugStatus, BugSeverity, BugCategory
from harness.lifecycle import CommitValidationHook, HookContext


class TestCommitLog:
    """Tests for commit log."""

    def test_add_commit(self):
        log = CommitLog()
        commit = CommitRecord(
            commit_hash="abc123",
            bug_id="BUG_1",
            message="Fix bug 1",
            files_changed=["server.py"],
        )
        log.add_commit(commit)

        assert len(log.get_commits()) == 1
        assert log.get_commits()[0].commit_hash == "abc123"

    def test_get_commit_for_bug(self):
        log = CommitLog()
        log.add_commit(CommitRecord(
            commit_hash="abc123",
            bug_id="BUG_1",
            message="Fix bug 1",
        ))
        log.add_commit(CommitRecord(
            commit_hash="def456",
            bug_id="BUG_2",
            message="Fix bug 2",
        ))

        commit = log.get_commit_for_bug("BUG_1")
        assert commit is not None
        assert commit.commit_hash == "abc123"

    def test_each_bug_has_one_commit(self):
        log = CommitLog()

        for i in range(8):
            log.add_commit(CommitRecord(
                commit_hash=f"hash{i}",
                bug_id=f"BUG_{i+1}",
                message=f"Fix bug {i+1}",
            ))

        assert len(log.get_commits()) == 8

        bug_ids = [c.bug_id for c in log.get_commits()]
        assert len(bug_ids) == len(set(bug_ids))


class TestCommitValidation:
    """Tests for commit validation hook."""

    def test_requires_bug_id(self):
        hook = CommitValidationHook(require_bug_id=True)
        ctx = HookContext(commit_message="Fix something")

        result = hook.execute(ctx)
        assert not result.success
        assert "bug ID" in result.message

    def test_requires_message(self):
        hook = CommitValidationHook(require_message=True)
        ctx = HookContext(bug_id="BUG_1")

        result = hook.execute(ctx)
        assert not result.success
        assert "message" in result.message.lower()

    def test_message_length_validation(self):
        hook = CommitValidationHook(min_message_length=20)
        ctx = HookContext(bug_id="BUG_1", commit_message="Short")

        result = hook.execute(ctx)
        assert not result.success
        assert "20" in result.message

    def test_valid_commit(self):
        hook = CommitValidationHook()
        ctx = HookContext(
            bug_id="BUG_1",
            commit_message="Fix SQL injection vulnerability in get_task",
        )

        result = hook.execute(ctx)
        assert result.success


class TestBugTrackerCommitIntegration:
    """Tests for bug tracker commit integration."""

    def test_bug_fixed_after_commit(self):
        tracker = BugTracker()
        bug = BugReport(
            id="BUG_1",
            title="Test bug",
            description="",
            file_path="test.py",
            line_number=10,
            category=BugCategory.CORRECTNESS,
            severity=BugSeverity.MEDIUM,
        )
        tracker.add_bug(bug)

        assert tracker.get_bug("BUG_1").status == BugStatus.PENDING

        tracker.update_status("BUG_1", BugStatus.FIXING)
        assert tracker.get_bug("BUG_1").status == BugStatus.FIXING

        tracker.update_status("BUG_1", BugStatus.FIXED)
        assert tracker.get_bug("BUG_1").status == BugStatus.FIXED

    def test_all_bugs_tracked_independently(self):
        tracker = BugTracker()

        for i in range(8):
            bug = BugReport(
                id=f"BUG_{i+1}",
                title=f"Bug {i+1}",
                description="",
                file_path="test.py",
                line_number=i * 10,
                category=BugCategory.CORRECTNESS,
                severity=BugSeverity.MEDIUM,
            )
            tracker.add_bug(bug)

        for i in range(4):
            tracker.update_status(f"BUG_{i+1}", BugStatus.FIXED)

        progress = tracker.get_progress()
        assert progress["total"] == 8
        assert progress["fixed"] == 4
        assert progress["pending"] == 4
