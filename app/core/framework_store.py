"""Durable framework-operational records kept separately from customer messages.

The store deliberately records identifiers and bounded metadata only: never API
keys, webhook secrets, or raw chat text.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.core.database import utc_now


class FrameworkStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS framework_audit_events (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    merchant_id TEXT,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_merchant_time
                    ON framework_audit_events(merchant_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS framework_idempotency (
                    principal_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(principal_id, operation, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS merchant_config_revisions (
                    revision_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'active', 'superseded')),
                    config_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    UNIQUE(merchant_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_config_revision_merchant
                    ON merchant_config_revisions(merchant_id, version DESC);
                CREATE TABLE IF NOT EXISTS framework_events (
                    event_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivery_status TEXT NOT NULL CHECK(delivery_status IN ('pending', 'delivered', 'not_configured', 'failed')),
                    delivery_attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    delivered_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_framework_events_merchant
                    ON framework_events(merchant_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS knowledge_index_jobs (
                    job_id TEXT PRIMARY KEY,
                    merchant_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'failed')),
                    requested_by TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_json TEXT,
                    error_code TEXT
                );
                """
            )

    def record_audit(
        self,
        *,
        request_id: str,
        principal_id: str,
        merchant_id: str | None,
        action: str,
        outcome: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO framework_audit_events(
                    audit_id, request_id, principal_id, merchant_id, action, outcome, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), request_id, principal_id, merchant_id, action, outcome,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), utc_now(),
                ),
            )

    def list_audit(self, *, merchant_id: str | None, limit: int = 50) -> list[dict[str, object]]:
        query = """
            SELECT request_id, principal_id, merchant_id, action, outcome, metadata_json, created_at
            FROM framework_audit_events
        """
        parameters: tuple[object, ...] = ()
        if merchant_id is not None:
            query += " WHERE merchant_id = ?"
            parameters = (merchant_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (*parameters, limit)).fetchall()
        return [
            {
                **{key: row[key] for key in ("request_id", "principal_id", "merchant_id", "action", "outcome", "created_at")},
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def metric_counts(self, *, merchant_id: str | None) -> list[dict[str, object]]:
        query = "SELECT action, outcome, COUNT(*) AS count FROM framework_audit_events"
        parameters: tuple[object, ...] = ()
        if merchant_id is not None:
            query += " WHERE merchant_id = ?"
            parameters = (merchant_id,)
        query += " GROUP BY action, outcome ORDER BY action, outcome"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def get_idempotent_response(
        self, *, principal_id: str, operation: str, idempotency_key: str
    ) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT request_hash, response_json FROM framework_idempotency
                WHERE principal_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (principal_id, operation, idempotency_key),
            ).fetchone()
        return dict(row) if row else None

    def save_idempotent_response(
        self,
        *,
        principal_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        response: dict[str, object],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO framework_idempotency(
                    principal_id, operation, idempotency_key, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    principal_id, operation, idempotency_key, request_hash,
                    json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")), utc_now(),
                ),
            )

    def create_event(
        self, *, merchant_id: str, event_type: str, request_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        record = {
            "event_id": str(uuid4()), "merchant_id": merchant_id, "event_type": event_type,
            "request_id": request_id, "payload": payload, "delivery_status": "pending",
            "delivery_attempts": 0, "created_at": utc_now(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO framework_events(
                    event_id, merchant_id, event_type, request_id, payload_json, delivery_status,
                    delivery_attempts, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["event_id"], merchant_id, event_type, request_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    record["delivery_status"], record["delivery_attempts"], record["created_at"],
                ),
            )
        return record

    def list_events(self, *, merchant_id: str, limit: int = 50) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, merchant_id, event_type, request_id, payload_json, delivery_status,
                       delivery_attempts, last_error, created_at, delivered_at
                FROM framework_events WHERE merchant_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (merchant_id, limit),
            ).fetchall()
        return [
            {
                **{key: row[key] for key in (
                    "event_id", "merchant_id", "event_type", "request_id", "delivery_status",
                    "delivery_attempts", "last_error", "created_at", "delivered_at",
                )},
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def get_event(self, event_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT event_id, merchant_id, event_type, request_id, payload_json, delivery_status,
                   delivery_attempts, last_error, created_at, delivered_at FROM framework_events WHERE event_id = ?""",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            **{key: row[key] for key in ("event_id", "merchant_id", "event_type", "request_id", "delivery_status", "delivery_attempts", "last_error", "created_at", "delivered_at")},
            "payload": json.loads(row["payload_json"]),
        }

    def mark_event_delivery(self, *, event_id: str, status: str, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE framework_events SET delivery_status = ?, delivery_attempts = delivery_attempts + 1,
                   last_error = ?, delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END
                   WHERE event_id = ?""",
                (status, error, status, utc_now(), event_id),
            )

    def create_config_revision(
        self, *, merchant_id: str, config: dict[str, object], created_by: str
    ) -> dict[str, object]:
        with self._connect() as connection:
            version = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM merchant_config_revisions WHERE merchant_id = ?",
                    (merchant_id,),
                ).fetchone()[0]
            )
            record = {
                "revision_id": str(uuid4()), "merchant_id": merchant_id, "version": version,
                "status": "draft", "config": config, "created_by": created_by, "created_at": utc_now(),
                "activated_at": None,
            }
            connection.execute(
                """
                INSERT INTO merchant_config_revisions(
                    revision_id, merchant_id, version, status, config_json, created_by, created_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["revision_id"], merchant_id, version, "draft",
                    json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")), created_by,
                    record["created_at"], None,
                ),
            )
        return record

    def get_config_revision(self, revision_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM merchant_config_revisions WHERE revision_id = ?", (revision_id,)).fetchone()
        return _config_row(row) if row else None

    def list_config_revisions(self, merchant_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM merchant_config_revisions WHERE merchant_id = ? ORDER BY version DESC", (merchant_id,)
            ).fetchall()
        return [_config_row(row) for row in rows]

    def activate_config_revision(self, revision_id: str) -> dict[str, object] | None:
        record = self.get_config_revision(revision_id)
        if record is None:
            return None
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE merchant_config_revisions SET status = 'superseded' WHERE merchant_id = ? AND status = 'active'",
                (record["merchant_id"],),
            )
            connection.execute(
                "UPDATE merchant_config_revisions SET status = 'active', activated_at = ? WHERE revision_id = ?",
                (now, revision_id),
            )
        return self.get_config_revision(revision_id)

    def active_config_revisions(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM merchant_config_revisions WHERE status = 'active' ORDER BY merchant_id"
            ).fetchall()
        return [_config_row(row) for row in rows]

    def create_knowledge_job(self, *, merchant_id: str, requested_by: str) -> dict[str, object]:
        record = {"job_id": str(uuid4()), "merchant_id": merchant_id, "status": "queued", "requested_by": requested_by, "requested_at": utc_now()}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_index_jobs(job_id, merchant_id, status, requested_by, requested_at) VALUES (?, ?, ?, ?, ?)",
                (record["job_id"], merchant_id, "queued", requested_by, record["requested_at"]),
            )
        return record

    def complete_knowledge_job(self, *, job_id: str, result: dict[str, int] | None, error_code: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE knowledge_index_jobs SET status = ?, completed_at = ?, result_json = ?, error_code = ? WHERE job_id = ?""",
                (
                    "completed" if error_code is None else "failed", utc_now(),
                    json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None, error_code, job_id,
                ),
            )

    def get_knowledge_job(self, job_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM knowledge_index_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return {
            "job_id": row["job_id"], "merchant_id": row["merchant_id"], "status": row["status"],
            "requested_by": row["requested_by"], "requested_at": row["requested_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error_code": row["error_code"],
        }


def _config_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "revision_id": row["revision_id"], "merchant_id": row["merchant_id"], "version": row["version"],
        "status": row["status"], "config": json.loads(row["config_json"]), "created_by": row["created_by"],
        "created_at": row["created_at"], "activated_at": row["activated_at"],
    }
