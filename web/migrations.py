"""Portable project-data migrations.

Jobs are JSON-shaped records stored in both SQLite and a human-readable mirror.
Migrations are pure, deterministic transformations so the application, backup
restore flow, and the standalone migration command all use the same rules.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple


CURRENT_SCHEMA_VERSION = 4
PROJECT_FORMAT_VERSION = "1.0"


def _version(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def needs_migration(record: Any, target: int = CURRENT_SCHEMA_VERSION) -> bool:
    return isinstance(record, dict) and _version(record.get("schema_version")) < int(target)


def migrate_job_record(record: Dict[str, Any], target: int = CURRENT_SCHEMA_VERSION) -> Tuple[Dict[str, Any], List[str]]:
    """Upgrade one record and return ``(record, applied_migrations)``.

    Unknown future schema versions are preserved rather than silently
    downgrading data.  The caller can surface that condition as a migration
    error when it needs to write the record.
    """

    if not isinstance(record, dict):
        raise ValueError("project record must be an object")
    target_version = int(target)
    current = _version(record.get("schema_version"))
    if current > target_version:
        raise ValueError(
            f"project schema {current} is newer than the supported schema {target_version}; upgrade Shorts Studio first"
        )
    job: Dict[str, Any] = copy.deepcopy(record)
    applied: List[str] = []

    # v1: normalize the original project shape used before durable checkpoints.
    if current < 1 <= target_version:
        request = job.get("request")
        if not isinstance(request, dict):
            request = {}
        if not request.get("url"):
            for alias in ("video_url", "source_url", "youtube_url", "path"):
                if request.get(alias):
                    request["url"] = request[alias]
                    break
        job["request"] = request
        if not isinstance(job.get("raw_shorts"), list):
            job["raw_shorts"] = _safe_list(_safe_dict(job.get("result")).get("shorts"))
        if not isinstance(job.get("raw_transcript"), dict):
            job["raw_transcript"] = _safe_dict(_safe_dict(job.get("result")).get("transcript"))
        if not isinstance(job.get("logs"), list):
            job["logs"] = []
        applied.append("v0_to_v1")
        current = 1

    # v2: ensure the durable job lifecycle fields exist and have safe values.
    if current < 2 <= target_version:
        job.setdefault("status", "draft")
        job.setdefault("stage", "draft")
        job.setdefault("message", "Migrated project")
        job.setdefault("progress", 0)
        if not isinstance(job.get("checkpoint"), dict):
            job["checkpoint"] = {"stage": job.get("stage", "draft"), "progress": job.get("progress", 0)}
        job.setdefault("archived", False)
        try:
            now = float(job.get("created_at") or job.get("updated_at") or 0.0)
        except (TypeError, ValueError, OverflowError):
            now = 0.0
        job.setdefault("created_at", now)
        job.setdefault("updated_at", job.get("created_at", now))
        applied.append("v1_to_v2")
        current = 2

    # v3: establish the result/raw-data split used by the editor and backup API.
    if current < 3 <= target_version:
        job.setdefault("result", None)
        job.setdefault("raw_shorts", [])
        job.setdefault("raw_transcript", {})
        job.setdefault("raw_source_video_url", None)
        job.setdefault("elapsed_seconds", None)
        job.setdefault("eta_seconds", None)
        applied.append("v2_to_v3")
        current = 3

    # v4: the beta project format adds experiments, analytics, and an explicit
    # format marker.  These fields are intentionally local metadata and never
    # contain runtime credentials.
    if current < 4 <= target_version:
        for field in ("variants", "analytics", "publishing"):
            if not isinstance(job.get(field), list):
                job[field] = []
        job.setdefault("project_format_version", PROJECT_FORMAT_VERSION)
        applied.append("v3_to_v4")
        current = 4

    # A current-schema record may still have been hand-edited or partially
    # written by an interrupted older process. Normalize the collection
    # boundaries on every upgrade so route handlers can rely on the format.
    if target_version >= 1:
        job["request"] = _safe_dict(job.get("request"))
        job["raw_shorts"] = _safe_list(job.get("raw_shorts"))
        job["raw_transcript"] = _safe_dict(job.get("raw_transcript"))
        job["logs"] = _safe_list(job.get("logs"))
    if target_version >= 2 and not isinstance(job.get("checkpoint"), dict):
        job["checkpoint"] = {"stage": job.get("stage", "draft"), "progress": job.get("progress", 0)}
    if target_version >= 4:
        for field in ("variants", "analytics", "publishing"):
            if not isinstance(job.get(field), list):
                job[field] = []

    job["schema_version"] = target_version
    job.setdefault("project_format_version", PROJECT_FORMAT_VERSION)
    history = job.get("migration_history")
    if not isinstance(history, list):
        history = []
    if applied:
        # Keep this transformation pure: callers can add an operational
        # timestamp after persisting if they need one.  A stable source
        # timestamp is retained for human inspection without making repeated
        # migrations produce different records.
        source_time = job.get("updated_at") or job.get("created_at")
        try:
            applied_at = float(source_time) if source_time is not None else None
        except (TypeError, ValueError, OverflowError):
            applied_at = None
        history.extend({"migration": name, "applied_at": applied_at} for name in applied)
    job["migration_history"] = history[-32:]
    return job, applied


def _safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def migration_summary(records: List[Dict[str, Any]], target: int = CURRENT_SCHEMA_VERSION) -> Dict[str, Any]:
    versions: Dict[str, int] = {}
    pending = 0
    newer = 0
    for record in records:
        value = _version(record.get("schema_version"))
        versions[str(value)] = versions.get(str(value), 0) + 1
        if value < target:
            pending += 1
        elif value > target:
            newer += 1
    return {
        "current_schema_version": int(target),
        "project_format_version": PROJECT_FORMAT_VERSION,
        "total_projects": len(records),
        "projects_needing_migration": pending,
        "projects_with_newer_schema": newer,
        "schema_versions": versions,
        "automatic_on_startup": True,
    }
