"""
state.py - S: State Store with SQLite backend

Implements commit/recover/snapshot atomic operations with crash recovery support.
"""

from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.schemas import (
    SessionState, ExecutionState, TaskSpec, PlotOutline,
    SceneSpec, SceneDraft, ImageryEntry, ConsistencyReport
)


class StateStoreError(Exception):
    """Base exception for state store errors"""
    pass


class SnapshotNotFoundError(StateStoreError):
    """Raised when requested snapshot doesn't exist"""
    pass


class SessionNotFoundError(StateStoreError):
    """Raised when session doesn't exist"""
    pass


class StateStore:
    """
    S component: Persistent state storage with SQLite backend.

    Provides three atomic operations:
    - commit: Save current session state
    - recover: Load session state from storage
    - snapshot: Create a named checkpoint for crash recovery
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.home() / ".harness" / "state.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    metadata_json TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_session
                ON snapshots(session_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_snapshots_name
                ON snapshots(session_id, name);
            """)

    def _serialize_state(self, state: SessionState) -> str:
        """Serialize session state to JSON"""
        return state.model_dump_json()

    def _deserialize_state(self, json_str: str) -> SessionState:
        """Deserialize JSON to session state"""
        return SessionState.model_validate_json(json_str)

    def create_session(self, session_id: str | None = None) -> SessionState:
        """Create a new session"""
        if session_id is None:
            session_id = str(uuid.uuid4())

        now = datetime.now()
        state = SessionState(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            current_state=ExecutionState.INIT
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO sessions (session_id, created_at, updated_at, state_json)
                   VALUES (?, ?, ?, ?)""",
                (session_id, now.isoformat(), now.isoformat(), self._serialize_state(state))
            )

        return state

    def commit(self, state: SessionState) -> None:
        """
        Commit current session state to storage.
        Atomic operation - either fully succeeds or fails.
        """
        state.updated_at = datetime.now()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                (state.session_id,)
            )
            exists = cursor.fetchone() is not None

            if exists:
                conn.execute(
                    """UPDATE sessions
                       SET updated_at = ?, state_json = ?
                       WHERE session_id = ?""",
                    (state.updated_at.isoformat(), self._serialize_state(state), state.session_id)
                )
            else:
                conn.execute(
                    """INSERT INTO sessions (session_id, created_at, updated_at, state_json)
                       VALUES (?, ?, ?, ?)""",
                    (state.session_id, state.created_at.isoformat(),
                     state.updated_at.isoformat(), self._serialize_state(state))
                )

    def recover(self, session_id: str) -> SessionState:
        """
        Recover session state from storage.
        Returns the most recent committed state.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT state_json FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()

            if row is None:
                raise SessionNotFoundError(f"Session not found: {session_id}")

            return self._deserialize_state(row[0])

    def snapshot(
        self,
        state: SessionState,
        name: str,
        metadata: dict[str, Any] | None = None
    ) -> str:
        """
        Create a named snapshot of the current state.
        Returns the snapshot ID.
        """
        snapshot_id = str(uuid.uuid4())
        now = datetime.now()

        self.commit(state)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO snapshots
                   (snapshot_id, session_id, name, created_at, state_json, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (snapshot_id, state.session_id, name, now.isoformat(),
                 self._serialize_state(state),
                 json.dumps(metadata) if metadata else None)
            )

        return snapshot_id

    def recover_snapshot(self, session_id: str, name: str) -> SessionState:
        """
        Recover from a named snapshot.
        Returns the state at the time of the snapshot.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT state_json FROM snapshots
                   WHERE session_id = ? AND name = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, name)
            )
            row = cursor.fetchone()

            if row is None:
                raise SnapshotNotFoundError(
                    f"Snapshot not found: {name} for session {session_id}"
                )

            return self._deserialize_state(row[0])

    def recover_latest_snapshot(self, session_id: str) -> SessionState:
        """Recover from the most recent snapshot for a session"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT state_json FROM snapshots
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            )
            row = cursor.fetchone()

            if row is None:
                raise SnapshotNotFoundError(
                    f"No snapshots found for session {session_id}"
                )

            return self._deserialize_state(row[0])

    def list_snapshots(self, session_id: str) -> list[dict[str, Any]]:
        """List all snapshots for a session"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT snapshot_id, name, created_at, metadata_json
                   FROM snapshots WHERE session_id = ?
                   ORDER BY created_at DESC""",
                (session_id,)
            )

            return [
                {
                    "snapshot_id": row[0],
                    "name": row[1],
                    "created_at": row[2],
                    "metadata": json.loads(row[3]) if row[3] else None
                }
                for row in cursor.fetchall()
            ]

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT session_id, created_at, updated_at FROM sessions
                   ORDER BY updated_at DESC"""
            )

            return [
                {
                    "session_id": row[0],
                    "created_at": row[1],
                    "updated_at": row[2]
                }
                for row in cursor.fetchall()
            ]

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all its snapshots"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM snapshots WHERE session_id = ?",
                (session_id,)
            )
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,)
            )

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            return cursor.fetchone() is not None
