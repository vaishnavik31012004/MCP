from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["running", "waiting_approval", "completed", "failed", "cancelled"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class TaskStore:
    """Tiny synchronous SQLite store for task bookkeeping and their event logs.

    This is deliberately separate from LangGraph's own checkpointer (which
    persists graph state for pause/resume) — this store is what the frontend
    reads to render task history and replay an event timeline.
    """

    def __init__(self, db_path: str):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def create_task(self, goal: str) -> str:
        task_id = str(uuid.uuid4())
        now = _now()
        self._conn.execute(
            "INSERT INTO tasks (id, goal, status, result, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, goal, "running", None, now, now),
        )
        self._conn.commit()
        return task_id

    def update_status(self, task_id: str, status: TaskStatus, result: Any = None) -> None:
        self._conn.execute(
            "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE id = ?",
            (status, json.dumps(result) if result is not None else None, _now(), task_id),
        )
        self._conn.commit()

    def add_event(self, task_id: str, event_type: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT INTO task_events (task_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (task_id, event_type, json.dumps(payload), _now()),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT id, goal, status, result, created_at, updated_at FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "goal": row[1],
            "status": row[2],
            "result": json.loads(row[3]) if row[3] else None,
            "created_at": row[4],
            "updated_at": row[5],
        }

    def get_events(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT event_type, payload, created_at FROM task_events WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        ).fetchall()
        return [{"type": r[0], "payload": json.loads(r[1]), "created_at": r[2]} for r in rows]

    def list_tasks(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, goal, status, result, created_at, updated_at FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "goal": r[1],
                "status": r[2],
                "result": json.loads(r[3]) if r[3] else None,
                "created_at": r[4],
                "updated_at": r[5],
            }
            for r in rows
        ]
