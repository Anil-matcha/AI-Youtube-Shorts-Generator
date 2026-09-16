"""Inspect or apply Shorts Studio project-data migrations.

Usage::

    python scripts/migrate_data.py --data-dir ./output
    python scripts/migrate_data.py --data-dir ./output --apply

The default is a dry run.  ``--apply`` creates a timestamped backup before
updating JSON mirrors and the SQLite job store.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.job_store import JobStore
from web.migrations import CURRENT_SCHEMA_VERSION, migrate_job_record, needs_migration


def _paths(data_dir: Path) -> tuple[Path, Path]:
    root = data_dir.expanduser().resolve()
    output = root / "output"
    jobs_dir = output / "jobs" if (output / "jobs").is_dir() else root / "jobs"
    db = output / "jobs.sqlite3" if (output / "jobs.sqlite3").is_file() else root / "jobs.sqlite3"
    return jobs_dir, db


def _load_json_jobs(jobs_dir: Path) -> List[tuple[Path, Dict[str, Any]]]:
    jobs: List[tuple[Path, Dict[str, Any]]] = []
    if not jobs_dir.is_dir():
        return jobs
    for path in sorted(jobs_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("id"):
            jobs.append((path, value))
    return jobs


def _schema_version(record: Dict[str, Any]) -> int:
    try:
        return max(0, int(record.get("schema_version") or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("."), help="Shorts Studio data root")
    parser.add_argument("--apply", action="store_true", help="Apply migrations after creating a backup")
    args = parser.parse_args()
    jobs_dir, database = _paths(args.data_dir)
    json_jobs = _load_json_jobs(jobs_dir)
    db_jobs: List[Dict[str, Any]] = []
    if database.is_file():
        store = JobStore(database)
        try:
            db_jobs = store.load_all()
        finally:
            store.close()
    all_records: Dict[str, Dict[str, Any]] = {str(record.get("id")): record for record in db_jobs if record.get("id")}
    for _, record in json_jobs:
        all_records.setdefault(str(record.get("id")), record)
    pending = [record for record in all_records.values() if needs_migration(record)]
    newer = [record for record in all_records.values() if _schema_version(record) > CURRENT_SCHEMA_VERSION]
    summary: Dict[str, Any] = {
        "data_dir": str(args.data_dir.expanduser().resolve()),
        "jobs_dir": str(jobs_dir),
        "database": str(database),
        "current_schema_version": CURRENT_SCHEMA_VERSION,
        "projects_scanned": len(all_records),
        "projects_needing_migration": len(pending),
        "projects_with_newer_schema": len(newer),
        "applied": False,
    }
    if not args.apply or not pending:
        print(json.dumps(summary, indent=2))
        return 0

    backup_root = args.data_dir.expanduser().resolve() / ".migration-backups" / time.strftime("%Y%m%d_%H%M%S")
    backup_root.mkdir(parents=True, exist_ok=True)
    migrated_ids: set[str] = set()
    for path, record in json_jobs:
        try:
            migrated, steps = migrate_job_record(record)
        except ValueError:
            continue
        if not steps:
            continue
        shutil.copy2(path, backup_root / path.name)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(migrated, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)
        migrated_ids.add(str(migrated["id"]))

    if database.is_file():
        store = JobStore(database)
        try:
            for record in pending:
                migrated, steps = migrate_job_record(record)
                if steps:
                    store.save(migrated)
                    migrated_ids.add(str(migrated["id"]))
        finally:
            store.close()
    summary.update({"applied": True, "migrated_projects": len(migrated_ids), "backup_dir": str(backup_root)})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
