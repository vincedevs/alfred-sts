"""Alfred's one SQLite database file: a record of background jobs.

A job is written here when it starts and updated as it runs, so after a restart
Alfred knows which jobs to pick up again and which results it hasn't told you yet.
"""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY,
    request     TEXT    NOT NULL,           -- what you asked for, in your words
    status      TEXT    NOT NULL,           -- running | done | failed | stopped
    result      TEXT,                       -- the answer, or what went wrong
    session_id  TEXT,                       -- Claude session, used to resume after a restart
    created_at  REAL    NOT NULL,
    finished_at REAL,
    told_user   INTEGER NOT NULL DEFAULT 0  -- 1 once Alfred has said the result
)
"""


@dataclass
class Task:
    id: int
    request: str
    status: str
    result: str | None
    session_id: str | None
    created_at: float
    finished_at: float | None
    told_user: bool


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(SCHEMA)
        self._conn.commit()

    def add_task(self, request: str) -> int:
        cursor = self._conn.execute(
            "INSERT INTO tasks (request, status, created_at) VALUES (?, 'running', ?)",
            (request, time.time()),
        )
        self._conn.commit()
        return cursor.lastrowid

    def set_session(self, task_id: int, session_id: str) -> None:
        self._conn.execute("UPDATE tasks SET session_id = ? WHERE id = ?", (session_id, task_id))
        self._conn.commit()

    def finish_task(self, task_id: int, status: str, result: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET status = ?, result = ?, finished_at = ? WHERE id = ?",
            (status, result, time.time(), task_id),
        )
        self._conn.commit()

    def mark_told(self, task_ids: list[int]) -> None:
        self._conn.executemany(
            "UPDATE tasks SET told_user = 1 WHERE id = ?", [(i,) for i in task_ids]
        )
        self._conn.commit()

    def get_task(self, task_id: int) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _to_task(row) if row else None

    def recent_tasks(self, limit: int = 5) -> list[Task]:
        rows = self._conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
        return [_to_task(row) for row in rows]

    def running_tasks(self) -> list[Task]:
        rows = self._conn.execute("SELECT * FROM tasks WHERE status = 'running' ORDER BY id")
        return [_to_task(row) for row in rows]

    def untold_results(self) -> list[Task]:
        """Finished jobs whose result Alfred hasn't said yet."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE status != 'running' AND told_user = 0 ORDER BY id"
        )
        return [_to_task(row) for row in rows]

    def close(self) -> None:
        self._conn.close()


def _to_task(row: sqlite3.Row) -> Task:
    return Task(**{**dict(row), "told_user": bool(row["told_user"])})
