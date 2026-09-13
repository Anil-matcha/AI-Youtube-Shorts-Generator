"""Web UI for the YouTube Shorts generator.

    python -m web.app
    # then open http://127.0.0.1:7860
"""
from __future__ import annotations

import json
import hashlib
import io
import math
import os
import re
import shutil
import subprocess
from array import array
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import File, FastAPI, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shorts_generator import generate_shorts  # noqa: E402
from shorts_generator.config import (  # noqa: E402
    GEMINI_API_KEY,
    LLM_PROVIDER,
    LOCAL_BURN_CAPTIONS,
    LOCAL_HEURISTIC_FALLBACK,
    LOCAL_OUTPUT_DIR,
    LOCAL_WHISPER_DEVICE,
    LOCAL_WHISPER_MODEL,
    MUAPI_API_KEY,
    OPENAI_API_KEY,
    gpu_status,
    runtime_credentials,
)

app = FastAPI(title="Shorts Studio", version="0.9.2")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_cancel_events: Dict[str, threading.Event] = {}
# UI-supplied credentials live only for the lifetime of an active job.  They
# are never included in the persisted request, snapshots, metadata, or logs.
_job_credentials: Dict[str, Dict[str, str]] = {}
_job_id_pattern = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_max_credential_length = 4096


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer without letting a malformed .env break startup."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(1, value)


_max_concurrent_jobs = _positive_int_env("SHORTS_MAX_CONCURRENT_JOBS", 2)
_job_slots = threading.Semaphore(_max_concurrent_jobs)
_output_root = Path(LOCAL_OUTPUT_DIR).expanduser().resolve()
_jobs_dir = _output_root / "jobs"
_uploads_dir = _output_root / "uploads"
_trash_dir = _output_root / ".trash"
_setup_state_path = _output_root / "studio_state.json"
_allowed_upload_extensions = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}
_max_upload_mb = _positive_int_env("SHORTS_MAX_UPLOAD_MB", 2048)
_max_upload_bytes = _max_upload_mb * 1024 * 1024
_auto_resume = os.getenv("SHORTS_AUTO_RESUME", "true").strip().lower() in {"1", "true", "yes", "on"}

_APP_VERSION = os.getenv("SHORTS_STUDIO_VERSION", "0.9.2").strip().lstrip("v") or "0.9.2"
_GITHUB_REPO = "wiifhub/AI-Youtube-Shorts-Generator"
_update_lock = threading.Lock()
_update_state: Dict[str, Any] = {
    "status": "idle",
    "current_version": _APP_VERSION,
    "latest_version": None,
    "progress": 0,
    "total": 0,
    "message": "",
    "error": None,
}


def _nonnegative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


_min_free_gb = _nonnegative_float_env("SHORTS_MIN_FREE_GB", 0.5)


def _safe_transcript_duration(transcript: Any) -> float:
    """Read a usable duration from persisted/API transcript data."""
    if not isinstance(transcript, dict):
        return 0.0
    try:
        duration = float(transcript.get("duration") or 0.0)
    except (TypeError, ValueError, OverflowError):
        duration = 0.0
    if math.isfinite(duration) and duration > 0:
        return duration
    ends = []
    raw_segments = transcript.get("segments")
    segments = raw_segments if isinstance(raw_segments, (list, tuple)) else []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        try:
            end = float(segment.get("end"))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(end) and end > 0:
            ends.append(end)
    return max(ends, default=0.0)


def _dict_items(value: Any) -> List[Dict[str, Any]]:
    """Return only object entries from persisted/API list data."""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict_value(value: Any) -> Dict[str, Any]:
    """Return a shallow object copy, or an empty object for corrupt state."""
    return dict(value) if isinstance(value, dict) else {}


def _job_media_path(job: Dict[str, Any], value: Any) -> Optional[Path]:
    """Resolve a generated media path without allowing persisted path escapes.

    Custom save folders are supported, so the job's own ``output_dir`` is the
    trust boundary rather than the global ``output/jobs`` directory.  A stale
    or hand-edited job record must not turn the clip/thumbnail endpoints into
    arbitrary file readers.
    """
    if not value or str(value).startswith("http"):
        return None
    try:
        candidate = Path(str(value)).expanduser().resolve()
        output_dir = Path(
            str(job.get("output_dir") or (_jobs_dir / str(job.get("id") or "")))
        ).expanduser().resolve()
        candidate.relative_to(output_dir)
    except (OSError, RuntimeError, ValueError, TypeError):
        return None
    return candidate


def _job_path(job_id: str) -> Path:
    safe_id = str(job_id)
    if not _job_id_pattern.fullmatch(safe_id):
        raise ValueError("invalid job id")
    return _jobs_dir / f"{safe_id}.json"


def _persist_job_locked(job: Dict[str, Any]) -> None:
    """Atomically persist one job; callers must hold ``_lock``."""
    _jobs_dir.mkdir(parents=True, exist_ok=True)
    job["updated_at"] = time.time()
    path = _job_path(str(job["id"]))
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(job, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_persisted_jobs() -> None:
    """Restore recent jobs and mark in-flight work interrupted by a restart."""
    _jobs_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for path in _jobs_dir.glob("*.json"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(files, key=lambda item: item[0], reverse=True):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(job, dict) or not job.get("id"):
            continue
        job_id = str(job["id"])
        if not _job_id_pattern.fullmatch(job_id):
            continue
        job["id"] = job_id
        if not isinstance(job.get("logs"), list):
            job["logs"] = []
        try:
            created_at = float(job.get("created_at") or path.stat().st_mtime)
            if not math.isfinite(created_at):
                raise ValueError("created_at must be finite")
            job["created_at"] = created_at
        except (OSError, TypeError, ValueError, OverflowError):
            job["created_at"] = time.time()
        job.setdefault("status", "error")
        job.setdefault("stage", "unknown")
        job.setdefault("message", "Recovered project")
        persisted_request = job.get("request") if isinstance(job.get("request"), dict) else {}
        job.setdefault("name", str(persisted_request.get("url") or job_id))
        job.setdefault("archived", False)
        job.setdefault("updated_at", job.get("created_at"))
        if job.get("status") == "running":
            message = "Interrupted when Shorts Studio stopped; it can be resumed."
            job["status"] = "interrupted"
            job["stage"] = "interrupted"
            job["message"] = message
            job["error"] = None
            job["logs"] = list(job["logs"])[-79:]
            job["logs"].append({"t": time.time(), "stage": "interrupted", "message": message})
        _jobs[job_id] = job


_load_persisted_jobs()


class JobRequest(BaseModel):
    model_config = {"allow_inf_nan": False}
    url: str = Field(..., min_length=3)
    mode: str = "local"
    num_clips: int = Field(3, ge=1, le=12)
    aspect_ratio: str = "9:16"
    download_format: str = "720"
    language: Optional[str] = None
    caption_style: str = "bold"
    remove_silence: bool = False
    normalize_audio: bool = False
    denoise_audio: bool = False
    remove_filler_words: bool = False
    caption_position: str = "bottom"
    caption_font: str = "Arial"
    caption_size: int = Field(0, ge=0, le=120)
    caption_color: Optional[str] = None
    focus: str = "balanced"
    background_music: Optional[str] = None
    watermark: Optional[str] = None
    auto_reframe: bool = True
    crop_position: float = Field(0.5, ge=0.0, le=1.0)
    fit_mode: str = "crop"
    zoom: float = Field(1.0, ge=0.5, le=1.5)
    intro: Optional[str] = None
    outro: Optional[str] = None
    jump_cuts: bool = False
    layout: str = "single"
    whisper_model: Optional[str] = None
    whisper_device: Optional[str] = None
    output_height: int = Field(1920, ge=0, le=4320)
    save_folder: Optional[str] = None
    llm_provider: Optional[str] = None


class BatchRequest(JobRequest):
    url: str = ""
    urls: List[str] = Field(..., min_length=1, max_length=50)


class ClipUpdate(BaseModel):
    model_config = {"allow_inf_nan": False}
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
    caption_style: Optional[str] = None
    caption_position: str = "bottom"
    caption_font: str = "Arial"
    caption_size: int = Field(0, ge=0, le=120)
    caption_color: Optional[str] = None
    crop_position: float = Field(0.5, ge=0.0, le=1.0)
    zoom: float = Field(1.0, ge=0.5, le=1.5)
    fit_mode: str = "crop"
    layout: str = "single"
    output_height: int = Field(1920, ge=0, le=4320)


class ProjectUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class OpenFolderRequest(BaseModel):
    job_id: Optional[str] = None


class SetupStateUpdate(BaseModel):
    dismissed: bool = True


_log_secret_pattern = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{8,}|mu_[A-Za-z0-9_-]{8,})\b")
_log_level_stages = {
    "error": {"error"},
    "warn": {"warning", "warn"},
    "done": {"done"},
    "project": {"project"},
    "running": {
        "queued",
        "download",
        "transcribe",
        "rank",
        "render",
        "caption",
        "audio",
        "frame",
        "thumbnail",
        "metadata",
        "upload",
    },
}


def _redact_log_text(value: Any, job_id: Optional[str] = None) -> str:
    """Keep credentials out of the log API even if a dependency echoes one."""
    text = str(value or "")
    text = _log_secret_pattern.sub("[redacted]", text)
    if job_id:
        credentials = _job_credentials.get(job_id) or {}
        for secret in credentials.values():
            if isinstance(secret, str) and len(secret) >= 4:
                text = text.replace(secret, "[redacted]")
    return text[:4000]


def _normalise_log_entry(job_id: str, project: str, entry: Any, index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    try:
        timestamp = float(entry.get("t") or time.time())
        if not math.isfinite(timestamp):
            raise ValueError
        # datetime.fromtimestamp can reject very large, otherwise-finite values.
        stamp = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        timestamp = time.time()
        stamp = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds")
    stage = str(entry.get("stage") or "info").strip()[:32] or "info"
    return {
        "id": f"{job_id}:{index}:{timestamp:.6f}",
        "job_id": job_id,
        "project": str(project or "Untitled project")[:160],
        "t": timestamp,
        "timestamp": stamp,
        "stage": stage,
        "message": _redact_log_text(entry.get("message"), job_id),
    }


def _log_entries_locked(job_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return safe, normalized log entries. The caller must hold ``_lock``."""
    jobs = [_jobs.get(job_id)] if job_id else list(_jobs.values())
    entries: List[Dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        current_id = str(job.get("id") or "")
        request = job.get("request") if isinstance(job.get("request"), dict) else {}
        project = str(job.get("name") or request.get("url") or current_id or "Untitled project")
        logs = job.get("logs") if isinstance(job.get("logs"), list) else []
        for index, raw in enumerate(logs):
            normalised = _normalise_log_entry(current_id, project, raw, index)
            if normalised:
                entries.append(normalised)
    entries.sort(key=lambda item: (item.get("t", 0), item.get("id", "")), reverse=True)
    return entries


def _filter_log_entries_locked(
    job_id: Optional[str] = None,
    level: Optional[str] = None,
    stage: Optional[str] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    entries = _log_entries_locked(job_id)
    wanted_level = str(level or "").strip().lower()
    wanted_stage = str(stage or "").strip().lower()
    search = str(query or "").strip().casefold()
    if wanted_stage:
        entries = [entry for entry in entries if entry["stage"].casefold() == wanted_stage]
    elif wanted_level:
        allowed = _log_level_stages.get(wanted_level)
        if allowed is not None:
            entries = [entry for entry in entries if entry["stage"].casefold() in allowed]
    if search:
        entries = [
            entry
            for entry in entries
            if search in f"{entry['project']} {entry['stage']} {entry['message']}".casefold()
        ]
    return entries


def _job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    status = str(job.get("status") or "unknown")
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    return {
        "id": str(job.get("id") or ""),
        "status": status,
        "stage": str(job.get("stage") or "unknown"),
        "message": str(job.get("message") or ""),
        "logs": [
            safe
            for safe in (
                {
                    **entry,
                    "stage": str(entry.get("stage") or "info")[:32],
                    "message": _redact_log_text(entry.get("message"), str(job.get("id") or "")),
                }
                for entry in ((job.get("logs") if isinstance(job.get("logs"), list) else [])[-80:])
                if isinstance(entry, dict)
            )
        ],
        "error": job.get("error"),
        "result": job.get("result"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at", job.get("created_at")),
        "name": str(job.get("name") or request.get("url") or job.get("id") or "Untitled project"),
        "archived": bool(job.get("archived", False)),
        "can_retry": status in {"error", "cancelled", "interrupted", "draft"} and bool(request.get("url")),
        "request": request,
        "output_dir": job.get("output_dir"),
    }


def _append_job_log(job: Dict[str, Any], stage: str, message: Any) -> None:
    """Append a bounded log entry even when an older job record is malformed."""
    logs = job.get("logs")
    if not isinstance(logs, list):
        logs = []
        job["logs"] = logs
    job_id = str(job.get("id") or "")
    logs.append({"t": time.time(), "stage": str(stage or "info")[:32], "message": _redact_log_text(message, job_id)})
    if len(logs) > 80:
        del logs[:-80]


def _creator_metadata(short: Dict[str, Any]) -> Dict[str, str]:
    """Create ready-to-paste social metadata without another paid LLM call."""
    title = str(short.get("title") or "Untitled highlight").strip()
    hook = str(short.get("hook_sentence") or title).strip()
    reason = str(short.get("virality_reason") or "").strip()
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}", f"{title} {hook}")
    tags = ["#Shorts", "#YouTubeShorts"]
    for word in words:
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", word)
        if tag.lower() not in {item.lower() for item in tags} and len(tag) <= 22:
            tags.append(tag)
        if len(tags) >= 6:
            break
    description = hook
    if reason:
        description += f"\n\n{reason}"
    description += "\n\n#Shorts #YouTubeShorts"
    return {
        "title": title[:100],
        "description": description[:5000],
        "hashtags": " ".join(tags),
        "thumbnail_text": hook[:70],
    }


def _public_shorts(shorts: List[Dict], job_id: str) -> List[Dict]:
    out = []
    for i, s in enumerate(_dict_items(shorts)):
        item = dict(s)
        clip = item.get("clip_url") or ""
        if clip and not str(clip).startswith("http"):
            item["play_url"] = f"/api/jobs/{job_id}/clip/{i}"
            item["local_path"] = clip
        else:
            item["play_url"] = clip
        thumbnail = item.get("thumbnail_path") or ""
        if thumbnail and not str(thumbnail).startswith("http"):
            item["thumbnail_url"] = f"/api/jobs/{job_id}/thumbnail/{i}"
        item["creator_metadata"] = _creator_metadata(item)
        out.append(item)
    return out


def _cleanup_job_temporary_files(job: Dict[str, Any]) -> None:
    """Remove only renderer scratch files, never completed/user media."""
    output_dir = job.get("output_dir")
    if not output_dir:
        return
    try:
        root = Path(str(output_dir)).expanduser().resolve()
        if not root.is_dir():
            return
        scratch_suffixes = (
            ".part", ".cut.mp4", ".base.mp4", ".render.mp4", ".audio.mp4",
            ".jump.mp4", ".extras.mp4", ".branded.mp4", ".silent.mp4",
            ".regenerate.mp4",
        )
        for item in root.rglob("*"):
            if not item.is_file() or not item.name.endswith(scratch_suffixes):
                continue
            try:
                item.unlink()
            except OSError:
                continue
    except (OSError, RuntimeError, TypeError):
        return


def _clean_runtime_credential(value: Optional[str], label: str) -> Optional[str]:
    """Normalize a UI credential without ever logging or persisting it."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if len(cleaned) > _max_credential_length:
        raise HTTPException(400, f"{label} is too long")
    if any(char in cleaned for char in "\r\n"):
        raise HTTPException(400, f"{label} contains invalid characters")
    return cleaned


def _runtime_credentials_from_headers(
    muapi_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    llm_provider: Optional[str] = None,
) -> Dict[str, str]:
    """Build a non-persistent credential map from request headers."""
    values: Dict[str, str] = {}
    for key, value, label in (
        ("muapi", muapi_api_key, "MuAPI API key"),
        ("openai", openai_api_key, "OpenAI API key"),
        ("gemini", gemini_api_key, "Gemini API key"),
    ):
        cleaned = _clean_runtime_credential(value, label)
        if cleaned:
            values[key] = cleaned
    if llm_provider is not None:
        provider = str(llm_provider).strip().lower()
        if provider not in {"openai", "gemini"}:
            raise HTTPException(400, "LLM provider must be openai or gemini")
        values["llm_provider"] = provider
    return values


def _start_job_thread(
    job_id: str,
    req: JobRequest,
    credentials: Optional[Dict[str, str]] = None,
) -> None:
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, req, dict(credentials or {})),
        daemon=True,
    )
    thread.start()


def _run_job(
    job_id: str,
    req: JobRequest,
    credentials: Optional[Dict[str, str]] = None,
) -> None:
    slot_acquired = False

    def progress(stage: str, message: str) -> None:
        with _lock:
            job = _jobs[job_id]
            if _cancel_events.get(job_id, threading.Event()).is_set():
                raise RuntimeError("Job cancelled")
            job["stage"] = stage
            job["message"] = message
            _append_job_log(job, stage, message)
            _persist_job_locked(job)

    try:
        _job_slots.acquire()
        slot_acquired = True
        progress("queued", "Starting pipeline...")
        if req.save_folder:
            base = Path(req.save_folder).expanduser().resolve()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            source_tag = re.sub(r"[^A-Za-z0-9_-]+", "_", req.url.rsplit("/", 1)[-1])[:32] or "source"
            job_output_dir = base / f"{stamp}_shorts_{source_tag}_{job_id[:8]}"
        else:
            job_output_dir = _jobs_dir / job_id
        job_output_dir.mkdir(parents=True, exist_ok=True)
        with _lock:
            _jobs[job_id]["output_dir"] = str(job_output_dir)
            _persist_job_locked(_jobs[job_id])
        supplied = dict(credentials or {})
        with runtime_credentials(
            muapi_api_key=supplied.get("muapi"),
            openai_api_key=supplied.get("openai"),
            gemini_api_key=supplied.get("gemini"),
            llm_provider=supplied.get("llm_provider") or req.llm_provider,
        ):
            result = generate_shorts(
                youtube_url=req.url.strip(),
                num_clips=req.num_clips,
                aspect_ratio=req.aspect_ratio,
                download_format=req.download_format,
                language=req.language or None,
                mode=req.mode,
                progress=progress,
                output_dir=str(job_output_dir) if req.mode == "local" else None,
                caption_style=req.caption_style,
                remove_silence=req.remove_silence,
                normalize_audio=req.normalize_audio,
                denoise_audio=req.denoise_audio,
                remove_filler_words=req.remove_filler_words,
                caption_position=req.caption_position,
                caption_font=req.caption_font,
                caption_size=req.caption_size,
                caption_color=req.caption_color,
                focus=req.focus,
                background_music=req.background_music,
                watermark=req.watermark,
                auto_reframe=req.auto_reframe,
                crop_position=req.crop_position,
                fit_mode=req.fit_mode,
                zoom=req.zoom,
                intro=req.intro,
                outro=req.outro,
                jump_cuts=req.jump_cuts,
                layout=req.layout,
                whisper_model=req.whisper_model,
                whisper_device=req.whisper_device,
                output_height=req.output_height,
                llm_provider=req.llm_provider,
            )
        if not isinstance(result, dict):
            raise RuntimeError("pipeline returned an invalid result object")
        transcript = _dict_value(result.get("transcript"))
        raw_shorts = _dict_items(result.get("shorts"))
        highlights = _dict_items(result.get("highlights"))
        public = {
            "mode": result.get("mode"),
            "source_video_url": result.get("source_video_url"),
            "highlights": highlights,
            "shorts": _public_shorts(raw_shorts, job_id),
            "transcript_duration": _safe_transcript_duration(transcript),
            "segment_count": len(_dict_items(transcript.get("segments"))),
        }
        # Keep a portable manifest beside the rendered media, including when
        # the user selected a custom Save folder instead of output/jobs.
        try:
            with _lock:
                job_state = _jobs[job_id]
                created_at = job_state.get("created_at")
                request_snapshot = dict(job_state.get("request") or {})
            metadata = {
                "job_id": job_id,
                "created_at": created_at,
                "output_dir": str(job_output_dir),
                "request": request_snapshot,
                "result": public,
                "transcript": transcript,
            }
            (job_output_dir / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            progress("metadata", f"Could not write metadata.json: {exc}")
        with _lock:
            job = _jobs[job_id]
            if job.get("status") == "cancelled":
                _cleanup_job_temporary_files(job)
                return
            job["status"] = "done"
            job["stage"] = "done"
            job["message"] = f"Rendered {len(public['shorts'])} shorts"
            job["result"] = public
            job["raw_shorts"] = raw_shorts
            job["raw_transcript"] = transcript
            job["raw_source_video_url"] = result.get("source_video_url")
            _append_job_log(job, "done", job["message"])
            _persist_job_locked(job)
    except Exception as exc:
        with _lock:
            job = _jobs.get(job_id)
            if not job:
                return
            if job.get("status") == "cancelled":
                _cleanup_job_temporary_files(job)
                return
            job["status"] = "error"
            job["stage"] = "error"
            job["message"] = str(exc)
            job["error"] = str(exc)
            _append_job_log(job, "error", str(exc))
            _persist_job_locked(job)
            _cleanup_job_temporary_files(job)
    finally:
        if slot_acquired:
            _job_slots.release()
        with _lock:
            _cancel_events.pop(job_id, None)
            _job_credentials.pop(job_id, None)


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


def _enqueue_job(
    req: JobRequest,
    credentials: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if req.mode not in ("api", "local"):
        raise HTTPException(400, "mode must be api or local")
    if not req.url or not req.url.strip():
        raise HTTPException(400, "url/path cannot be blank")
    if req.llm_provider is not None:
        provider = str(req.llm_provider).strip().lower()
        if provider not in {"openai", "gemini"}:
            raise HTTPException(400, "LLM provider must be openai or gemini")
        req.llm_provider = provider
    supplied_credentials = dict(credentials or {})
    # The JSON field is the durable project setting; accept the header as a
    # convenience for API clients that only send session credentials.  When
    # both are present, the explicit request field wins and the runtime map is
    # aligned with what will be persisted for retries/resume.
    header_provider = supplied_credentials.get("llm_provider")
    if req.llm_provider is None and header_provider:
        req.llm_provider = header_provider
    elif req.llm_provider is not None:
        supplied_credentials["llm_provider"] = req.llm_provider
    if req.mode == "api" and not (supplied_credentials.get("muapi") or MUAPI_API_KEY):
        raise HTTPException(
            400,
            "API mode needs a MuAPI API key. Enter it in Settings or configure MUAPI_API_KEY in .env.",
        )
    try:
        free_gb = shutil.disk_usage(_output_root).free / (1024 ** 3)
    except OSError:
        free_gb = 0.0
    if _min_free_gb and free_gb < _min_free_gb:
        raise HTTPException(507, f"not enough free disk space ({free_gb:.2f} GB available; {_min_free_gb:.2f} GB required)")
    job_id = uuid.uuid4().hex[:12]
    default_name = re.sub(r"[^A-Za-z0-9 _-]+", " ", req.url.rsplit("/", 1)[-1]).strip()
    default_name = " ".join(default_name.split())[:80] or "Untitled project"
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "name": default_name,
            "status": "running",
            "stage": "queued",
            "message": "Queued",
            "logs": [],
            "error": None,
            "result": None,
            "raw_shorts": [],
            "raw_transcript": {},
            "raw_source_video_url": None,
            "created_at": time.time(),
            "updated_at": time.time(),
            "archived": False,
            "request": {
                "url": req.url.strip(),
                "mode": req.mode,
                "num_clips": req.num_clips,
                "aspect_ratio": req.aspect_ratio,
                "download_format": req.download_format,
                "language": req.language,
                "caption_style": req.caption_style,
                "remove_silence": req.remove_silence,
                "normalize_audio": req.normalize_audio,
                "denoise_audio": req.denoise_audio,
                "remove_filler_words": req.remove_filler_words,
                "caption_position": req.caption_position,
                "caption_font": req.caption_font,
                "caption_size": req.caption_size,
                "caption_color": req.caption_color,
                "focus": req.focus,
                "background_music": req.background_music,
                "watermark": req.watermark,
                "auto_reframe": req.auto_reframe,
                "crop_position": req.crop_position,
                "fit_mode": req.fit_mode,
                "zoom": req.zoom,
                "intro": req.intro,
                "outro": req.outro,
                "jump_cuts": req.jump_cuts,
                "layout": req.layout,
                "whisper_model": req.whisper_model,
                "whisper_device": req.whisper_device,
                "output_height": req.output_height,
                "save_folder": req.save_folder,
                "llm_provider": req.llm_provider,
            },
        }
        _cancel_events[job_id] = threading.Event()
        if supplied_credentials:
            _job_credentials[job_id] = supplied_credentials
        _persist_job_locked(_jobs[job_id])
    _start_job_thread(job_id, req, supplied_credentials)
    with _lock:
        return _job_snapshot(_jobs[job_id])


def _resume_interrupted_jobs() -> None:
    pending: List[tuple[str, JobRequest]] = []
    with _lock:
        for job_id, job in list(_jobs.items()):
            if job.get("status") != "interrupted":
                continue
            request = _dict_value(job.get("request"))
            try:
                req = JobRequest.model_validate(request)
            except Exception as exc:
                job["status"] = "error"
                job["stage"] = "error"
                job["message"] = f"Saved project settings are invalid: {exc}"
                job["error"] = job["message"]
                _append_job_log(job, "error", job["message"])
                _persist_job_locked(job)
                continue
            job["status"] = "running"
            job["stage"] = "queued"
            job["message"] = "Resuming after the previous Shorts Studio session."
            job["error"] = None
            job["logs"] = list(job.get("logs") or [])[-79:]
            _append_job_log(job, "queued", job["message"])
            _cancel_events[job_id] = threading.Event()
            _persist_job_locked(job)
            pending.append((job_id, req))
    for job_id, req in pending:
        _start_job_thread(job_id, req)


@app.on_event("startup")
async def resume_interrupted_jobs() -> None:
    if _auto_resume:
        threading.Thread(target=_resume_interrupted_jobs, name="shorts-studio-resume", daemon=True).start()


@app.post("/api/jobs")
def create_job(
    req: JobRequest,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    credentials = _runtime_credentials_from_headers(
        x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider
    )
    return _enqueue_job(req, credentials)


@app.post("/api/jobs/batch")
def create_batch_jobs(
    req: BatchRequest,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    credentials = _runtime_credentials_from_headers(
        x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider
    )
    jobs = []
    for url in req.urls:
        clean_url = url.strip()
        if len(clean_url) < 3:
            continue
        item = JobRequest(
            url=clean_url,
            mode=req.mode,
            num_clips=req.num_clips,
            aspect_ratio=req.aspect_ratio,
            download_format=req.download_format,
            language=req.language,
            caption_style=req.caption_style,
            remove_silence=req.remove_silence,
            normalize_audio=req.normalize_audio,
            denoise_audio=req.denoise_audio,
            remove_filler_words=req.remove_filler_words,
            caption_position=req.caption_position,
            caption_font=req.caption_font,
            caption_size=req.caption_size,
            caption_color=req.caption_color,
            focus=req.focus,
            background_music=req.background_music,
            watermark=req.watermark,
            auto_reframe=req.auto_reframe,
            crop_position=req.crop_position,
            fit_mode=req.fit_mode,
            zoom=req.zoom,
            intro=req.intro,
            outro=req.outro,
            jump_cuts=req.jump_cuts,
            layout=req.layout,
            whisper_model=req.whisper_model,
            whisper_device=req.whisper_device,
            output_height=req.output_height,
            save_folder=req.save_folder,
            llm_provider=req.llm_provider,
        )
        jobs.append(_enqueue_job(item, credentials))
    if not jobs:
        raise HTTPException(400, "batch did not contain any usable URLs or file paths")
    return {"jobs": jobs}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if job.get("status") == "running":
            job["status"] = "cancelled"
            job["stage"] = "cancelled"
            job["message"] = "Cancellation requested"
            job["error"] = "Cancelled by user"
            _append_job_log(job, "cancelled", job["message"])
            _cancel_events.setdefault(job_id, threading.Event()).set()
            _persist_job_locked(job)
        return _job_snapshot(job)


@app.get("/api/jobs")
def list_jobs(include_archived: bool = False) -> Dict[str, Any]:
    def created_at_value(job: Dict[str, Any]) -> float:
        try:
            value = float(job.get("created_at") or 0.0)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    with _lock:
        jobs = [
            _job_snapshot(j)
            for j in sorted(
                (j for j in _jobs.values() if include_archived or not j.get("archived", False)),
                key=created_at_value,
                reverse=True,
            )
        ]
    return {"jobs": jobs[:20]}


@app.patch("/api/jobs/{job_id}")
def rename_job(job_id: str, update: ProjectUpdate) -> Dict[str, Any]:
    name = " ".join(update.name.split())
    if not name:
        raise HTTPException(400, "project name cannot be blank")
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job["name"] = name
        _persist_job_locked(job)
        return _job_snapshot(job)


@app.post("/api/jobs/{job_id}/archive")
def archive_job(job_id: str) -> Dict[str, Any]:
    """Toggle archive state without touching rendered media."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        job["archived"] = not bool(job.get("archived", False))
        _append_job_log(job, "project", "Archived" if job["archived"] else "Restored to library")
        _persist_job_locked(job)
        return _job_snapshot(job)


@app.post("/api/jobs/{job_id}/duplicate")
def duplicate_job(job_id: str) -> Dict[str, Any]:
    """Create a clean draft with the source settings of an existing project."""
    with _lock:
        source = _jobs.get(job_id)
        if not source:
            raise HTTPException(404, "job not found")
        request = _dict_value(source.get("request"))
    try:
        copied_request = JobRequest.model_validate(request)
    except Exception as exc:
        raise HTTPException(400, f"project settings are invalid: {exc}") from exc
    new_id = uuid.uuid4().hex[:12]
    name = f"{source.get('name') or 'Untitled project'} copy"
    clone = {
        "id": new_id,
        "name": name[:80],
        "status": "draft",
        "stage": "draft",
        "message": "Duplicated project ready to run",
        "error": None,
        "result": None,
        "raw_shorts": [],
        "raw_transcript": {},
        "raw_source_video_url": None,
        "created_at": time.time(),
        "updated_at": time.time(),
        "archived": False,
        "logs": [{"t": time.time(), "stage": "project", "message": "Duplicated from project " + job_id}],
        "request": copied_request.model_dump(),
    }
    with _lock:
        _jobs[new_id] = clone
        _cancel_events.pop(new_id, None)
        _persist_job_locked(clone)
        return _job_snapshot(clone)


def _trash_path(job_id: str) -> Path:
    if not _job_id_pattern.fullmatch(str(job_id)):
        raise ValueError("invalid job id")
    return _trash_dir / f"{job_id}.json"


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    """Soft-delete a project record; media remains recoverable on disk."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if job.get("status") == "running":
            raise HTTPException(409, "cancel the running job before deleting it")
        _trash_dir.mkdir(parents=True, exist_ok=True)
        source = _job_path(job_id)
        target = _trash_path(job_id)
        if source.is_file():
            os.replace(source, target)
        else:
            target.write_text(json.dumps(job, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        _jobs.pop(job_id, None)
        _cancel_events.pop(job_id, None)
    return {"status": "deleted", "job_id": job_id, "recoverable": True, "media_preserved": True}


@app.post("/api/jobs/{job_id}/restore")
def restore_job(job_id: str) -> Dict[str, Any]:
    with _lock:
        if job_id in _jobs:
            raise HTTPException(409, "project is already in the library")
        path = _trash_path(job_id)
        if not path.is_file():
            raise HTTPException(404, "deleted project not found")
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(500, f"could not restore project: {exc}") from exc
        if not isinstance(job, dict) or str(job.get("id")) != job_id:
            raise HTTPException(400, "deleted project record is invalid")
        _jobs[job_id] = job
        _persist_job_locked(job)
        try:
            path.unlink()
        except OSError:
            pass
        return _job_snapshot(job)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(
    job_id: str,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    """Restart a failed/interrupted/draft project with its saved settings."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        status = str(job.get("status") or "unknown")
        if status == "running":
            raise HTTPException(409, "project is already running")
        if status not in {"error", "cancelled", "interrupted", "draft"}:
            raise HTTPException(409, "only failed, cancelled, interrupted, or draft projects can be retried")
        request = _dict_value(job.get("request"))
    try:
        req = JobRequest.model_validate(request)
    except Exception as exc:
        raise HTTPException(400, f"saved project settings are invalid: {exc}") from exc
    credentials = _runtime_credentials_from_headers(
        x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider
    )
    if req.llm_provider:
        credentials["llm_provider"] = req.llm_provider
    elif credentials.get("llm_provider"):
        req.llm_provider = credentials["llm_provider"]
    if req.mode == "api" and not (credentials.get("muapi") or MUAPI_API_KEY):
        raise HTTPException(
            400,
            "API mode needs a MuAPI API key. Enter it in Settings before retrying.",
        )
    with _lock:
        job = _jobs.get(job_id)
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
        _append_job_log(job, "queued", job["message"])
        _cancel_events[job_id] = threading.Event()
        if credentials:
            _job_credentials[job_id] = credentials
        _persist_job_locked(job)
        snapshot = _job_snapshot(job)
    _start_job_thread(job_id, req, credentials)
    return snapshot


def _validate_log_filters(job_id: Optional[str], level: Optional[str], stage: Optional[str]) -> None:
    if job_id and not _job_id_pattern.fullmatch(job_id):
        raise HTTPException(400, "invalid job id")
    if level and level.strip().lower() not in {"error", "warn", "running", "done", "project"}:
        raise HTTPException(400, "invalid log level")
    if stage and (len(stage) > 32 or not re.fullmatch(r"[A-Za-z0-9_.-]+", stage.strip())):
        raise HTTPException(400, "invalid log stage")


@app.get("/api/logs")
def list_logs(
    job_id: Optional[str] = Query(default=None, max_length=64),
    level: Optional[str] = Query(default=None, max_length=20),
    stage: Optional[str] = Query(default=None, max_length=32),
    q: Optional[str] = Query(default=None, max_length=300),
    limit: int = Query(default=250, ge=1, le=1000),
) -> Dict[str, Any]:
    """Return recent project activity without exposing credentials or raw records."""
    _validate_log_filters(job_id, level, stage)
    with _lock:
        if job_id and job_id not in _jobs:
            raise HTTPException(404, "job not found")
        entries = _filter_log_entries_locked(job_id, level, stage, q)
    total = len(entries)
    return {
        "logs": entries[:limit],
        "count": min(total, limit),
        "total": total,
        "current_version": _APP_VERSION,
    }


@app.get("/api/logs/download")
def download_logs(
    job_id: Optional[str] = Query(default=None, max_length=64),
    level: Optional[str] = Query(default=None, max_length=20),
    stage: Optional[str] = Query(default=None, max_length=32),
    q: Optional[str] = Query(default=None, max_length=300),
) -> PlainTextResponse:
    """Download the currently filtered activity log as plain text."""
    _validate_log_filters(job_id, level, stage)
    with _lock:
        if job_id and job_id not in _jobs:
            raise HTTPException(404, "job not found")
        entries = list(reversed(_filter_log_entries_locked(job_id, level, stage, q)))
    lines = [f"{entry['timestamp']} [{entry['project']}] [{entry['stage']}] {entry['message']}" for entry in entries]
    filename = f"shorts_{job_id}.log" if job_id else "shorts_studio.log"
    return PlainTextResponse(
        "\n".join(lines) + ("\n" if lines else ""),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/jobs/{job_id}/logs")
def download_job_logs(job_id: str):
    """Backwards-compatible per-project log download."""
    if not _job_id_pattern.fullmatch(job_id):
        raise HTTPException(400, "invalid job id")
    with _lock:
        if job_id not in _jobs:
            raise HTTPException(404, "job not found")
        entries = list(reversed(_log_entries_locked(job_id)))
    lines = [f"{entry['timestamp']} [{entry['stage']}] {entry['message']}" for entry in entries]
    return PlainTextResponse(
        "\n".join(lines) + ("\n" if lines else ""),
        headers={"Content-Disposition": f'attachment; filename="shorts_{job_id}.log"'},
    )


@app.post("/api/open-folder")
def open_folder(request: OpenFolderRequest) -> Dict[str, Any]:
    """Open a safe local output folder on desktop builds."""
    if request.job_id:
        with _lock:
            job = _jobs.get(request.job_id)
            if not job:
                raise HTTPException(404, "job not found")
            folder = Path(str(job.get("output_dir") or _output_root))
    else:
        folder = _output_root
    try:
        folder = folder.expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(400, f"output folder is unavailable: {exc}") from exc
    opened = False
    headless = os.getenv("SHORTS_STUDIO_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not headless:
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            opened = True
        except FileNotFoundError:
            # A server/container may not have a desktop opener. Returning the
            # path is still useful and avoids turning a successful export into
            # a misleading 500 response.
            opened = False
        except OSError as exc:
            raise HTTPException(500, f"could not open folder: {exc}") from exc
    return {"status": "opened" if opened else "available", "opened": opened, "path": str(folder)}


@app.post("/api/jobs/{job_id}/clips/{index}")
def update_clip(job_id: str, index: int, update: ClipUpdate) -> Dict[str, Any]:
    """Regenerate one clip after a manual timestamp/style adjustment."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        raw_shorts = _dict_items(job.get("raw_shorts"))
        if index < 0 or index >= len(raw_shorts):
            raise HTTPException(404, "clip not found")
        request = _dict_value(job.get("request"))
        transcript = job.get("raw_transcript")
        transcript = dict(transcript) if isinstance(transcript, dict) else {}
        source = job.get("raw_source_video_url")
        mode = str(_dict_value(job.get("result")).get("mode") or request.get("mode") or "local")

    duration = _safe_transcript_duration(transcript)
    if duration and update.start_time >= duration:
        raise HTTPException(400, f"start_time must be before the {duration:.1f}s source")
    if duration and update.end_time > duration + 0.25:
        raise HTTPException(400, f"end_time must be within the {duration:.1f}s source")
    if update.end_time <= update.start_time + 0.1:
        raise HTTPException(400, "end_time must be at least 0.1s after start_time")
    style = (update.caption_style or request.get("caption_style") or "bold").strip().lower()
    if style not in {"clean", "bold", "boxed", "karaoke"}:
        raise HTTPException(400, "caption_style must be clean, bold, boxed, or karaoke")
    if not source:
        raise HTTPException(400, "source video is unavailable for this job")

    old = dict(raw_shorts[index])
    try:
        if mode == "local":
            from shorts_generator.local.clipper import crop_clip_local

            old_path = str(old.get("clip_url") or "")
            safe_old_path = _job_media_path(job, old_path)
            if safe_old_path and safe_old_path.is_file():
                out_path = str(safe_old_path)
            else:
                job_output_dir = str(job.get("output_dir") or (_jobs_dir / job_id))
                out_path = str(Path(job_output_dir).expanduser().resolve() / f"short_{index + 1:02d}.mp4")
            undo_path = out_path + ".undo.mp4"
            render_path = out_path + ".regenerate.mp4"
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            crop_clip_local(
                str(source),
                update.start_time,
                update.end_time,
                str(request.get("aspect_ratio") or "9:16"),
                render_path,
                caption_segments=_dict_items(transcript.get("segments")),
                burn_captions=LOCAL_BURN_CAPTIONS,
                caption_style=style,
                remove_silence=bool(request.get("remove_silence")),
                normalize_audio=bool(request.get("normalize_audio")),
                denoise_audio=bool(request.get("denoise_audio")),
                remove_filler_words=bool(request.get("remove_filler_words")),
                caption_position=update.caption_position,
                caption_font=update.caption_font,
                caption_size=update.caption_size,
                caption_color=update.caption_color,
                background_music=request.get("background_music") or None,
                watermark=request.get("watermark") or None,
                auto_reframe=bool(request.get("auto_reframe", True)),
                crop_position=update.crop_position,
                fit_mode=update.fit_mode,
                zoom=update.zoom,
                layout=update.layout,
                output_height=update.output_height,
                intro=request.get("intro") or None,
                outro=request.get("outro") or None,
                jump_cuts=bool(request.get("jump_cuts")),
            )
            if not os.path.isfile(render_path):
                raise RuntimeError("clip renderer did not produce an output file")
            # Keep the current clip and its previous undo snapshot untouched
            # until the replacement render has completed successfully.
            if os.path.isfile(out_path):
                shutil.copyfile(out_path, undo_path)
            os.replace(render_path, out_path)
            replacement = {
                **old,
                "start_time": update.start_time,
                "end_time": update.end_time,
                "clip_url": out_path,
                "captions_burned": bool(LOCAL_BURN_CAPTIONS and transcript.get("segments")),
                "fit_mode": update.fit_mode,
                "zoom": update.zoom,
                "crop_position": update.crop_position,
                "caption_style": style,
                "caption_position": update.caption_position,
                "caption_font": update.caption_font,
                "caption_size": update.caption_size,
                "caption_color": update.caption_color,
                "layout": update.layout,
                "output_height": update.output_height,
            }
            replacement["undo_path"] = undo_path if os.path.isfile(undo_path) else None
            replacement["undo_metadata"] = {
                key: value
                for key, value in old.items()
                if key not in {"undo_path", "undo_metadata"}
            }
            try:
                from shorts_generator.local.visual import extract_thumbnail

                thumb = str(Path(out_path).with_suffix(".jpg"))
                extract_thumbnail(str(source), (update.start_time + update.end_time) / 2.0, thumb)
                replacement["thumbnail_path"] = thumb
            except Exception:
                pass
        elif mode == "api":
            from shorts_generator.clipper import crop_clip

            replacement = {
                **old,
                "start_time": update.start_time,
                "end_time": update.end_time,
                "fit_mode": update.fit_mode,
                "zoom": update.zoom,
                "crop_position": update.crop_position,
                "caption_style": style,
                "caption_position": update.caption_position,
                "caption_font": update.caption_font,
                "caption_size": update.caption_size,
                "caption_color": update.caption_color,
                "layout": update.layout,
                "output_height": update.output_height,
                "clip_url": crop_clip(
                    str(source),
                    update.start_time,
                    update.end_time,
                    aspect_ratio=str(request.get("aspect_ratio") or "9:16"),
                ),
            }
        else:
            raise HTTPException(400, f"unsupported job mode: {mode}")
    except HTTPException:
        raise
    except Exception as exc:
        if mode == "local":
            render_path = locals().get("render_path")
            if render_path and os.path.isfile(render_path):
                try:
                    os.remove(render_path)
                except OSError:
                    pass
        raise HTTPException(500, f"could not regenerate clip: {exc}") from exc

    with _lock:
        job = _jobs[job_id]
        current = _dict_items(job.get("raw_shorts"))
        if index >= len(current):
            raise HTTPException(409, "job clips changed while regenerating")
        current[index] = replacement
        job["raw_shorts"] = current
        result = _dict_value(job.get("result"))
        result["shorts"] = _public_shorts(current, job_id)
        job["result"] = result
        job["message"] = f"Regenerated clip {index + 1}"
        _append_job_log(job, "edit", job["message"])
        _persist_job_locked(job)
        return _job_snapshot(job)


@app.post("/api/jobs/{job_id}/clips/{index}/undo")
def undo_clip(job_id: str, index: int) -> Dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = _dict_items(job.get("raw_shorts"))
        if index < 0 or index >= len(shorts):
            raise HTTPException(404, "clip not found")
        item = dict(shorts[index])
        undo_path = _job_media_path(job, item.get("undo_path"))
        clip_path = _job_media_path(job, item.get("clip_url"))
        if not undo_path or not undo_path.is_file() or not clip_path:
            raise HTTPException(400, "no previous clip version is available")
        shutil.copyfile(undo_path, clip_path)
        restored = _dict_value(item.get("undo_metadata")) or dict(item)
        restored["clip_url"] = str(clip_path)
        restored.pop("undo_path", None)
        restored.pop("undo_metadata", None)
        shorts[index] = restored
        job["raw_shorts"] = shorts
        result = _dict_value(job.get("result"))
        if result:
            result["shorts"] = _public_shorts(shorts, job_id)
            job["result"] = result
        _persist_job_locked(job)
        return _job_snapshot(job)


@app.get("/api/jobs/{job_id}/timeline")
def get_timeline(job_id: str) -> Dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        transcript = job.get("raw_transcript")
        if not isinstance(transcript, dict):
            transcript = {}
        return {
            "duration": _safe_transcript_duration(transcript),
            "segments": _dict_items(transcript.get("segments")),
            "visual_events": _dict_items(transcript.get("visual_events")),
        }


@app.get("/api/jobs/{job_id}/waveform")
def get_waveform(job_id: str, bins: int = 240) -> Dict[str, Any]:
    """Return cached audio peaks for a lightweight timeline waveform."""
    bins = max(32, min(600, int(bins or 240)))
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        source = job.get("raw_source_video_url")
        output_dir = Path(str(job.get("output_dir") or (_jobs_dir / job_id))).expanduser().resolve()
    if not source or not Path(str(source)).is_file():
        return {"duration": 0.0, "peaks": [], "available": False}
    source_path = Path(str(source)).expanduser().resolve()
    cache_path = output_dir / "waveform.json"
    try:
        signature = [source_path.stat().st_size, source_path.stat().st_mtime_ns, bins]
    except OSError:
        signature = []
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached.get("signature") == signature and isinstance(cached.get("peaks"), list):
            return {"duration": float(cached.get("duration") or 0.0), "peaks": cached["peaks"], "available": True, "cached": True}
    except (OSError, ValueError, TypeError):
        pass
    try:
        from shorts_generator.local.clipper import _find_ffmpeg

        ffmpeg = _find_ffmpeg()
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(source_path), "-f", "s16le", "-ac", "1", "-ar", "2000", "-v", "error", "-"],
            capture_output=True,
            timeout=90,
            check=False,
        )
        raw = probe.stdout or b""
        samples = array("h")
        samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
        if not samples:
            return {"duration": 0.0, "peaks": [], "available": False}
        step = max(1, len(samples) // bins)
        peaks = []
        for start in range(0, len(samples), step):
            window = samples[start : start + step]
            peak = max((abs(value) for value in window), default=0) / 32768.0
            peaks.append(round(min(1.0, peak), 4))
            if len(peaks) >= bins:
                break
        duration = len(samples) / 2000.0
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"signature": signature, "duration": duration, "peaks": peaks}), encoding="utf-8")
        return {"duration": duration, "peaks": peaks, "available": True, "cached": False}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, TimeoutError) as exc:
        return {"duration": 0.0, "peaks": [], "available": False, "error": str(exc)}


@app.get("/api/jobs/{job_id}/export")
def export_job(job_id: str):
    """Download a ZIP containing local clips and creator metadata."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        result = _dict_value(job.get("result"))
        raw_shorts = _dict_items(job.get("raw_shorts"))
        request = _dict_value(job.get("request"))

    manifest = {
        "job_id": job_id,
        "request": request,
        "mode": result.get("mode"),
        "source_video_url": result.get("source_video_url"),
        "shorts": [
            {
                **{key: value for key, value in short.items() if key != "clip_url"},
                "creator_metadata": _creator_metadata(short),
            }
            for short in raw_shorts
        ],
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("metadata.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr("publishing/youtube_shorts.json", json.dumps({"platform": "youtube_shorts", "items": [s["creator_metadata"] for s in manifest["shorts"]]}, ensure_ascii=False, indent=2))
        bundle.writestr("publishing/tiktok.json", json.dumps({"platform": "tiktok", "items": [s["creator_metadata"] for s in manifest["shorts"]]}, ensure_ascii=False, indent=2))
        bundle.writestr("publishing/instagram_reels.json", json.dumps({"platform": "instagram_reels", "items": [s["creator_metadata"] for s in manifest["shorts"]]}, ensure_ascii=False, indent=2))
        for index, short in enumerate(raw_shorts, 1):
            path = _job_media_path(job, short.get("clip_url"))
            if path and path.is_file():
                bundle.write(path, arcname=f"clips/short_{index:02d}.mp4")
            thumbnail = _job_media_path(job, short.get("thumbnail_path"))
            if thumbnail and thumbnail.is_file():
                bundle.write(thumbnail, arcname=f"thumbnails/short_{index:02d}.jpg")
            for caption_format in ("srt", "vtt"):
                caption_text = _captions_for_short(short, job.get("raw_transcript"), caption_format)
                if caption_text:
                    bundle.writestr(f"captions/short_{index:02d}.{caption_format}", caption_text)
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="shorts_{job_id}.zip"'},
    )


def _subtitle_timestamp(seconds: object, vtt: bool = False) -> str:
    try:
        value = float(seconds)
        if not math.isfinite(value) or value < 0:
            value = 0.0
    except (TypeError, ValueError, OverflowError):
        value = 0.0
    milliseconds = max(0, int(round(value * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_int, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d}{separator}{millis:03d}"


def _captions_for_short(short: Dict[str, Any], transcript: Any, format_name: str = "srt") -> str:
    if not isinstance(short, dict) or not isinstance(transcript, dict):
        return ""
    try:
        clip_start = float(short.get("start_time"))
        clip_end = float(short.get("end_time"))
        if not math.isfinite(clip_start) or not math.isfinite(clip_end) or clip_end <= clip_start:
            return ""
    except (TypeError, ValueError, OverflowError):
        return ""
    vtt = str(format_name).lower() == "vtt"
    lines = ["WEBVTT", ""] if vtt else []
    count = 0
    for segment in _dict_items(transcript.get("segments")):
        try:
            start = float(segment.get("start"))
            end = float(segment.get("end"))
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        left = max(start, clip_start)
        right = min(end, clip_end)
        text = " ".join(str(segment.get("text") or "").split())
        if right <= left or not text:
            continue
        count += 1
        lines.append(f"{count}" if not vtt else "")
        lines.append(f"{_subtitle_timestamp(left - clip_start, vtt)} --> {_subtitle_timestamp(right - clip_start, vtt)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines) if count else ""


@app.get("/api/jobs/{job_id}/clip/{index}/captions")
def download_clip_captions(job_id: str, index: int, format: str = "srt"):
    format_name = str(format or "srt").strip().lower()
    if format_name not in {"srt", "vtt"}:
        raise HTTPException(400, "format must be srt or vtt")
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = _dict_items(job.get("raw_shorts"))
        transcript = job.get("raw_transcript")
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "clip not found")
    text = _captions_for_short(shorts[index], transcript, format_name)
    if not text:
        raise HTTPException(404, "no captions available for this clip")
    return PlainTextResponse(
        text,
        media_type="text/vtt" if format_name == "vtt" else "application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="short_{index + 1:02d}.{format_name}"'},
    )


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return _job_snapshot(job)


@app.get("/api/jobs/{job_id}/clip/{index}")
def get_clip(job_id: str, index: int):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = _dict_items(job.get("raw_shorts"))
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "clip not found")
    path = shorts[index].get("clip_url")
    if not path or str(path).startswith("http"):
        raise HTTPException(400, "clip is not a local file")
    p = _job_media_path(job, path)
    if not p or not p.is_file():
        raise HTTPException(404, f"file missing: {path}")
    return FileResponse(p, media_type="video/mp4", filename=p.name)


@app.post("/api/jobs/{job_id}/preview")
def preview_clip(job_id: str, update: ClipUpdate) -> Dict[str, Any]:
    """Render a lightweight preview using the exact crop settings requested."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        request = _dict_value(job.get("request"))
        source = job.get("raw_source_video_url")
        transcript = job.get("raw_transcript")
        transcript = dict(transcript) if isinstance(transcript, dict) else {}
        output_dir = str(job.get("output_dir") or (_jobs_dir / job_id))
    if not source or not Path(str(source)).is_file():
        raise HTTPException(400, "a completed local job is required for preview")
    duration = _safe_transcript_duration(transcript)
    if duration and update.start_time >= duration:
        raise HTTPException(400, f"start_time must be before the {duration:.1f}s source")
    if duration and update.end_time > duration + 0.25:
        raise HTTPException(400, f"end_time must be within the {duration:.1f}s source")
    if update.end_time <= update.start_time + 0.1:
        raise HTTPException(400, "end_time must be at least 0.1s after start_time")
    style = (update.caption_style or str(request.get("caption_style") or "bold")).strip().lower()
    if style not in {"clean", "bold", "boxed", "karaoke"}:
        raise HTTPException(400, "caption_style must be clean, bold, boxed, or karaoke")
    from shorts_generator.local.clipper import crop_clip_local
    preview_dir = Path(output_dir) / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_stat = Path(str(source)).stat()
        source_stamp = [source_stat.st_size, source_stat.st_mtime_ns]
    except OSError:
        source_stamp = []
    preview_payload = {
        "source": source_stamp,
        "start": update.start_time,
        "end": update.end_time,
        "caption_style": style,
        "caption_position": update.caption_position,
        "caption_font": update.caption_font,
        "caption_size": update.caption_size,
        "caption_color": update.caption_color,
        "crop_position": update.crop_position,
        "zoom": update.zoom,
        "fit_mode": update.fit_mode,
        "layout": update.layout,
        "output_height": min(960, update.output_height or 1920),
    }
    preview_key = hashlib.sha256(json.dumps(preview_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:20]
    cached = preview_dir / f"preview_{preview_key}.mp4"
    preview = Path(output_dir) / "preview.mp4"
    if cached.is_file():
        shutil.copyfile(cached, preview)
        return {"preview_url": f"/api/jobs/{job_id}/preview.mp4?key={preview_key}", "path": str(preview), "cached": True}
    render_path = preview_dir / f"preview_{preview_key}.render.mp4"
    try:
        crop_clip_local(
            str(source), update.start_time, update.end_time,
            str(request.get("aspect_ratio") or "9:16"), str(render_path),
            caption_segments=_dict_items(transcript.get("segments")),
            burn_captions=LOCAL_BURN_CAPTIONS,
            caption_style=style,
            caption_position=update.caption_position,
            caption_font=update.caption_font,
            caption_size=update.caption_size,
            caption_color=update.caption_color,
            remove_silence=bool(request.get("remove_silence")),
            normalize_audio=bool(request.get("normalize_audio")),
            denoise_audio=bool(request.get("denoise_audio")),
            remove_filler_words=bool(request.get("remove_filler_words")),
            background_music=request.get("background_music") or None,
            watermark=request.get("watermark") or None,
            auto_reframe=bool(request.get("auto_reframe", True)),
            crop_position=update.crop_position, fit_mode=update.fit_mode, zoom=update.zoom,
            layout=update.layout,
            output_height=min(960, update.output_height or 1920),
            intro=request.get("intro") or None,
            outro=request.get("outro") or None,
            jump_cuts=bool(request.get("jump_cuts")),
        )
        if not render_path.is_file():
            raise RuntimeError("preview renderer did not produce an output file")
        os.replace(render_path, cached)
        shutil.copyfile(cached, preview)
    finally:
        if render_path.is_file():
            try:
                render_path.unlink()
            except OSError:
                pass
    return {"preview_url": f"/api/jobs/{job_id}/preview.mp4?key={preview_key}", "path": str(preview), "cached": False}


@app.get("/api/jobs/{job_id}/preview.mp4")
def get_preview(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        output_dir = Path(str(job.get("output_dir") or (_jobs_dir / job_id)))
        path = _job_media_path(job, output_dir / "preview.mp4")
    if not path or not path.is_file():
        raise HTTPException(404, "preview not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.get("/api/jobs/{job_id}/thumbnail/{index}")
def get_thumbnail(job_id: str, index: int):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = _dict_items(job.get("raw_shorts"))
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "thumbnail not found")
    path = shorts[index].get("thumbnail_path")
    safe_path = _job_media_path(job, path)
    if not safe_path or not safe_path.is_file():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(safe_path, media_type="image/jpeg", filename=safe_path.name)


@app.post("/api/uploads")
async def upload_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Store a browser-uploaded source in the local output area."""
    original_name = Path(file.filename or "video.mp4").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in _allowed_upload_extensions:
        allowed = ", ".join(sorted(_allowed_upload_extensions))
        raise HTTPException(400, f"unsupported video type; use one of: {allowed}")

    safe_stem = Path(original_name).stem.strip() or "video"
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in safe_stem)
    # Keep the final path comfortably below Windows MAX_PATH even when a
    # browser supplies an unusually long filename.
    safe_stem = safe_stem[:120] or "video"
    target = _uploads_dir / f"upload_{uuid.uuid4().hex[:12]}_{safe_stem}{suffix}"
    temporary = target.with_suffix(target.suffix + ".part")
    size = 0
    try:
        _uploads_dir.mkdir(parents=True, exist_ok=True)
        with temporary.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _max_upload_bytes:
                    raise HTTPException(
                        413,
                        f"file is larger than the {_max_upload_bytes // (1024 * 1024)} MB upload limit",
                    )
                output.write(chunk)
        os.replace(temporary, target)
    except HTTPException:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise HTTPException(500, f"could not save upload: {exc}") from exc
    except Exception as exc:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
        raise HTTPException(500, f"could not save upload: {exc}") from exc
    finally:
        await file.close()

    return {
        "name": original_name,
        "path": str(target.resolve()),
        "url": f"/api/uploads/{target.name}",
        "size": size,
    }


@app.get("/api/uploads/{filename}")
def get_upload(filename: str):
    """Serve an uploaded source for an optional browser preview."""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(404, "upload not found")
    path = _uploads_dir / safe_name
    if not path.is_file():
        raise HTTPException(404, "upload not found")
    return FileResponse(path, filename=path.name)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "output": str(Path(LOCAL_OUTPUT_DIR).resolve())}


def _setup_state() -> Dict[str, Any]:
    try:
        value = json.loads(_setup_state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_setup_state(values: Dict[str, Any]) -> None:
    _output_root.mkdir(parents=True, exist_ok=True)
    temporary = _setup_state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, _setup_state_path)


def _whisper_model_cached(model_name: str) -> bool:
    model = str(model_name or "").strip()
    if not model:
        return False
    roots = [
        Path.home() / ".cache" / "huggingface" / "hub",
        Path(os.getenv("LOCALAPPDATA", "")) / "huggingface" / "hub",
    ]
    for env_name in ("HF_HOME", "HUGGINGFACE_HUB_CACHE"):
        configured = os.getenv(env_name, "").strip()
        if configured:
            cache_root = Path(configured).expanduser()
            roots.extend((cache_root / "hub", cache_root))
    token = f"models--Systran--faster-whisper-{model}"
    return any((root / token).is_dir() for root in roots if str(root))


def _setup_report() -> Dict[str, Any]:
    state = _setup_state()
    try:
        usage = shutil.disk_usage(_output_root)
        free_gb = round(usage.free / (1024 ** 3), 2)
    except OSError:
        free_gb = 0.0
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    gpu = gpu_status()
    provider = str(LLM_PROVIDER or "openai").strip().lower()
    provider_key = bool(OPENAI_API_KEY) if provider == "openai" else bool(GEMINI_API_KEY) if provider == "gemini" else False
    warnings = []
    if not ffmpeg:
        warnings.append("FFmpeg is not available; local rendering cannot start until it is installed or bundled.")
    if not ffprobe:
        warnings.append("FFprobe is not available; media diagnostics will be limited.")
    if free_gb < _min_free_gb:
        warnings.append(f"Only {free_gb:.2f} GB of free disk space is available.")
    if provider not in {"openai", "gemini"}:
        warnings.append(f"Unknown LLM_PROVIDER={provider!r}; offline ranking will be used.")
    return {
        "first_run": not bool(state.get("setup_dismissed")),
        "setup_dismissed": bool(state.get("setup_dismissed")),
        "ffmpeg": {"ready": bool(ffmpeg), "path": ffmpeg},
        "ffprobe": {"ready": bool(ffprobe), "path": ffprobe},
        "gpu": gpu,
        "whisper": {
            "model": LOCAL_WHISPER_MODEL,
            "device": LOCAL_WHISPER_DEVICE,
            "model_cached": _whisper_model_cached(LOCAL_WHISPER_MODEL),
        },
        "keys": {
            "muapi_configured": bool(MUAPI_API_KEY),
            "openai_configured": bool(OPENAI_API_KEY),
            "gemini_configured": bool(GEMINI_API_KEY),
            "selected_provider": provider,
            "selected_provider_configured": provider_key,
            "offline_fallback": bool(LOCAL_HEURISTIC_FALLBACK),
        },
        "storage": {"output_root": str(_output_root), "free_disk_gb": free_gb, "minimum_free_gb": _min_free_gb},
        "warnings": warnings,
        "ready_for_local": bool(ffmpeg) and free_gb >= _min_free_gb,
    }


@app.get("/api/setup")
def setup_report() -> Dict[str, Any]:
    return _setup_report()


@app.post("/api/setup/prepare")
def prepare_setup(update: Optional[SetupStateUpdate] = None) -> Dict[str, Any]:
    update = update or SetupStateUpdate()
    try:
        _output_root.mkdir(parents=True, exist_ok=True)
        _jobs_dir.mkdir(parents=True, exist_ok=True)
        _uploads_dir.mkdir(parents=True, exist_ok=True)
        state = _setup_state()
        state["setup_dismissed"] = bool(update.dismissed)
        state["last_checked_at"] = time.time()
        _write_setup_state(state)
    except OSError as exc:
        raise HTTPException(500, f"could not prepare local folders: {exc}") from exc
    return _setup_report()


@app.post("/api/setup/dismiss")
def dismiss_setup(update: Optional[SetupStateUpdate] = None) -> Dict[str, Any]:
    return prepare_setup(update)


@app.post("/api/shutdown")
def shutdown() -> Dict[str, str]:
    """Stop this local-only server (used by the portable launcher Quit button)."""
    threading.Timer(0.25, lambda: os._exit(0)).start()
    return {"status": "shutting_down"}


@app.get("/api/system")
def system_status() -> Dict[str, Any]:
    usage = shutil.disk_usage(_output_root)
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "whisper_model": LOCAL_WHISPER_MODEL,
        "whisper_device": LOCAL_WHISPER_DEVICE,
        "gpu": gpu_status(),
        "whisper_models": ["tiny", "base", "small", "medium", "large-v3"],
        "whisper_devices": ["auto", "cpu", "cuda"],
        "captions_enabled": LOCAL_BURN_CAPTIONS,
        "free_disk_gb": round(usage.free / (1024 ** 3), 2),
        "max_concurrent_jobs": _max_concurrent_jobs,
        "setup": _setup_report(),
    }


@app.get("/api/diagnostics")
def diagnostics() -> Dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    with _lock:
        counts = {}
        for job in _jobs.values():
            counts[job.get("status", "unknown")] = counts.get(job.get("status", "unknown"), 0) + 1
    return {
        "python": sys.version,
        "ffmpeg_path": ffmpeg,
        "ffmpeg_ready": bool(ffmpeg),
        "output_root": str(_output_root),
        "free_disk_gb": round(shutil.disk_usage(_output_root).free / (1024 ** 3), 2),
        "job_counts": counts,
        "captions_enabled": LOCAL_BURN_CAPTIONS,
        "setup": _setup_report(),
    }


def _version_tuple(value: Any) -> tuple[int, int, int]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def _github_release() -> Dict[str, Any]:
    import requests

    response = requests.get(
        f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ShortsStudio-Updater"},
        timeout=(8, 30),
    )
    response.raise_for_status()
    release = response.json()
    if not isinstance(release, dict):
        raise RuntimeError("GitHub returned an invalid release response")
    return release


def _package_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return ROOT


def _package_root_writable() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    root = _package_root()
    probe = root / f".shorts-studio-update-{uuid.uuid4().hex}.tmp"
    try:
        probe.write_text("ok", encoding="ascii")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _update_dir() -> Path:
    data_root = Path(os.getenv("SHORTS_STUDIO_DATA_DIR") or _output_root.parent).expanduser()
    return data_root / "updates"


def _select_release_asset(release: Dict[str, Any]) -> Optional[Dict[str, str]]:
    raw_assets = release.get("assets")
    assets = raw_assets if isinstance(raw_assets, list) else []
    candidates: list[Dict[str, str]] = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        name = Path(str(raw.get("name") or "")).name
        url = str(raw.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        lower = name.lower()
        if lower.endswith(".zip") and "window" in lower:
            candidates.append({"name": name, "url": url, "kind": "zip"})
        elif lower.endswith(".exe") and ("setup" in lower or "installer" in lower):
            candidates.append({"name": name, "url": url, "kind": "installer"})
    if not candidates:
        return None
    if _package_root_writable():
        return next((asset for asset in candidates if asset["kind"] == "zip"), candidates[0])
    if getattr(sys, "frozen", False):
        return next((asset for asset in candidates if asset["kind"] == "installer"), candidates[0])
    return None


def _release_info(release: Dict[str, Any]) -> Dict[str, Any]:
    tag = str(release.get("tag_name") or "").strip()
    if not tag or _version_tuple(tag) == (0, 0, 0):
        raise RuntimeError("GitHub release did not include a usable version tag")
    latest = tag.lstrip("vV")
    current_version = _APP_VERSION
    asset = _select_release_asset(release)
    return {
        "available": True,
        "update_available": _version_tuple(latest) > _version_tuple(current_version),
        "current_version": current_version,
        "latest_version": latest,
        "tag": tag,
        "url": str(release.get("html_url") or f"https://github.com/{_GITHUB_REPO}/releases/tag/{tag}"),
        "name": str(release.get("name") or f"Shorts Studio {tag}"),
        "published_at": release.get("published_at"),
        "asset": asset,
        "can_install": bool(asset and _version_tuple(latest) > _version_tuple(current_version)),
        "frozen": bool(getattr(sys, "frozen", False)),
    }


def _set_update_state(**values: Any) -> Dict[str, Any]:
    with _update_lock:
        _update_state.update(values)
        return dict(_update_state)


def _ps_quote(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _write_zip_updater(zip_path: Path, install_root: Path) -> Path:
    update_root = zip_path.parent
    script = update_root / f"apply-{uuid.uuid4().hex}.ps1"
    pid = os.getpid()
    script_text = f"""$ErrorActionPreference = 'Stop'
$pidToWait = {pid}
$zip = {_ps_quote(zip_path)}
$install = {_ps_quote(install_root)}
$stage = Join-Path ([IO.Path]::GetTempPath()) ('ShortsStudio-update-' + [guid]::NewGuid().ToString('N'))
try {{
  while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 500 }}
  New-Item -ItemType Directory -Path $stage -Force | Out-Null
  Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
  $payload = Join-Path $stage 'ShortsStudio'
  if (-not (Test-Path -LiteralPath $payload)) {{ throw 'The downloaded update did not contain a ShortsStudio folder.' }}
  & robocopy $payload $install /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -gt 7) {{ throw "Update copy failed with robocopy exit code $LASTEXITCODE." }}
  Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
  Start-Process -FilePath (Join-Path $install 'ShortsStudio.exe') -WorkingDirectory $install
}} catch {{
  Add-Content -LiteralPath (Join-Path $stage 'update-error.txt') -Value $_.Exception.Message -ErrorAction SilentlyContinue
}} finally {{
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}}
"""
    script.write_text(script_text, encoding="utf-8")
    return script


def _launch_update(asset: Dict[str, str], downloaded: Path) -> None:
    if asset.get("kind") == "zip":
        script = _write_zip_updater(downloaded, _package_root())
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
            cwd=str(downloaded.parent),
            creationflags=flags,
        )
    else:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [str(downloaded), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
            cwd=str(downloaded.parent),
            creationflags=flags,
        )


def _download_and_apply(asset: Dict[str, str], latest: str) -> None:
    import requests

    partial: Optional[Path] = None
    try:
        target_dir = _update_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(asset["name"]).name
        target = target_dir / filename
        partial = target.with_name(target.name + ".part")
        _set_update_state(status="downloading", latest_version=latest, asset_name=filename, progress=0, total=0, message=f"Downloading {filename}", error=None)
        with requests.get(
            asset["url"],
            headers={"Accept": "application/octet-stream", "User-Agent": "ShortsStudio-Updater"},
            stream=True,
            timeout=(15, 120),
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            downloaded_bytes = 0
            _set_update_state(total=total)
            with partial.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded_bytes += len(chunk)
                    _set_update_state(progress=downloaded_bytes, total=total)
        os.replace(partial, target)
        _set_update_state(status="restarting", progress=target.stat().st_size, total=target.stat().st_size, path=str(target), message="Update downloaded. Restarting Shorts Studio…", error=None)
        _launch_update(asset, target)
        threading.Thread(target=lambda: (time.sleep(0.35), os._exit(0)), name="shorts-studio-update-exit", daemon=True).start()
    except Exception as exc:
        if partial is not None:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
        _set_update_state(status="error", message="Update failed", error=str(exc))


@app.get("/api/update")
def update_check() -> Dict[str, Any]:
    """Check the wiifhub release and describe the in-app update path."""
    try:
        info = _release_info(_github_release())
        _set_update_state(
            status="available" if info["update_available"] else "current",
            current_version=info["current_version"],
            latest_version=info["latest_version"],
            progress=0,
            total=0,
            message="Update available" if info["update_available"] else "Shorts Studio is up to date",
            error=None,
        )
        info["state"] = dict(_update_state)
        return info
    except Exception as exc:
        _set_update_state(status="error", message="Update check failed", error=str(exc))
        return {"available": False, "update_available": False, "current_version": _APP_VERSION, "error": str(exc), "state": dict(_update_state)}


@app.get("/api/update/status")
def update_status() -> Dict[str, Any]:
    with _update_lock:
        return dict(_update_state)


@app.post("/api/update/apply")
def update_apply() -> Dict[str, Any]:
    """Download and apply the newest packaged release, then restart the app."""
    with _update_lock:
        if _update_state.get("status") in {"checking", "starting", "downloading", "restarting"}:
            return dict(_update_state)
    try:
        release = _github_release()
        info = _release_info(release)
        if not info["update_available"]:
            return {"status": "current", "message": "Shorts Studio is already up to date", **info}
        asset = info.get("asset")
        if not asset or not info.get("can_install"):
            return {"status": "manual", "message": "This source install needs a manual update from the GitHub release page.", **info}
        _set_update_state(status="starting", current_version=info["current_version"], latest_version=info["latest_version"], progress=0, total=0, message="Starting update…", error=None)
        threading.Thread(target=_download_and_apply, args=(asset, info["latest_version"]), name="shorts-studio-update", daemon=True).start()
        return {"status": "starting", "message": "Update started", **info}
    except Exception as exc:
        _set_update_state(status="error", message="Update failed", error=str(exc))
        return {"status": "error", "message": "Update failed", "error": str(exc), "current_version": _APP_VERSION}


def main() -> None:
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=7860, reload=False)


if __name__ == "__main__":
    main()
