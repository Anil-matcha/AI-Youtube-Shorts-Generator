"""Project-library and job-control routes for Shorts Studio.

Rendering and persistence primitives stay in :mod:`web.app`; these handlers
only translate HTTP requests into those state-bound operations.  Resolving the
module lazily keeps route registration free of circular imports.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from web.models import BatchRequest, JobRequest, ProjectUpdate


router = APIRouter()


def _studio() -> Any:
    """Resolve the stateful app module only when a request is handled."""
    return importlib.import_module("web.app")


def _credentials(
    x_muapi_key: Optional[str],
    x_openai_key: Optional[str],
    x_gemini_key: Optional[str],
    x_llm_provider: Optional[str],
) -> Dict[str, str]:
    return _studio()._runtime_credentials_from_headers(
        x_muapi_key,
        x_openai_key,
        x_gemini_key,
        x_llm_provider,
    )


@router.post("/api/jobs")
def create_job(
    req: JobRequest,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    return _studio()._enqueue_job(req, _credentials(x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider))


@router.post("/api/factory/jobs", tags=["projects"])
def create_factory_job(
    req: JobRequest,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    """Queue one URL or uploaded file for a reviewable factory package."""
    return _studio()._enqueue_job(
        req,
        _credentials(x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider),
        factory_mode=True,
    )


@router.post("/api/jobs/batch")
def create_batch_jobs(
    req: BatchRequest,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    studio = _studio()
    credentials = _credentials(x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider)
    jobs = []
    defaults = req.model_dump()
    defaults.pop("urls", None)
    for url in req.urls:
        clean_url = str(url).strip()
        if len(clean_url) < 3:
            continue
        payload = {**defaults, "url": clean_url}
        jobs.append(studio._enqueue_job(JobRequest.model_validate(payload), credentials))
    if not jobs:
        raise HTTPException(400, "batch did not contain any usable URLs or file paths")
    return {"jobs": jobs}


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    should_terminate = False
    queued_future = None
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if job.get("status") in {"running", "queued"}:
            job["status"] = "cancelled"
            job["stage"] = "cancelled"
            job["message"] = "Cancellation requested"
            job["error"] = "Cancelled by user"
            studio._append_job_log(job, "cancelled", job["message"])
            studio._cancel_events.setdefault(job_id, threading.Event()).set()
            studio._persist_job_locked(job)
            should_terminate = True
            # A bounded executor may have accepted the task but not started
            # it yet. Cancel that future as well so a queued cancellation does
            # not unexpectedly begin rendering after the response returns.
            queued_future = studio._job_futures.get(job_id)
        snapshot = studio._job_snapshot(job)
    if queued_future is not None:
        if queued_future.cancel():
            # A future cancelled before its worker starts will never execute
            # the worker's normal ``finally`` block, so release its event and
            # bookkeeping here instead of retaining a dead queue entry.
            with studio._lock:
                studio._cancel_events.pop(job_id, None)
                studio._job_credentials.pop(job_id, None)
                if studio._job_futures.get(job_id) is queued_future:
                    studio._job_futures.pop(job_id, None)
    if should_terminate:
        terminated = studio._terminate_job_processes(job_id)
        snapshot["terminated_processes"] = terminated
    return snapshot


@router.get("/api/jobs")
def list_jobs(
    include_archived: bool = False,
    q: Optional[str] = Query(default=None, max_length=300),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100000),
) -> Dict[str, Any]:
    studio = _studio()

    def created_at_value(job: Dict[str, Any]) -> float:
        try:
            value = float(job.get("created_at") or 0.0)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return value if value == value and abs(value) != float("inf") else 0.0

    with studio._lock:
        jobs = [
            studio._job_snapshot(job)
            for job in sorted(
                (job for job in studio._jobs.values() if include_archived or not job.get("archived", False)),
                key=created_at_value,
                reverse=True,
            )
        ]
    search = str(q or "").strip().casefold()
    if search:
        jobs = [
            job
            for job in jobs
            if search in f"{job.get('name', '')} {job.get('id', '')} {job.get('request', {}).get('url', '')}".casefold()
        ]
    page = jobs[offset : offset + limit]
    return {
        "jobs": page,
        "total": len(jobs),
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if offset + limit < len(jobs) else None,
    }


@router.patch("/api/jobs/{job_id}")
def rename_job(job_id: str, update: ProjectUpdate) -> Dict[str, Any]:
    studio = _studio()
    name = " ".join(update.name.split())
    if not name:
        raise HTTPException(400, "project name cannot be blank")
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job["name"] = name
        studio._persist_job_locked(job)
        return studio._job_snapshot(job)


@router.post("/api/jobs/{job_id}/archive")
def archive_job(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job["archived"] = not bool(job.get("archived", False))
        studio._append_job_log(job, "project", "Archived" if job["archived"] else "Restored to library")
        studio._persist_job_locked(job)
        return studio._job_snapshot(job)


@router.post("/api/jobs/{job_id}/duplicate")
def duplicate_job(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        source = studio._jobs.get(job_id)
        if not source:
            raise HTTPException(404, "job not found")
        request = studio._dict_value(source.get("request"))
        source_name = source.get("name")
    try:
        copied_request = JobRequest.model_validate(request)
    except Exception as exc:
        raise HTTPException(400, f"project settings are invalid: {exc}") from exc
    new_id = uuid.uuid4().hex[:12]
    now = time.time()
    clone = {
        "id": new_id,
        "name": f"{source_name or 'Untitled project'} copy"[:80],
        "status": "draft",
        "stage": "draft",
        "message": "Duplicated project ready to run",
        "error": None,
        "result": None,
        "raw_shorts": [],
        "raw_transcript": {},
        "raw_source_video_url": None,
        "created_at": now,
        "updated_at": now,
        "archived": False,
        "logs": [{"t": now, "stage": "project", "message": "Duplicated from project " + job_id}],
        "request": copied_request.model_dump(),
    }
    with studio._lock:
        studio._jobs[new_id] = clone
        studio._cancel_events.pop(new_id, None)
        studio._persist_job_locked(clone)
        return studio._job_snapshot(clone)


def _trash_path(studio: Any, job_id: str) -> Path:
    if not studio._job_id_pattern.fullmatch(str(job_id)):
        raise ValueError("invalid job id")
    return studio._trash_dir / f"{job_id}.json"


@router.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    """Soft-delete a project record; media remains recoverable on disk."""
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if job.get("status") == "running":
            raise HTTPException(409, "cancel the running job before deleting it")
        studio._trash_dir.mkdir(parents=True, exist_ok=True)
        source = studio._job_path(job_id)
        target = _trash_path(studio, job_id)
        if source.is_file():
            os.replace(source, target)
        else:
            target.write_text(json.dumps(job, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        studio._jobs.pop(job_id, None)
        studio._cancel_events.pop(job_id, None)
        studio._job_store.delete(job_id)
    return {"status": "deleted", "job_id": job_id, "recoverable": True, "media_preserved": True}


@router.post("/api/jobs/{job_id}/restore")
def restore_job(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        if job_id in studio._jobs:
            raise HTTPException(409, "project is already in the library")
        path = _trash_path(studio, job_id)
        if not path.is_file():
            raise HTTPException(404, "deleted project not found")
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(500, f"could not restore project: {exc}") from exc
        if not isinstance(job, dict) or str(job.get("id")) != job_id:
            raise HTTPException(400, "deleted project record is invalid")
        studio._jobs[job_id] = job
        studio._persist_job_locked(job)
        try:
            path.unlink()
        except OSError:
            pass
        return studio._job_snapshot(job)


@router.post("/api/jobs/{job_id}/retry")
def retry_job(
    job_id: str,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        status = str(job.get("status") or "unknown")
        if status == "running":
            raise HTTPException(409, "project is already running")
        if status not in {"error", "cancelled", "interrupted", "draft"}:
            raise HTTPException(409, "only failed, cancelled, interrupted, or draft projects can be retried")
        request = studio._dict_value(job.get("request"))
    try:
        req = JobRequest.model_validate(request)
    except Exception as exc:
        raise HTTPException(400, f"saved project settings are invalid: {exc}") from exc
    studio._validate_mode_capabilities(req)
    studio._validate_local_paths(req)
    credentials = _credentials(x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider)
    if req.llm_provider:
        credentials["llm_provider"] = req.llm_provider
    elif credentials.get("llm_provider"):
        req.llm_provider = credentials["llm_provider"]
    if req.mode == "api" and not (credentials.get("muapi") or studio.MUAPI_API_KEY):
        raise HTTPException(400, "API mode needs a MuAPI API key. Enter it in Settings before retrying.")
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job["status"] = "running"
        job["stage"] = "queued"
        job["message"] = "Queued for retry"
        job["error"] = None
        job["result"] = None
        job["raw_shorts"] = []
        job["raw_transcript"] = {}
        job["raw_source_video_url"] = None
        job["logs"] = list(job.get("logs") or [])[-79:]
        studio._append_job_log(job, "queued", job["message"])
        studio._cancel_events[job_id] = threading.Event()
        if credentials:
            studio._job_credentials[job_id] = credentials
        studio._persist_job_locked(job)
        snapshot = studio._job_snapshot(job)
    studio._start_job_thread(job_id, req, credentials)
    return snapshot


def _validate_log_filters(studio: Any, job_id: Optional[str], level: Optional[str], stage: Optional[str]) -> None:
    if job_id and not studio._job_id_pattern.fullmatch(job_id):
        raise HTTPException(400, "invalid job id")
    if level and level.strip().lower() not in {"error", "warn", "running", "done", "project"}:
        raise HTTPException(400, "invalid log level")
    if stage and (len(stage) > 32 or not re.fullmatch(r"[A-Za-z0-9_.-]+", stage.strip())):
        raise HTTPException(400, "invalid log stage")


@router.get("/api/logs")
def list_logs(
    job_id: Optional[str] = Query(default=None, max_length=64),
    level: Optional[str] = Query(default=None, max_length=20),
    stage: Optional[str] = Query(default=None, max_length=32),
    q: Optional[str] = Query(default=None, max_length=300),
    limit: int = Query(default=250, ge=1, le=1000),
) -> Dict[str, Any]:
    studio = _studio()
    _validate_log_filters(studio, job_id, level, stage)
    with studio._lock:
        if job_id and job_id not in studio._jobs:
            raise HTTPException(404, "job not found")
        entries = studio._filter_log_entries_locked(job_id, level, stage, q)
    total = len(entries)
    return {"logs": entries[:limit], "count": min(total, limit), "total": total, "current_version": studio._APP_VERSION}


@router.get("/api/logs/download")
def download_logs(
    job_id: Optional[str] = Query(default=None, max_length=64),
    level: Optional[str] = Query(default=None, max_length=20),
    stage: Optional[str] = Query(default=None, max_length=32),
    q: Optional[str] = Query(default=None, max_length=300),
) -> PlainTextResponse:
    studio = _studio()
    _validate_log_filters(studio, job_id, level, stage)
    with studio._lock:
        if job_id and job_id not in studio._jobs:
            raise HTTPException(404, "job not found")
        entries = list(reversed(studio._filter_log_entries_locked(job_id, level, stage, q)))
    lines = [f"{entry['timestamp']} [{entry['project']}] [{entry['stage']}] {entry['message']}" for entry in entries]
    filename = f"shorts_{job_id}.log" if job_id else "shorts_studio.log"
    return PlainTextResponse(
        "\n".join(lines) + ("\n" if lines else ""),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/jobs/{job_id}/logs")
def download_job_logs(job_id: str) -> PlainTextResponse:
    studio = _studio()
    if not studio._job_id_pattern.fullmatch(job_id):
        raise HTTPException(400, "invalid job id")
    with studio._lock:
        if job_id not in studio._jobs:
            raise HTTPException(404, "job not found")
        entries = list(reversed(studio._log_entries_locked(job_id)))
    lines = [f"{entry['timestamp']} [{entry['stage']}] {entry['message']}" for entry in entries]
    return PlainTextResponse(
        "\n".join(lines) + ("\n" if lines else ""),
        headers={"Content-Disposition": f'attachment; filename="shorts_{job_id}.log"'},
    )
