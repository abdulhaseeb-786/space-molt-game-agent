"""Persistent State, Mission Memory & Task Store using SQLite.
Meets Requirement 5 ("Persistent memory and reliability"):
- Records all A2A task assignments, progression, and final outputs
- Prevents duplicate operations on recovery/restart (idempotency)
- Stores persistent pilot observations, system charts, and market findings
- Survives unexpected crashes or controlled TA demonstration failures
"""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'logs' / 'state.sqlite3'


class StateManager:
    """Thread-safe / process-safe SQLite persistence manager for MAS tasks and observations."""

    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observations (
                    key TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS completed_actions (
                    action_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    details TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
            ''')
            conn.commit()

    # --- Task Management ---

    def create_task(self, agent: str, goal: str, payload: Dict[str, Any], task_id: Optional[str] = None) -> str:
        """Create a new mission task in PENDING state."""
        tid = task_id or f'TASK-{uuid.uuid4().hex[:8].upper()}'
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                '''INSERT INTO tasks (task_id, agent, goal, payload, status, result, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'PENDING', NULL, ?, ?)''',
                (tid, agent, goal, json.dumps(payload, ensure_ascii=False), now, now)
            )
            conn.commit()
        return tid

    def update_task_status(self, task_id: str, status: str, result: Optional[Dict[str, Any]] = None):
        """Update task progress: PENDING -> IN_PROGRESS -> COMPLETED / FAILED."""
        now = time.time()
        res_str = json.dumps(result, ensure_ascii=False) if result is not None else None
        with self._get_conn() as conn:
            if res_str is not None:
                conn.execute(
                    '''UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE task_id = ?''',
                    (status, res_str, now, task_id)
                )
            else:
                conn.execute(
                    '''UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?''',
                    (status, now, task_id)
                )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a task record by ID."""
        with self._get_conn() as conn:
            row = conn.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,)).fetchone()
            if not row:
                return None
            return {
                'task_id': row['task_id'],
                'agent': row['agent'],
                'goal': row['goal'],
                'payload': json.loads(row['payload']),
                'status': row['status'],
                'result': json.loads(row['result']) if row['result'] else None,
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }

    def get_pending_tasks(self, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch pending tasks for recovery or assignment."""
        with self._get_conn() as conn:
            if agent:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE agent = ? AND status IN ('PENDING', 'IN_PROGRESS') ORDER BY created_at ASC",
                    (agent,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status IN ('PENDING', 'IN_PROGRESS') ORDER BY created_at ASC"
                ).fetchall()
            return [
                {
                    'task_id': r['task_id'],
                    'agent': r['agent'],
                    'goal': r['goal'],
                    'payload': json.loads(r['payload']),
                    'status': r['status'],
                    'result': json.loads(r['result']) if r['result'] else None
                }
                for r in rows
            ]

    # --- Persistent Observations & Intelligence ---

    def save_observation(self, key: str, agent: str, data: Any):
        """Save an observation (e.g. system chart, asteroid location, best station prices)."""
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                '''INSERT INTO observations (key, agent, data, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET agent=excluded.agent, data=excluded.data, updated_at=excluded.updated_at''',
                (key, agent, json.dumps(data, ensure_ascii=False), now)
            )
            conn.commit()

    def get_observation(self, key: str) -> Optional[Any]:
        """Fetch cached observation."""
        with self._get_conn() as conn:
            row = conn.execute('SELECT data FROM observations WHERE key = ?', (key,)).fetchone()
            if row:
                return json.loads(row['data'])
            return None

    # --- Idempotency & Duplicate Prevention ---

    def is_action_completed(self, action_id: str) -> bool:
        """Check if an action (e.g. trade execution) was already completed."""
        with self._get_conn() as conn:
            row = conn.execute('SELECT 1 FROM completed_actions WHERE action_id = ?', (action_id,)).fetchone()
            return row is not None

    def mark_action_completed(self, action_id: str, action_type: str, details: Dict[str, Any]):
        """Record an action as executed to prevent duplicate execution across restarts."""
        with self._get_conn() as conn:
            conn.execute(
                '''INSERT OR IGNORE INTO completed_actions (action_id, action_type, details, timestamp)
                   VALUES (?, ?, ?, ?)''',
                (action_id, action_type, json.dumps(details, ensure_ascii=False), time.time())
            )
            conn.commit()

    def get_summary(self) -> Dict[str, Any]:
        """Get aggregate metrics of tasks and actions."""
        with self._get_conn() as conn:
            tasks_total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
            tasks_completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'COMPLETED'").fetchone()[0]
            actions_completed = conn.execute('SELECT COUNT(*) FROM completed_actions').fetchone()[0]
            return {
                'total_tasks': tasks_total,
                'completed_tasks': tasks_completed,
                'completed_actions': actions_completed
            }
