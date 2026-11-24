"""SQLite storage for the board: tasks plus an append only log of moves."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

STATES = ("queued", "in_progress", "blocked", "waiting_human", "done")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    owner         TEXT,
    state         TEXT NOT NULL
                  CHECK (state IN ('queued','in_progress','blocked','waiting_human','done')),
    waiting_on    TEXT,
    note          TEXT,
    created_at    TEXT NOT NULL,
    last_moved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS moves (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL REFERENCES tasks(id),
    from_state TEXT,
    to_state   TEXT NOT NULL,
    moved_at   TEXT NOT NULL,
    note       TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_moves_task ON moves(task_id, moved_at);
"""


class BoardError(Exception):
    """Raised for bad input: unknown task, unknown state, duplicate id."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 timestamp. Naive values are treated as UTC."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BoardError(f"not an ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    owner: Optional[str]
    state: str
    waiting_on: Optional[str]
    note: Optional[str]
    created_at: datetime
    last_moved_at: datetime


@dataclass(frozen=True)
class Move:
    task_id: str
    from_state: Optional[str]
    to_state: str
    moved_at: datetime
    note: Optional[str]


def _check_state(state: str) -> None:
    if state not in STATES:
        raise BoardError(f"unknown state {state!r}; expected one of {', '.join(STATES)}")


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class Board:
    """A thin wrapper over one SQLite file. Use as a context manager."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def __enter__(self) -> "Board":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    # writes -----------------------------------------------------------

    def add_task(
        self,
        task_id: str,
        title: str,
        owner: Optional[str] = None,
        state: str = "queued",
        waiting_on: Optional[str] = None,
        note: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Task:
        _check_state(state)
        task_id = task_id.strip()
        if not task_id or not title.strip():
            raise BoardError("task id and title are required")
        stamp = format_ts(now or utcnow())
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO tasks (id, title, owner, state, waiting_on, note,"
                    " created_at, last_moved_at) VALUES (?,?,?,?,?,?,?,?)",
                    (task_id, title.strip(), _clean(owner), state,
                     _clean(waiting_on), _clean(note), stamp, stamp),
                )
                self.conn.execute(
                    "INSERT INTO moves (task_id, from_state, to_state, moved_at, note)"
                    " VALUES (?,?,?,?,?)",
                    (task_id, None, state, stamp, "created"),
                )
        except sqlite3.IntegrityError as exc:
            raise BoardError(f"task {task_id!r} already exists") from exc
        return self.get_task(task_id)

    def move_task(
        self,
        task_id: str,
        state: str,
        waiting_on: Optional[str] = None,
        note: Optional[str] = None,
        owner: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Task:
        """Change a task's state and reset its last moved time.

        Moving to the same state is allowed: it is how an agent says
        "still alive, still working" (a heartbeat). waiting_on is cleared
        unless the new state is blocked or waiting_human.
        """
        _check_state(state)
        current = self.get_task(task_id)
        stamp = format_ts(now or utcnow())
        keeps_waiting = state in ("blocked", "waiting_human")
        new_waiting = _clean(waiting_on) if keeps_waiting else None
        if keeps_waiting and new_waiting is None and state == current.state:
            new_waiting = current.waiting_on
        new_owner = _clean(owner) or current.owner
        new_note = _clean(note) or current.note
        with self.conn:
            self.conn.execute(
                "UPDATE tasks SET state=?, waiting_on=?, note=?, owner=?,"
                " last_moved_at=? WHERE id=?",
                (state, new_waiting, new_note, new_owner, stamp, task_id),
            )
            self.conn.execute(
                "INSERT INTO moves (task_id, from_state, to_state, moved_at, note)"
                " VALUES (?,?,?,?,?)",
                (task_id, current.state, state, stamp, _clean(note)),
            )
        return self.get_task(task_id)

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM moves")
            self.conn.execute("DELETE FROM tasks")

    # reads ------------------------------------------------------------

    def get_task(self, task_id: str) -> Task:
        row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise BoardError(f"no task with id {task_id!r}")
        return _row_to_task(row)

    def list_tasks(self) -> list[Task]:
        rows = self.conn.execute(
            "SELECT * FROM tasks ORDER BY last_moved_at ASC, id ASC"
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def moves_for(self, task_id: str) -> list[Move]:
        rows = self.conn.execute(
            "SELECT * FROM moves WHERE task_id=? ORDER BY id ASC", (task_id,)
        ).fetchall()
        return [
            Move(r["task_id"], r["from_state"], r["to_state"],
                 parse_ts(r["moved_at"]), r["note"])
            for r in rows
        ]


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        title=row["title"],
        owner=row["owner"],
        state=row["state"],
        waiting_on=row["waiting_on"],
        note=row["note"],
        created_at=parse_ts(row["created_at"]),
        last_moved_at=parse_ts(row["last_moved_at"]),
    )
