"""Web UI for the YouTube Shorts generator.

python -m web.app
# then open http://127.0.0.1:7860
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import importlib.util
from urllib.parse import unquote, urlparse
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager, contextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shorts_generator import __version__, generate_shorts  # noqa: E402
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
    runtime_job_control,
)
from shorts_generator.local.downloader import validate_remote_source  # noqa: E402
from shorts_generator.costs import rates_from_environment  # noqa: E402
from web.models import JobRequest, ProviderCostRates  # noqa: E402
from web.security import (  # noqa: E402
    SlidingWindowLimiter,
    auth_enabled,
    authorized,
    client_key,
    error_response,
    rate_limit_response,
    redact_structure,
    redact_text,
)
from web.feature_routes import router as feature_router  # noqa: E402
from web.editor_routes import router as editor_router  # noqa: E402
from web.job_routes import router as job_router  # noqa: E402
from web.system_routes import router as system_router  # noqa: E402
from web.update_service import UpdateService  # noqa: E402
from web.job_store import JobStore  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _shutdown_requested.clear()
    _job_store.reopen()
    _ensure_job_executor()
    try:
        if _auto_resume:
            # Recovery is a bounded metadata pass; enqueue recovered work before
            # accepting requests so the SQLite queue is authoritative from the
            # first client connection. Actual rendering runs in the worker pool.
            _resume_interrupted_jobs()
        yield
    finally:
        _shutdown_job_executor()
        _job_store.close()


app = FastAPI(
    title="Shorts Studio",
    version=__version__,
    description="Local-first video highlight extraction, editing, and export workspace.",
    contact={"name": "Shorts Studio", "url": "https://github.com/wiifhub/AI-Youtube-Shorts-Generator"},
    license_info={"name": "MIT"},
    openapi_tags=[
        {"name": "system", "description": "Health, diagnostics, setup, and shutdown."},
        {"name": "projects", "description": "Create, inspect, edit, and export projects."},
        {"name": "logs", "description": "Browse bounded, credential-redacted project activity."},
        {"name": "media", "description": "Upload and stream source or generated media."},
        {"name": "updates", "description": "Check and apply releases from the wiifhub repository."},
    ],
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.include_router(system_router)
app.include_router(feature_router, prefix="/api")
app.include_router(job_router)
app.include_router(editor_router)

_cors_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("SHORTS_CORS_ORIGINS", "").split(",")
    if origin.strip() and origin.strip() != "*"
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Shorts-Token", "X-CSRF-Token"],
    )

_logger = logging.getLogger("shorts_studio")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalize FastAPI and Starlette HTTP errors for the frontend and API clients."""
    detail = exc.detail
    if isinstance(detail, dict):
        message = detail.get("error") or detail.get("message") or detail.get("detail") or "Request failed"
        code = detail.get("code") or f"http_{exc.status_code}"
        extra = {key: value for key, value in detail.items() if key not in {"error", "message", "detail", "code"}}
    else:
        message = str(detail or "Request failed")
        code = f"http_{exc.status_code}"
        extra = {}
    return error_response(redact_text(message), code, exc.status_code, **redact_structure(extra))


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return machine-readable validation details without Starlette's ``detail`` wrapper."""
    return error_response(
        "Request validation failed",
        "validation_error",
        422,
        details=redact_structure(jsonable_encoder(exc.errors())),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Keep unexpected failures safe for users while retaining a server-side traceback."""
    _logger.exception("Unhandled %s error on %s %s", type(exc).__name__, request.method, request.url.path)
    return error_response("Internal server error", "internal_error", 500)


_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.RLock()
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
_jobs_db_path = _output_root / "jobs.sqlite3"
_job_store = JobStore(_jobs_db_path)
_uploads_dir = _output_root / "uploads"
_trash_dir = _output_root / ".trash"
_setup_state_path = _output_root / "studio_state.json"
_brand_presets_path = _output_root / "brand_presets.json"
_cost_rates_path = _output_root / "provider_costs.json"
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
_max_json_bytes = _positive_int_env("SHORTS_MAX_JSON_MB", 2) * 1024 * 1024
_auto_resume = os.getenv("SHORTS_AUTO_RESUME", "true").strip().lower() in {"1", "true", "yes", "on"}
_allow_external_paths = os.getenv("SHORTS_ALLOW_EXTERNAL_PATHS", "false").strip().lower() in {"1", "true", "yes", "on"}
_rate_limit_per_minute = _positive_int_env("SHORTS_RATE_LIMIT_PER_MINUTE", 600)
_upload_rate_limit_per_minute = _positive_int_env("SHORTS_UPLOAD_RATE_LIMIT_PER_MINUTE", 10)
_job_rate_limit_per_minute = _positive_int_env("SHORTS_JOB_RATE_LIMIT_PER_MINUTE", 30)
_rate_limiter = SlidingWindowLimiter(_rate_limit_per_minute)
_upload_rate_limiter = SlidingWindowLimiter(_upload_rate_limit_per_minute)
_job_rate_limiter = SlidingWindowLimiter(_job_rate_limit_per_minute)
_job_executor: Optional[ThreadPoolExecutor] = None
_job_futures: Dict[str, Future[Any]] = {}
_process_lock = threading.RLock()
_job_processes: Dict[str, Dict[int, Any]] = {}
_shutdown_requested = threading.Event()
_bound_server: Any = None
_media_slots = threading.Semaphore(_positive_int_env("SHORTS_MAX_MEDIA_OPERATIONS", 2))
_JOB_SCHEMA_VERSION = 2

_APP_VERSION = os.getenv("SHORTS_STUDIO_VERSION", __version__).strip().lstrip("v") or __version__
_GITHUB_REPO = "wiifhub/AI-Youtube-Shorts-Generator"
_require_signed_updates = os.getenv("SHORTS_REQUIRE_SIGNED_UPDATES", "true").strip().lower() in {"1", "true", "yes", "on"}
_max_update_bytes = _positive_int_env("SHORTS_MAX_UPDATE_MB", 4096) * 1024 * 1024
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
_update_service = UpdateService(
    repo=_GITHUB_REPO,
    current_version=_APP_VERSION,
    data_root=Path(os.getenv("SHORTS_STUDIO_DATA_DIR") or _output_root.parent).expanduser(),
    state_setter=lambda **values: _set_update_state(**values),
    state_getter=lambda: dict(_update_state),
    max_bytes=_max_update_bytes,
    require_digest=_require_signed_updates,
)


def _nonnegative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError, OverflowError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


_min_free_gb = _nonnegative_float_env("SHORTS_MIN_FREE_GB", 0.5)


@app.middleware("http")
async def request_limits(request: Request, call_next: Any):
    """Reject oversized JSON before parsing while leaving streaming uploads to their own guard."""
    raw_length = request.headers.get("content-length")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "application/json" and not raw_length:
        # Chunked JSON has no Content-Length header. Request.body() is cached
        # by Starlette, so endpoint parsing still receives the same payload.
        body = await request.body()
        if len(body) > _max_json_bytes:
            return error_response(
                f"JSON request is too large (maximum {_max_json_bytes // (1024 * 1024)} MB)",
                "request_too_large",
                413,
            )
    if raw_length:
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError):
            return error_response("Content-Length must be an integer", "invalid_content_length", 400)
        if content_length < 0:
            return error_response("Content-Length cannot be negative", "invalid_content_length", 400)
        if content_type == "application/json" and content_length > _max_json_bytes:
            return error_response(
                f"JSON request is too large (maximum {_max_json_bytes // (1024 * 1024)} MB)",
                "request_too_large",
                413,
            )
        if content_type and content_type != "application/json" and not content_type.startswith("multipart/"):
            if content_length > 8 * 1024 * 1024:
                return error_response("Request body is too large", "request_too_large", 413)
    return await call_next(request)


@app.middleware("http")
async def security_middleware(request: Request, call_next: Any):
    """Protect remote deployments and throttle expensive local endpoints.

    Authentication is opt-in through ``SHORTS_API_TOKEN`` so the packaged
    loopback desktop experience remains one-click.  Once configured, every
    API route except health/login/status requires a bearer header, token header,
    or the secure session cookie issued by ``/api/auth/login``.
    """
    path = request.url.path
    public = path in {"/api/health", "/healthz", "/api/auth/status", "/api/auth/login"} or not path.startswith("/api/")
    if auth_enabled() and not public and not authorized(request):
        return error_response("Authentication required", "auth_required", 401)
    if auth_enabled() and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and request.cookies.get("shorts_token"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        # SameSite=Strict is the primary protection; this origin check covers
        # deployments that place the UI behind a reverse proxy.
        if origin:
            parsed_origin = urlparse(origin)
            if parsed_origin.netloc and parsed_origin.netloc != request.url.netloc:
                return error_response("Cross-site mutation blocked", "csrf_failed", 403)
    if path.startswith("/api/") and path not in {"/api/health", "/api/auth/status"}:
        limiter = _rate_limiter
        limit = None
        if path == "/api/uploads":
            limiter = _upload_rate_limiter
            limit = _upload_rate_limit_per_minute
        elif path in {"/api/jobs", "/api/jobs/batch"}:
            limiter = _job_rate_limiter
            limit = _job_rate_limit_per_minute
        allowed, retry_after = limiter.allow(f"{client_key(request)}:{path}", limit)
        if not allowed:
            return rate_limit_response(retry_after)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'",
    )
    if os.getenv("SHORTS_STRUCTURED_LOGS", "false").strip().lower() in {"1", "true", "yes", "on"}:
        _logger.info("request method=%s path=%s status=%s", request.method, path, response.status_code)
    return response


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
        output_dir = _job_output_dir(job)
        candidate.relative_to(output_dir)
    except (OSError, RuntimeError, ValueError, TypeError):
        return None
    return candidate


def _job_output_dir(job: Dict[str, Any]) -> Path:
    """Return a job output directory inside the configured trust boundary."""
    job_id = str(job.get("id") or "")
    # Job records can be restored from a user-supplied backup.  Keep the
    # fallback itself inside ``jobs`` even if a malformed record somehow
    # reaches this helper before normal ID validation runs.
    safe_job_id = job_id if _job_id_pattern.fullmatch(job_id) else "invalid-job"
    fallback = (_jobs_dir / safe_job_id).expanduser().resolve()
    raw = job.get("output_dir")
    if not raw:
        return fallback
    try:
        candidate = Path(str(raw)).expanduser().resolve()
        if _allow_external_paths:
            return candidate
        candidate.relative_to(_output_root.resolve())
        return candidate
    except (OSError, RuntimeError, ValueError, TypeError):
        return fallback


def _job_source_path(job: Dict[str, Any], value: Any) -> Optional[Path]:
    """Resolve a local source only when it remains inside the output root."""
    if not value or str(value).startswith(("http://", "https://")):
        return None
    try:
        candidate = Path(str(value)).expanduser().resolve()
        if not _allow_external_paths:
            candidate.relative_to(_output_root.resolve())
        return candidate if candidate.is_file() else None
    except (OSError, RuntimeError, ValueError, TypeError):
        return None


def _job_path(job_id: str) -> Path:
    safe_id = str(job_id)
    if not _job_id_pattern.fullmatch(safe_id):
        raise ValueError("invalid job id")
    return _jobs_dir / f"{safe_id}.json"


def _persist_job_locked(job: Dict[str, Any]) -> None:
    """Persist one job atomically to SQLite and a portable JSON mirror.

    SQLite is the durable queue/state source.  JSON remains intentionally
    available for human inspection and the metadata backup format.
    """
    _jobs_dir.mkdir(parents=True, exist_ok=True)
    _job_store.reopen()
    job["schema_version"] = _JOB_SCHEMA_VERSION
    job["updated_at"] = time.time()
    _job_store.save(job)
    path = _job_path(str(job["id"]))
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(job, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _job_cancelled(job_id: str) -> bool:
    """Return true for explicit cancellation or coordinated application stop."""
    if _shutdown_requested.is_set():
        return True
    with _lock:
        event = _cancel_events.get(str(job_id))
        job = _jobs.get(str(job_id))
        return bool(event and event.is_set()) or str((job or {}).get("status")) == "cancelled"


@contextmanager
def _media_operation(job_id: str):
    """Bound waveform/preview work and make it cancel-aware like jobs."""
    while True:
        if _job_cancelled(job_id):
            raise RuntimeError("Job cancelled")
        if _media_slots.acquire(timeout=0.25):
            break
    try:
        if _job_cancelled(job_id):
            raise RuntimeError("Job cancelled")
        yield
    finally:
        _media_slots.release()


def _run_media_command(job_id: str, args: List[str], timeout: float = 90.0) -> subprocess.CompletedProcess[Any]:
    """Run an editor subprocess with process tracking, timeout, and cancel support."""
    with _media_operation(job_id):
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _register_job_process(job_id, process)
        started = time.monotonic()
        try:
            while True:
                if _job_cancelled(job_id):
                    _terminate_job_processes(job_id)
                    raise RuntimeError("Job cancelled")
                if time.monotonic() - started > timeout:
                    _terminate_job_processes(job_id)
                    raise RuntimeError("media operation timed out")
                try:
                    stdout, stderr = process.communicate(timeout=0.25)
                    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            _unregister_job_process(job_id, process)


def bind_server(server: Any) -> None:
    """Bind the packaged Uvicorn server so the shutdown route can stop it."""
    global _bound_server
    _bound_server = server


def _request_shutdown() -> Dict[str, Any]:
    """Stop accepting work, persist interrupted jobs, and terminate children."""
    _shutdown_requested.set()
    interrupted: List[str] = []
    with _lock:
        for job_id, job in _jobs.items():
            if str(job.get("status")) not in {"queued", "running"}:
                continue
            job["status"] = "interrupted"
            job["stage"] = "interrupted"
            job["message"] = "Interrupted while Shorts Studio was shutting down; it can be resumed."
            job["error"] = None
            job["checkpoint"] = {"stage": "interrupted", "progress": job.get("progress", 0), "message": job["message"]}
            _append_job_log(job, "interrupted", job["message"])
            _persist_job_locked(job)
            event = _cancel_events.setdefault(job_id, threading.Event())
            event.set()
            future = _job_futures.get(job_id)
            if future:
                future.cancel()
            interrupted.append(job_id)
    for job_id in interrupted:
        _terminate_job_processes(job_id)
    if _bound_server is not None:
        try:
            _bound_server.should_exit = True
        except Exception:
            pass
    return {"status": "shutting_down", "interrupted_jobs": len(interrupted)}


def _load_persisted_jobs() -> None:
    """Restore jobs from SQLite (with legacy JSON migration) after a restart."""
    _jobs_dir.mkdir(parents=True, exist_ok=True)
    records: Dict[str, tuple[float, Dict[str, Any]]] = {}
    # SQLite is the primary source.  Loading the whole payload keeps recovery
    # compatible with older records while indexed status/updated columns make
    # future maintenance queries cheap.
    for raw in _job_store.load_all():
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        job_id = str(raw.get("id"))
        if not _job_id_pattern.fullmatch(job_id):
            continue
        try:
            updated = float(raw.get("updated_at") or raw.get("created_at") or 0.0)
        except (TypeError, ValueError, OverflowError):
            updated = 0.0
        records[job_id] = (updated, raw)

    # Read legacy/mutable JSON mirrors too.  This makes an upgrade from v0.9
    # lossless and lets a manually restored JSON file be picked up once.
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
        try:
            updated = float(job.get("updated_at") or job.get("created_at") or path.stat().st_mtime)
        except (OSError, TypeError, ValueError, OverflowError):
            updated = 0.0
        existing = records.get(job_id)
        if existing and existing[0] > updated:
            continue
        records[job_id] = (updated, job)

    for _, job in sorted(records.values(), key=lambda item: item[0], reverse=True):
        job_id = str(job["id"])
        job["id"] = job_id
        # A JSON/SQLite record is user-editable state, not an authorization
        # boundary. Normalize directories and local sources before any media
        # endpoint or recovery worker can use them.
        job["output_dir"] = str(_job_output_dir(job))
        persisted_source = job.get("raw_source_video_url")
        if persisted_source and not str(persisted_source).startswith(("http://", "https://")):
            safe_source = _job_source_path(job, persisted_source)
            job["raw_source_video_url"] = str(safe_source) if safe_source else None
        # Persisted records from pre-queue releases did not carry a schema
        # marker.  Upgrade them in memory with safe defaults before serving.
        job["schema_version"] = _JOB_SCHEMA_VERSION
        job.setdefault("progress", 0)
        job.setdefault("elapsed_seconds", None)
        job.setdefault("eta_seconds", None)
        job.setdefault(
            "checkpoint",
            {
                "stage": str(job.get("stage") or "unknown"),
                "progress": job.get("progress", 0),
                "message": str(job.get("message") or "Recovered project")[:400],
            },
        )
        if not isinstance(job.get("logs"), list):
            job["logs"] = []
        try:
            created_at = float(job.get("created_at") or job.get("updated_at") or time.time())
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
        if job.get("status") in {"running", "queued"}:
            message = "Interrupted when Shorts Studio stopped; it can be resumed."
            job["status"] = "interrupted"
            job["stage"] = "interrupted"
            job["message"] = message
            job["error"] = None
            job["logs"] = list(job["logs"])[-79:]
            job["logs"].append({"t": time.time(), "stage": "interrupted", "message": message})
        _jobs[job_id] = job
        # Migrate legacy JSON records and persist the interrupted checkpoint in
        # both stores so the next restart has exactly the same state.
        try:
            _persist_job_locked(job)
        except (OSError, ValueError, TypeError):
            _logger.exception("Could not migrate persisted job %s", job_id)


_load_persisted_jobs()


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
    supplied = _job_credentials.get(job_id or "") if job_id else None
    credentials = (
        {key: secret for key, secret in supplied.items() if key != "llm_provider"}
        if supplied
        else None
    )
    return redact_text(value, credentials, max_length=4000)


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
        "project": _redact_log_text(str(project or "Untitled project"))[:160],
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
            entry for entry in entries if search in f"{entry['project']} {entry['stage']} {entry['message']}".casefold()
        ]
    return entries


def _job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    status = str(job.get("status") or "unknown")
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    safe_request = redact_structure(request)
    try:
        progress = max(0, min(100, int(float(job.get("progress") or 0))))
    except (TypeError, ValueError, OverflowError):
        progress = 0
    try:
        schema_version = int(job.get("schema_version") or _JOB_SCHEMA_VERSION)
    except (TypeError, ValueError, OverflowError):
        schema_version = _JOB_SCHEMA_VERSION
    return {
        "id": str(job.get("id") or ""),
        "status": status,
        "stage": str(job.get("stage") or "unknown"),
        "message": _redact_log_text(job.get("message"), str(job.get("id") or "")),
        "progress": progress,
        "elapsed_seconds": job.get("elapsed_seconds"),
        "eta_seconds": job.get("eta_seconds"),
        "checkpoint": redact_structure(job.get("checkpoint")),
        "schema_version": schema_version,
        "logs": [
            safe
            for safe in (
                {
                    **redact_structure(entry),
                    "stage": str(entry.get("stage") or "info")[:32],
                    "message": _redact_log_text(entry.get("message"), str(job.get("id") or "")),
                }
                for entry in ((job.get("logs") if isinstance(job.get("logs"), list) else [])[-80:])
                if isinstance(entry, dict)
            )
        ],
        "error": _redact_log_text(job.get("error"), str(job.get("id") or "")) if job.get("error") else None,
        "result": redact_structure(job.get("result")),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at", job.get("created_at")),
        "name": _redact_log_text(job.get("name") or request.get("url") or job.get("id") or "Untitled project"),
        "archived": bool(job.get("archived", False)),
        "can_retry": status in {"error", "cancelled", "interrupted", "draft"} and bool(request.get("url")),
        "request": safe_request,
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
    try:
        root = _job_output_dir(job)
        if not root.is_dir():
            return
        scratch_suffixes = (
            ".part",
            ".cut.mp4",
            ".base.mp4",
            ".render.mp4",
            ".audio.mp4",
            ".jump.mp4",
            ".extras.mp4",
            ".branded.mp4",
            ".silent.mp4",
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
        if provider not in {"openai", "gemini", "ollama"}:
            raise HTTPException(400, "LLM provider must be openai, gemini, or ollama")
        values["llm_provider"] = provider
    return values


def _validate_mode_capabilities(req: JobRequest) -> None:
    """Reject settings that a hosted MuAPI render cannot honor silently."""
    if req.mode != "api":
        return
    parsed = urlparse(req.url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "API mode requires an http(s) video URL; choose Local mode for a file path.")
    unsupported = []
    if req.caption_style != "bold":
        unsupported.append("caption_style")
    if req.caption_position != "bottom":
        unsupported.append("caption_position")
    if req.caption_font != "Arial":
        unsupported.append("caption_font")
    if req.caption_size:
        unsupported.append("caption_size")
    if req.caption_color:
        unsupported.append("caption_color")
    if req.remove_silence:
        unsupported.append("remove_silence")
    if req.normalize_audio:
        unsupported.append("normalize_audio")
    if req.denoise_audio:
        unsupported.append("denoise_audio")
    if req.remove_filler_words:
        unsupported.append("remove_filler_words")
    if req.background_music:
        unsupported.append("background_music")
    if req.music_volume != 0.18:
        unsupported.append("music_volume")
    if req.music_fade_in:
        unsupported.append("music_fade_in")
    if req.music_fade_out:
        unsupported.append("music_fade_out")
    if req.watermark:
        unsupported.append("watermark")
    if req.intro:
        unsupported.append("intro")
    if req.outro:
        unsupported.append("outro")
    if req.jump_cuts:
        unsupported.append("jump_cuts")
    if req.layout != "single":
        unsupported.append("layout")
    if req.fit_mode != "crop":
        unsupported.append("fit_mode")
    if req.zoom != 1.0:
        unsupported.append("zoom")
    if req.auto_reframe is not True:
        unsupported.append("auto_reframe")
    if req.crop_position != 0.5:
        unsupported.append("crop_position")
    if req.output_height not in {0, 1920}:
        unsupported.append("output_height")
    if req.save_folder:
        unsupported.append("save_folder")
    if req.whisper_model:
        unsupported.append("whisper_model")
    if req.whisper_device:
        unsupported.append("whisper_device")
    if req.cuts:
        unsupported.append("cuts")
    if req.llm_provider or req.llm_model is not None or req.llm_temperature != 0.2:
        unsupported.append("local_llm_options")
    if unsupported:
        names = ", ".join(unsupported)
        raise HTTPException(400, f"API mode does not support {names}; switch to Local mode for these controls.")


def _validate_local_paths(req: JobRequest) -> None:
    """Keep a remotely reachable worker from reading arbitrary host paths."""
    if req.mode != "local":
        return
    source = str(req.url or "").strip()
    parsed = urlparse(source)
    if parsed.scheme.lower() in {"http", "https"}:
        try:
            validate_remote_source(source)
        except ValueError as exc:
            raise HTTPException(400, f"remote source is not allowed: {exc}") from exc
    if _allow_external_paths:
        return
    allowed_root = _output_root.resolve()

    def check(value: Optional[str], label: str, *, must_exist: bool) -> None:
        if not value:
            return
        try:
            candidate = Path(str(value)).expanduser().resolve()
            candidate.relative_to(allowed_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                400,
                f"{label} must be inside the configured output folder; set SHORTS_ALLOW_EXTERNAL_PATHS=true only for a trusted local desktop session.",
            ) from exc
        if must_exist and not candidate.is_file():
            raise HTTPException(400, f"{label} does not exist: {value}")

    if parsed.scheme.lower() not in {"http", "https"}:
        local_source = source
        if parsed.scheme.lower() == "file":
            local_source = unquote(parsed.path)
            if os.name == "nt" and re.match(r"^/[A-Za-z]:", local_source):
                local_source = local_source[1:]
        check(local_source, "source path", must_exist=True)
    check(req.save_folder, "save_folder", must_exist=False)
    check(req.background_music, "background_music", must_exist=True)
    check(req.watermark, "watermark", must_exist=True)
    check(req.intro, "intro", must_exist=True)
    check(req.outro, "outro", must_exist=True)


def _ensure_job_executor() -> ThreadPoolExecutor:
    """Create the bounded worker pool lazily so TestClient and restarts recover."""
    global _job_executor
    if _job_executor is None:
        _job_executor = ThreadPoolExecutor(max_workers=_max_concurrent_jobs, thread_name_prefix="shorts-studio-job")
    return _job_executor


def _shutdown_job_executor() -> None:
    global _job_executor
    _request_shutdown()
    executor = _job_executor
    _job_executor = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def _register_job_process(job_id: str, process: Any) -> None:
    """Track a render child so cancellation can terminate FFmpeg promptly."""
    try:
        pid = int(getattr(process, "pid"))
    except (AttributeError, TypeError, ValueError):
        return
    with _process_lock:
        _job_processes.setdefault(job_id, {})[pid] = process


def _unregister_job_process(job_id: str, process: Any) -> None:
    try:
        pid = int(getattr(process, "pid"))
    except (AttributeError, TypeError, ValueError):
        return
    with _process_lock:
        processes = _job_processes.get(job_id)
        if not processes:
            return
        processes.pop(pid, None)
        if not processes:
            _job_processes.pop(job_id, None)


def _terminate_job_processes(job_id: str) -> int:
    """Terminate all child processes belonging to a job and return a count."""
    with _process_lock:
        processes = list((_job_processes.get(job_id) or {}).values())
    terminated = 0
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
                terminated += 1
        except (AttributeError, OSError, ProcessLookupError):
            continue
    deadline = time.monotonic() + 2.0
    for process in processes:
        try:
            remaining = max(0.0, deadline - time.monotonic())
            process.wait(timeout=remaining)
        except (AttributeError, OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=1.0)
            except (AttributeError, OSError, ProcessLookupError, subprocess.TimeoutExpired):
                pass
    with _process_lock:
        _job_processes.pop(job_id, None)
    return terminated


def _start_job_thread(
    job_id: str,
    req: JobRequest,
    credentials: Optional[Dict[str, str]] = None,
) -> None:
    future = _ensure_job_executor().submit(_run_job, job_id, req, dict(credentials or {}))
    with _lock:
        _job_futures[job_id] = future

    def clear_finished(_future: Future[Any]) -> None:
        with _lock:
            if _job_futures.get(job_id) is _future:
                _job_futures.pop(job_id, None)

    future.add_done_callback(clear_finished)


def _run_job(
    job_id: str,
    req: JobRequest,
    credentials: Optional[Dict[str, str]] = None,
) -> None:
    slot_acquired = False
    with _lock:
        _cancel_events.setdefault(job_id, threading.Event())
    stage_weights = {
        "queued": 0,
        "download": 15,
        "analyze": 25,
        "transcribe": 45,
        "rank": 60,
        "crop": 85,
        "metadata": 95,
        "done": 100,
    }
    started_at = time.time()

    def progress(stage: str, message: str) -> None:
        with _lock:
            job = _jobs[job_id]
            if _job_cancelled(job_id):
                raise RuntimeError("Job cancelled")
            job["stage"] = stage
            job["message"] = message
            job["progress"] = stage_weights.get(str(stage).lower(), job.get("progress", 0))
            elapsed = max(0.0, time.time() - started_at)
            job["elapsed_seconds"] = round(elapsed, 1)
            current_progress = float(job.get("progress") or 0)
            if current_progress > 0 and current_progress < 100:
                job["eta_seconds"] = round(max(0.0, elapsed * (100.0 - current_progress) / current_progress), 1)
            else:
                job["eta_seconds"] = None
            _append_job_log(job, stage, message)
            job["checkpoint"] = {
                "stage": str(stage),
                "progress": job["progress"],
                "message": str(message)[:400],
                "updated_at": time.time(),
            }
            _persist_job_locked(job)

    try:
        while not slot_acquired:
            if _job_cancelled(job_id):
                raise RuntimeError("Job cancelled")
            slot_acquired = _job_slots.acquire(timeout=0.25)
        with _lock:
            if job_id in _jobs and _jobs[job_id].get("status") not in {"cancelled", "interrupted"}:
                _jobs[job_id]["status"] = "running"
                _jobs[job_id]["progress"] = 0
                _jobs[job_id]["eta_seconds"] = None
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
        with runtime_job_control(
            cancel_check=lambda: _job_cancelled(job_id),
            register_process=lambda process: _register_job_process(job_id, process),
            unregister_process=lambda process: _unregister_job_process(job_id, process),
        ):
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
                    llm_model=req.llm_model,
                    llm_temperature=req.llm_temperature,
                    music_volume=req.music_volume,
                    music_fade_in=req.music_fade_in,
                    music_fade_out=req.music_fade_out,
                    cuts=[cut.model_dump() for cut in req.cuts],
                    cancel_check=lambda: _job_cancelled(job_id),
                    cost_rates=_load_cost_rates(),
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
            "llm": _dict_value(result.get("llm")),
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
            if job.get("status") in {"cancelled", "interrupted"} or _shutdown_requested.is_set():
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
            if job.get("status") in {"cancelled", "interrupted"} or _shutdown_requested.is_set():
                if _shutdown_requested.is_set() and job.get("status") == "running":
                    job["status"] = "interrupted"
                    job["stage"] = "interrupted"
                    job["message"] = "Interrupted while Shorts Studio was shutting down; it can be resumed."
                    job["error"] = None
                    _persist_job_locked(job)
                _cleanup_job_temporary_files(job)
                return
            safe_error = _redact_log_text(str(exc), job_id)
            job["status"] = "error"
            job["stage"] = "error"
            job["message"] = safe_error
            job["error"] = safe_error
            _append_job_log(job, "error", safe_error)
            _persist_job_locked(job)
            _cleanup_job_temporary_files(job)
    finally:
        _terminate_job_processes(job_id)
        if slot_acquired:
            _job_slots.release()
        with _lock:
            _cancel_events.pop(job_id, None)
            _job_credentials.pop(job_id, None)
            _job_futures.pop(job_id, None)


def _enqueue_job(
    req: JobRequest,
    credentials: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if req.mode not in ("api", "local"):
        raise HTTPException(400, "mode must be api or local")
    if not req.url or not req.url.strip():
        raise HTTPException(400, "url/path cannot be blank")
    _validate_mode_capabilities(req)
    _validate_local_paths(req)
    if req.llm_provider is not None:
        provider = str(req.llm_provider).strip().lower()
        if provider not in {"openai", "gemini", "ollama"}:
            raise HTTPException(400, "LLM provider must be openai, gemini, or ollama")
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
        free_gb = shutil.disk_usage(_output_root).free / (1024**3)
    except OSError:
        free_gb = 0.0
    if _min_free_gb and free_gb < _min_free_gb:
        raise HTTPException(
            507, f"not enough free disk space ({free_gb:.2f} GB available; {_min_free_gb:.2f} GB required)"
        )
    job_id = uuid.uuid4().hex[:12]
    default_name = re.sub(r"[^A-Za-z0-9 _-]+", " ", req.url.rsplit("/", 1)[-1]).strip()
    default_name = " ".join(default_name.split())[:80] or "Untitled project"
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "schema_version": _JOB_SCHEMA_VERSION,
            "name": default_name,
            "status": "queued",
            "stage": "queued",
            "message": "Queued",
            "progress": 0,
            "elapsed_seconds": None,
            "eta_seconds": None,
            "checkpoint": {"stage": "queued", "progress": 0, "message": "Queued"},
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
                "llm_model": req.llm_model,
                "llm_temperature": req.llm_temperature,
                "music_volume": req.music_volume,
                "music_fade_in": req.music_fade_in,
                "music_fade_out": req.music_fade_out,
                "cuts": [cut.model_dump() for cut in req.cuts],
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
            try:
                _validate_mode_capabilities(req)
                _validate_local_paths(req)
            except Exception as exc:
                job["status"] = "error"
                job["stage"] = "error"
                job["message"] = f"Saved project settings are not supported: {exc}"
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




def _json_file_size(path: Path) -> int:
    try:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


def _transcript_cache_files() -> List[Path]:
    """Find renderer-owned transcript sidecars under the configured output."""
    files: List[Path] = []
    if not _jobs_dir.is_dir():
        return files
    for item in _jobs_dir.rglob("*"):
        if not item.is_file():
            continue
        name = item.name.lower()
        # Normal cache names are content-addressed and start with
        # ``transcript_``. Do not classify arbitrary creator subtitle files in
        # the output folder as disposable cache data.
        if name.startswith("transcript_") and name.endswith(".srt"):
            files.append(item)
        elif name.startswith("transcript_") and name.endswith((".words.json", ".meta.json")):
            files.append(item)
    return files


def _model_cache_roots() -> List[Path]:
    """Return only known faster-whisper/Hugging Face cache roots."""
    candidates = [
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        candidates.append(Path(local_appdata) / "huggingface" / "hub")
    for env_name in ("HF_HOME", "HUGGINGFACE_HUB_CACHE"):
        configured = os.getenv(env_name, "").strip()
        if configured:
            base = Path(configured).expanduser()
            candidates.extend((base, base / "hub"))
    unique: List[Path] = []
    seen = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _safe_tree_size(root: Path) -> int:
    return _json_file_size(root) if root.is_dir() else 0


def _storage_report() -> Dict[str, Any]:
    roots = {
        "jobs": _jobs_dir,
        "uploads": _uploads_dir,
        "trash": _trash_dir,
        "previews": _output_root,
    }
    sizes: Dict[str, int] = {}
    for name, root in roots.items():
        if name == "previews":
            sizes[name] = sum(
                item.stat().st_size
                for item in root.rglob("*")
                if item.is_file() and ("previews" in item.parts or item.name == "waveform.json")
            )
        else:
            sizes[name] = _json_file_size(root) if root.is_dir() else 0
    sizes["transcript_cache"] = sum(
        item.stat().st_size for item in _transcript_cache_files() if item.exists()
    )
    sizes["job_database"] = _jobs_db_path.stat().st_size if _jobs_db_path.is_file() else 0
    sizes["model_cache"] = sum(_safe_tree_size(root) for root in _model_cache_roots())
    try:
        free = shutil.disk_usage(_output_root).free
    except OSError:
        free = 0
    return {
        "root": str(_output_root),
        "free_bytes": free,
        "free_gb": round(free / (1024**3), 2),
        "items": {name: {"bytes": value, "gb": round(value / (1024**3), 3)} for name, value in sizes.items()},
        "retention": "Generated previews, waveforms, transcript caches, and deleted project records can be cleaned by age; source media and model caches are preserved unless explicitly selected.",
        "database": str(_jobs_db_path),
        "model_cache_roots": [str(root) for root in _model_cache_roots() if root.is_dir()],
    }


def _load_cost_rates() -> Dict[str, Dict[str, float]]:
    """Load creator-entered rates, falling back to environment values."""
    defaults = rates_from_environment()
    try:
        raw = json.loads(_cost_rates_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    for provider in defaults:
        for direction in ("input", "output"):
            key = f"{provider}_{direction}_usd_per_million"
            if key in raw:
                try:
                    value = float(raw[key])
                except (TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(value) and value >= 0:
                    defaults[provider][f"{direction}_usd_per_million"] = value
    return defaults


def _cost_rates_public() -> Dict[str, float]:
    nested = _load_cost_rates()
    return {
        f"{provider}_{direction}_usd_per_million": nested[provider][f"{direction}_usd_per_million"]
        for provider in nested
        for direction in ("input", "output")
    }


def _save_cost_rates(model: ProviderCostRates) -> Dict[str, float]:
    values = model.model_dump()
    _output_root.mkdir(parents=True, exist_ok=True)
    temporary = _cost_rates_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, _cost_rates_path)
    return {str(key): float(value) for key, value in values.items()}


def _load_brand_presets() -> Dict[str, Dict[str, Any]]:
    try:
        raw = json.loads(_brand_presets_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(name): value for name, value in raw.items() if isinstance(value, dict)}


def _save_brand_presets(presets: Dict[str, Dict[str, Any]]) -> None:
    _output_root.mkdir(parents=True, exist_ok=True)
    temporary = _brand_presets_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, _brand_presets_path)

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
    roots = [Path.home() / ".cache" / "huggingface" / "hub"]
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        roots.append(Path(local_appdata) / "huggingface" / "hub")
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
        free_gb = round(usage.free / (1024**3), 2)
    except OSError:
        free_gb = 0.0
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    gpu = gpu_status()
    local_modules = {name: bool(importlib.util.find_spec(name)) for name in ("yt_dlp", "faster_whisper", "cv2")}
    provider = str(LLM_PROVIDER or "openai").strip().lower()
    provider_key = (
        bool(OPENAI_API_KEY)
        if provider == "openai"
        else bool(GEMINI_API_KEY)
        if provider == "gemini"
        else provider == "ollama"
    )
    warnings = []
    if not ffmpeg:
        warnings.append("FFmpeg is not available; local rendering cannot start until it is installed or bundled.")
    if not ffprobe:
        warnings.append("FFprobe is not available; media diagnostics will be limited.")
    missing_local = [name for name, ready in local_modules.items() if not ready]
    if missing_local:
        warnings.append("Local dependencies missing: " + ", ".join(missing_local) + ". Install requirements-local.txt before rendering.")
    if free_gb < _min_free_gb:
        warnings.append(f"Only {free_gb:.2f} GB of free disk space is available.")
    if provider not in {"openai", "gemini", "ollama"}:
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
            "dependencies": local_modules,
        },
        "keys": {
            "muapi_configured": bool(MUAPI_API_KEY),
            "openai_configured": bool(OPENAI_API_KEY),
            "gemini_configured": bool(GEMINI_API_KEY),
            "selected_provider": provider,
            "selected_provider_configured": provider_key,
            "offline_fallback": bool(LOCAL_HEURISTIC_FALLBACK),
        },
        "storage": {
            "output_root": str(_output_root),
            "database": str(_jobs_db_path),
            "free_disk_gb": free_gb,
            "minimum_free_gb": _min_free_gb,
            "items": _storage_report().get("items", {}),
        },
        "warnings": warnings,
        "ready_for_local": bool(ffmpeg) and free_gb >= _min_free_gb and all(local_modules.values()),
    }


def _version_tuple(value: Any) -> tuple[int, int, int]:
    return _update_service.version_tuple(value)


def _github_release() -> Dict[str, Any]:
    return _update_service.github_release()


def _package_root() -> Path:
    return _update_service.package_root()


def _package_root_writable() -> bool:
    return _update_service.package_root_writable()


def _update_dir() -> Path:
    return _update_service.update_dir()


def _select_release_asset(release: Dict[str, Any]) -> Optional[Dict[str, str]]:
    return _update_service.select_release_asset(release)


def _release_info(release: Dict[str, Any]) -> Dict[str, Any]:
    return _update_service.release_info(release)


def _set_update_state(**values: Any) -> Dict[str, Any]:
    with _update_lock:
        safe_values = dict(values)
        for key in ("message", "error"):
            if key in safe_values and safe_values[key] is not None:
                safe_values[key] = redact_text(safe_values[key])
        _update_state.update(safe_values)
        return dict(_update_state)


def main() -> None:
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=7860, reload=False)


if __name__ == "__main__":
    main()
