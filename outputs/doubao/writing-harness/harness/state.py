import sqlite3
import json
from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
from .schemas import SessionInfo, GenerationState


class StateStore:
    def __init__(self, db_path: str = "harness_state.db"):
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()

    def _connect(self):
        """Connect to the SQLite database"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def _create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()

        # Sessions table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            start_time TIMESTAMP NOT NULL,
            last_updated TIMESTAMP NOT NULL,
            current_state TEXT NOT NULL,
            task_spec TEXT,
            current_scene_id INTEGER DEFAULT 0
        )
        ''')

        # State snapshots table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            state TEXT NOT NULL,
            snapshot_data TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        ''')

        # Trajectory entries table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS trajectory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            state TEXT NOT NULL,
            step_description TEXT NOT NULL,
            context_snapshot TEXT,
            tool_call TEXT,
            tool_result TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
        ''')

        self.conn.commit()

    def create_session(self, task_spec: Optional[Dict[str, Any]] = None) -> SessionInfo:
        """Create a new session"""
        session_id = str(uuid4())
        now = datetime.now().isoformat()

        session_info = SessionInfo(
            session_id=UUID(session_id),
            start_time=datetime.fromisoformat(now),
            last_updated=datetime.fromisoformat(now),
            current_state=GenerationState.INITIALIZED,
            task_spec=task_spec
        )

        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO sessions (session_id, start_time, last_updated, current_state, task_spec, current_scene_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            session_id,
            session_info.start_time.isoformat(),
            session_info.last_updated.isoformat(),
            session_info.current_state.value,
            json.dumps(task_spec) if task_spec else None,
            session_info.current_scene_id
        ))

        self.conn.commit()
        return session_info

    def get_session(self, session_id: UUID) -> Optional[SessionInfo]:
        """Retrieve session information"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM sessions WHERE session_id = ?', (str(session_id),))
        row = cursor.fetchone()

        if not row:
            return None

        task_spec = json.loads(row['task_spec']) if row['task_spec'] else None

        return SessionInfo(
            session_id=UUID(row['session_id']),
            start_time=datetime.fromisoformat(row['start_time']),
            last_updated=datetime.fromisoformat(row['last_updated']),
            current_state=GenerationState(row['current_state']),
            task_spec=task_spec,
            current_scene_id=row['current_scene_id']
        )

    def update_session(self, session_info: SessionInfo):
        """Update session information"""
        now = datetime.now().isoformat()
        cursor = self.conn.cursor()
        cursor.execute('''
        UPDATE sessions
        SET last_updated = ?, current_state = ?, task_spec = ?, current_scene_id = ?
        WHERE session_id = ?
        ''', (
            now,
            session_info.current_state.value,
            json.dumps(session_info.task_spec) if session_info.task_spec else None,
            session_info.current_scene_id,
            str(session_info.session_id)
        ))
        self.conn.commit()

    def snapshot(self, session_id: UUID, state: GenerationState, snapshot_data: Dict[str, Any]):
        """Create a state snapshot"""
        now = datetime.now().isoformat()
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO snapshots (session_id, timestamp, state, snapshot_data)
        VALUES (?, ?, ?, ?)
        ''', (
            str(session_id),
            now,
            state.value,
            json.dumps(snapshot_data)
        ))
        self.conn.commit()

    def get_latest_snapshot(self, session_id: UUID) -> Optional[Dict[str, Any]]:
        """Get the most recent snapshot for a session"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM snapshots
        WHERE session_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
        ''', (str(session_id),))
        row = cursor.fetchone()

        if not row:
            return None

        return json.loads(row['snapshot_data'])

    def add_trajectory_entry(
        self,
        session_id: UUID,
        state: GenerationState,
        step_description: str,
        context_snapshot: Optional[Dict[str, Any]] = None,
        tool_call: Optional[Dict[str, Any]] = None,
        tool_result: Optional[Dict[str, Any]] = None
    ):
        """Add an entry to the trajectory log"""
        now = datetime.now().isoformat()
        cursor = self.conn.cursor()
        cursor.execute('''
        INSERT INTO trajectory (
            session_id, timestamp, state, step_description,
            context_snapshot, tool_call, tool_result
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(session_id),
            now,
            state.value,
            step_description,
            json.dumps(context_snapshot) if context_snapshot else None,
            json.dumps(tool_call) if tool_call else None,
            json.dumps(tool_result) if tool_result else None
        ))
        self.conn.commit()

    def get_trajectory(self, session_id: UUID) -> List[Dict[str, Any]]:
        """Get full trajectory for a session"""
        cursor = self.conn.cursor()
        cursor.execute('''
        SELECT * FROM trajectory
        WHERE session_id = ?
        ORDER BY timestamp ASC
        ''', (str(session_id),))

        rows = cursor.fetchall()
        trajectory = []

        for row in rows:
            entry = {
                'timestamp': row['timestamp'],
                'state': GenerationState(row['state']),
                'step_description': row['step_description'],
                'context_snapshot': json.loads(row['context_snapshot']) if row['context_snapshot'] else None,
                'tool_call': json.loads(row['tool_call']) if row['tool_call'] else None,
                'tool_result': json.loads(row['tool_result']) if row['tool_result'] else None
            }
            trajectory.append(entry)

        return trajectory

    def recover_session(self, session_id: UUID) -> Optional[Dict[str, Any]]:
        """Recover full session state from latest snapshot"""
        snapshot = self.get_latest_snapshot(session_id)
        return snapshot if snapshot else None

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()