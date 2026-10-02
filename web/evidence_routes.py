"""Bounded, explicitly selected local story evidence with cancel controls."""

from __future__ import annotations

import importlib
import re
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import Field, field_validator, model_validator

from web.models import StrictModel
from web.security import redact_structure
from web.story_evidence import MAX_DURATION, MAX_FRAMES, MAX_OUTPUT_BYTES, TIMEOUT_SECONDS, analyze_local, model_catalog

router = APIRouter(tags=["v2 foundation"])
_active: Dict[str, threading.Event] = {}
_slots = threading.BoundedSemaphore(1)


class EvidenceRequest(StrictModel):
    model_config = {"allow_inf_nan": False, "extra": "forbid"}
    ocr_model: Optional[Literal["tesseract"]] = None
    audio_model: Optional[Literal["silero-vad"]] = None
    language: str = Field(default="eng", min_length=3, max_length=32)
    start_time: float = Field(default=0, ge=0, le=86400)
    duration_seconds: float = Field(default=60, ge=1, le=MAX_DURATION)
    max_frames: int = Field(default=4, ge=1, le=MAX_FRAMES)

    @field_validator("language")
    @classmethod
    def language_code(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z]{3}(?:\+[a-z]{3}){0,3}", value):
            raise ValueError("language must be local Tesseract language codes such as eng or eng+fra")
        return value

    @model_validator(mode="after")
    def selected_models(self) -> "EvidenceRequest":
        if not self.ocr_model and not self.audio_model:
            raise ValueError("select at least one local evidence model")
        return self


def _studio() -> Any:
    return importlib.import_module("web.app")


@router.get("/api/story/models")
def story_models() -> Dict[str, Any]:
    return model_catalog()


@router.get("/api/jobs/{job_id}/story/analyze")
def get_evidence(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
        return {"evidence": redact_structure(job.get("story_evidence")), "running": job_id in _active}


@router.delete("/api/jobs/{job_id}/story/analyze")
def clear_evidence(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
        event = _active.get(job_id)
        if event:
            event.set()
            return {"status": "cancelling"}
        job.pop("story_evidence", None)
        studio._persist_job_locked(job)
        return {"status": "cleared"}


@router.post("/api/jobs/{job_id}/story/analyze")
def analyze_evidence(job_id: str, request: EvidenceRequest) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
        if job.get("status") != "done":
            raise HTTPException(409, {"error": "complete the project before analyzing evidence", "code": "job_not_ready"})
        source = studio._job_source_path(job, job.get("raw_source_video_url"))
        if source is None:
            raise HTTPException(409, {"error": "local source media is required", "code": "local_source_required"})
        available = {item["id"] for item in model_catalog()["models"] if item["available"]}
        if any(model and model not in available for model in (request.ocr_model, request.audio_model)):
            raise HTTPException(409, {"error": "selected local model is unavailable", "code": "evidence_model_unavailable"})
        source_signature = (source.stat().st_size, source.stat().st_mtime_ns)
        if not _slots.acquire(blocking=False):
            raise HTTPException(409, {"error": "another evidence analysis is running", "code": "evidence_busy"})
        event = threading.Event()
        _active[job_id] = event
    deadline = time.monotonic() + TIMEOUT_SECONDS

    def check() -> None:
        if event.is_set() or studio._job_cancelled(job_id):
            raise RuntimeError("Evidence analysis cancelled")
        if time.monotonic() >= deadline:
            raise RuntimeError("Evidence analysis timed out")

    def run(args: list[str]) -> bytes:
        check()
        # Spool bounded output to disk so a dependency cannot exhaust memory.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(args, stdout=output, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            studio._register_job_process(job_id, process)
            try:
                while process.poll() is None:
                    check()
                    if output.tell() > MAX_OUTPUT_BYTES:
                        raise RuntimeError("Evidence output exceeded its budget")
                    try:
                        process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
                if process.returncode:
                    raise RuntimeError("Local evidence command failed; check installed models, language data, and source audio")
                output.seek(0)
                payload = output.read(MAX_OUTPUT_BYTES + 1)
                if len(payload) > MAX_OUTPUT_BYTES:
                    raise RuntimeError("Evidence output exceeded its budget")
                return payload
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
                studio._unregister_job_process(job_id, process)

    try:
        while not studio._media_slots.acquire(timeout=0.25):
            check()
        try:
            evidence = analyze_local(source, request.model_dump(), run, check)
        finally:
            studio._media_slots.release()
        check()
        with studio._lock:
            check()
            if studio._jobs.get(job_id) is not job or job.get("status") != "done":
                raise HTTPException(409, {"error": "project changed during analysis", "code": "evidence_stale"})
            if source_signature != (source.stat().st_size, source.stat().st_mtime_ns):
                raise HTTPException(409, {"error": "source changed during analysis", "code": "evidence_stale"})
            evidence["analyzed_at"] = time.time()
            job["story_evidence"] = redact_structure(evidence, studio._job_credentials.get(job_id))
            studio._append_job_log(job, "evidence", "Local OCR/audio evidence updated")
            studio._persist_job_locked(job)
            return {"evidence": job["story_evidence"], "running": False}
    except (RuntimeError, OSError, ImportError, ValueError) as exc:
        # Dependency errors can contain source paths or credentials. The
        # bounded known messages are sufficient for actionable UI feedback.
        message = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith(("Evidence ", "Local evidence ", "Tesseract ", "Audio ", "OCR ", "FFmpeg ")) else "Local evidence analysis failed"
        code = "evidence_cancelled" if event.is_set() or studio._shutdown_requested.is_set() else "evidence_failed"
        raise HTTPException(409, {"error": message[:200], "code": code}) from exc
    finally:
        with studio._lock:
            _active.pop(job_id, None)
        _slots.release()
