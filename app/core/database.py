"""Small SQLite persistence layer for short-lived demo sessions."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SessionStore:
    """Stores session identity, messages and bounded agent state; never credentials."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, message_id);
                CREATE TABLE IF NOT EXISTS session_state (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS handoff_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    merchant_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    ticket_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_handoff_tickets_session ON handoff_tickets(session_id);
                """
            )

    def ping(self) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    def create_session(self, merchant_id: str, customer_id: str) -> dict[str, str]:
        now = utc_now()
        session = {
            "session_id": str(uuid4()),
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (session_id, merchant_id, customer_id, created_at, updated_at)
                VALUES (:session_id, :merchant_id, :customer_id, :created_at, :updated_at)
                """,
                session,
            )
        return session

    def get_session(self, session_id: str) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_id, merchant_id, customer_id, created_at, updated_at FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE session_id = ? ORDER BY message_id ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_message(self, session_id: str, role: str, content: str) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            connection.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))

    def get_state(self, session_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM session_state WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(row["state_json"])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid persisted state for session '{session_id}'") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Invalid persisted state for session '{session_id}'")
        return value

    def set_state(self, session_id: str, state: dict[str, object]) -> None:
        now = utc_now()
        serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO session_state(session_id, state_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at
                """,
                (session_id, serialized, now),
            )
            connection.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))

    def reset_session(self, session_id: str) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM session_state WHERE session_id = ?", (session_id,))
            updated = connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
            )
        return cursor.rowcount >= 0 and updated.rowcount == 1

    def create_handoff_ticket(
        self, *, ticket_id: str, session_id: str, merchant_id: str, summary: str, reason: str
    ) -> dict[str, str]:
        record = {
            "ticket_id": ticket_id,
            "session_id": session_id,
            "merchant_id": merchant_id,
            "summary": summary,
            "reason": reason,
            "status": "created",
            "created_at": utc_now(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO handoff_tickets(
                    ticket_id, session_id, merchant_id, summary, reason, ticket_status, created_at
                ) VALUES (:ticket_id, :session_id, :merchant_id, :summary, :reason, :status, :created_at)
                """,
                record,
            )
        return record

    def get_handoff_ticket(self, ticket_id: str) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ticket_id, session_id, merchant_id, summary, reason,
                       ticket_status AS status, created_at
                FROM handoff_tickets WHERE ticket_id = ?
                """,
                (ticket_id,),
            ).fetchone()
        return dict(row) if row else None
