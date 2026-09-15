"""Small SQLite-backed durable store for Shorts Studio jobs.

The in-memory dictionary remains the fast read/write surface used by the web
handlers, while this module provides the durable boundary that survives a
process restart.  The JSON job files are kept as a portable mirror for backup
and for older installations; SQLite is the source used during recovery.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List


class JobStore:
    """Thread-safe SQLite job store with WAL and an idempotent schema."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA busy_timeout=30000")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at DESC)")
            self._connection.commit()

    def save(self, job: Dict[str, Any]) -> None:
        """Insert or update one complete job snapshot atomically."""
        job_id = str(job.get("id") or "").strip()
        if not job_id:
            raise ValueError("job id is required")
        status = str(job.get("status") or "unknown")
        stage = str(job.get("stage") or "unknown")
        try:
            progress = float(job.get("progress") or 0)
        except (TypeError, ValueError, OverflowError):
            progress = 0.0
        try:
            updated_at = float(job.get("updated_at") or 0)
        except (TypeError, ValueError, OverflowError):
            updated_at = 0.0
        payload = json.dumps(job, ensure_ascii=False, default=str, separators=(",", ":"))
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO jobs(id, status, stage, progress, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    stage=excluded.stage,
                    progress=excluded.progress,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (job_id, status, stage, progress, updated_at, payload),
            )
            self._connection.commit()

    def load_all(self) -> List[Dict[str, Any]]:
        """Return valid JSON job payloads newest first."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload FROM jobs ORDER BY updated_at DESC, id ASC"
            ).fetchall()
        records: List[Dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(str(row["payload"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("id"):
                records.append(value)
        return records

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM jobs WHERE id = ?", (str(job_id),))
            self._connection.commit()

    def clear(self) -> None:
        """Clear records (used by isolated tests and explicit maintenance)."""
        with self._lock:
            self._connection.execute("DELETE FROM jobs")
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
