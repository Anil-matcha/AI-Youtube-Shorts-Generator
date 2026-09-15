"""Durability and migration checks for the SQLite job queue state."""

from __future__ import annotations

from pathlib import Path

from web.job_store import JobStore


def test_job_store_survives_reopen_and_updates_checkpoints(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobStore(path)
    first.save(
        {
            "id": "job-1",
            "status": "running",
            "stage": "transcribe",
            "progress": 45,
            "updated_at": 10.0,
            "checkpoint": {"stage": "transcribe", "progress": 45},
        }
    )
    first.close()

    second = JobStore(path)
    assert second.load_all()[0]["checkpoint"]["stage"] == "transcribe"
    second.save(
        {
            "id": "job-1",
            "status": "done",
            "stage": "done",
            "progress": 100,
            "updated_at": 11.0,
            "checkpoint": {"stage": "done", "progress": 100},
        }
    )
    assert second.load_all()[0]["status"] == "done"
    second.delete("job-1")
    assert second.load_all() == []
    second.close()


def test_job_store_clear_is_scoped_to_database(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.save({"id": "a", "status": "queued", "stage": "queued", "updated_at": 1})
    store.save({"id": "b", "status": "queued", "stage": "queued", "updated_at": 2})
    assert {record["id"] for record in store.load_all()} == {"a", "b"}
    store.clear()
    assert store.load_all() == []
    store.close()
