"""Durable job queue (architecture §2.5.6).

The worker topology needs a queue that survives process death: intake ->
liteparse -> glm_ocr -> enrichment. Production runs NATS or Postgres
``pg_jobs``; this ships a SQLite-backed implementation with the same
semantics so a single-node deployment needs no extra infrastructure.

Semantics that matter for a document pipeline:
    - Leasing, not popping. A worker that dies mid-document must not lose
      the job; the lease expires and another worker picks it up.
    - Bounded retries with a terminal DEAD state. A document that crashes
      the parser must not loop forever.
    - Idempotency keys. Re-ingesting the same blob for the same stage is a
      no-op rather than duplicate work, which matters because content-
      addressed intake makes re-submission common.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Protocol


class JobType(str, Enum):
    INTAKE = "intake"
    LITEPARSE = "liteparse"
    LAYOUT_REGIONS = "layout_regions"
    KIE_EXTRACT = "kie_extract"
    TEXT_RESCUE = "text_rescue"
    CHUNK = "chunk"
    ENRICH = "enrich"
    EMBED = "embed"
    INDEX = "index"
    GRAPH = "graph"
    REPARSE = "reparse"


class JobState(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"


@dataclass(frozen=True)
class Job:
    job_id: str
    job_type: JobType
    payload: dict[str, Any]
    state: JobState
    attempts: int
    idempotency_key: str | None = None
    last_error: str | None = None


class JobQueue(Protocol):
    def enqueue(
        self,
        job_type: JobType,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> Job | None: ...

    def lease(
        self,
        job_types: Iterable[JobType],
        *,
        lease_seconds: int = 300,
    ) -> Job | None: ...

    def complete(self, job_id: str) -> None: ...

    def fail(self, job_id: str, error: str) -> None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    job_type         TEXT NOT NULL,
    payload          TEXT NOT NULL,
    state            TEXT NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 3,
    idempotency_key  TEXT,
    leased_until     TEXT,
    last_error       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency
    ON jobs (job_type, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (state, job_type);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class SQLiteJobQueue:
    """Durable queue backed by SQLite. Safe across threads and processes."""

    def __init__(self, path: Path | str = ":memory:", *, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL keeps readers from blocking the writer; irrelevant for :memory:
        # but important for the on-disk case workers actually use.
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def enqueue(
        self,
        job_type: JobType,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int | None = None,
    ) -> Job | None:
        job_id = str(uuid.uuid4())
        now = _iso(_now())
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO jobs (job_id, job_type, payload, state, attempts,"
                    " max_attempts, idempotency_key, created_at, updated_at)"
                    " VALUES (?,?,?,?,0,?,?,?,?)",
                    (
                        job_id,
                        job_type.value,
                        json.dumps(payload, sort_keys=True),
                        JobState.PENDING.value,
                        max_attempts or self.max_attempts,
                        idempotency_key,
                        now,
                        now,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                # Duplicate idempotency key — already queued or processed.
                return None
        return Job(
            job_id=job_id,
            job_type=job_type,
            payload=payload,
            state=JobState.PENDING,
            attempts=0,
            idempotency_key=idempotency_key,
        )

    def lease(
        self,
        job_types: Iterable[JobType],
        *,
        lease_seconds: int = 300,
    ) -> Job | None:
        wanted = [t.value for t in job_types]
        if not wanted:
            return None
        now = _now()
        placeholders = ",".join("?" * len(wanted))
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM jobs WHERE job_type IN ({placeholders})"
                "  AND (state = ? OR (state = ? AND leased_until < ?))"
                " ORDER BY created_at LIMIT 1",
                (*wanted, JobState.PENDING.value, JobState.LEASED.value, _iso(now)),
            ).fetchone()
            if row is None:
                return None
            attempts = row["attempts"] + 1
            self._conn.execute(
                "UPDATE jobs SET state = ?, attempts = ?, leased_until = ?, updated_at = ?"
                " WHERE job_id = ?",
                (
                    JobState.LEASED.value,
                    attempts,
                    _iso(now + timedelta(seconds=lease_seconds)),
                    _iso(now),
                    row["job_id"],
                ),
            )
            self._conn.commit()
        return Job(
            job_id=row["job_id"],
            job_type=JobType(row["job_type"]),
            payload=json.loads(row["payload"]),
            state=JobState.LEASED,
            attempts=attempts,
            idempotency_key=row["idempotency_key"],
        )

    def complete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET state = ?, leased_until = NULL, updated_at = ?"
                " WHERE job_id = ?",
                (JobState.DONE.value, _iso(_now()), job_id),
            )
            self._conn.commit()

    def fail(self, job_id: str, error: str) -> None:
        """Retry until ``max_attempts``, then park in DEAD.

        A permanently failing document must stop consuming worker capacity;
        DEAD jobs are what the review dashboard surfaces.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT attempts, max_attempts FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return
            terminal = row["attempts"] >= row["max_attempts"]
            self._conn.execute(
                "UPDATE jobs SET state = ?, last_error = ?, leased_until = NULL,"
                " updated_at = ? WHERE job_id = ?",
                (
                    (JobState.DEAD if terminal else JobState.PENDING).value,
                    error[:2000],
                    _iso(_now()),
                    job_id,
                ),
            )
            self._conn.commit()

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
        ).fetchall()
        return {r["state"]: r["n"] for r in rows}

    def dead_letters(self) -> list[Job]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY updated_at DESC",
            (JobState.DEAD.value,),
        ).fetchall()
        return [
            Job(
                job_id=r["job_id"],
                job_type=JobType(r["job_type"]),
                payload=json.loads(r["payload"]),
                state=JobState.DEAD,
                attempts=r["attempts"],
                idempotency_key=r["idempotency_key"],
                last_error=r["last_error"],
            )
            for r in rows
        ]
