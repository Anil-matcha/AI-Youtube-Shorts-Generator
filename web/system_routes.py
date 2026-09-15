"""System-facing routes for the Shorts Studio web service.

The stateful application module owns configuration and worker lifecycle; this
router keeps authentication, diagnostics, uploads, setup, and update flows
readable and independently testable.  State is resolved lazily to avoid an
import cycle while FastAPI registers the routes.
"""

from __future__ import annotations

import hmac
import importlib
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from web.models import AuthLogin, OpenFolderRequest, SetupStateUpdate
from web.security import LoginAttemptLimiter, authorized, auth_enabled, client_key, configured_token, error_response, redact_text


router = APIRouter()
_login_attempts = LoginAttemptLimiter()


def _studio() -> Any:
    """Resolve the stateful app module only when a request is handled."""
    return importlib.import_module("web.app")


@router.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(_studio().STATIC / "index.html", media_type="text/html")


@router.get("/api/auth/status", tags=["system"])
def auth_status(request: Request) -> Dict[str, Any]:
    """Report whether this instance requires the optional API token."""
    return {"enabled": auth_enabled(), "authenticated": authorized(request)}


@router.post("/api/auth/login", tags=["system"])
def auth_login(request: Request, credentials: AuthLogin) -> JSONResponse:
    """Exchange the configured token for a short-lived HttpOnly session cookie."""
    expected = configured_token()
    key = client_key(request)
    retry_after = _login_attempts.blocked(key)
    if retry_after:
        response = error_response("Too many failed login attempts; try again later.", "auth_locked", 429)
        response.headers["Retry-After"] = str(retry_after)
        return response
    if not expected or not hmac.compare_digest(credentials.token, expected):
        retry_after = _login_attempts.failed(key)
        response = error_response("Invalid access token", "auth_invalid", 401)
        if retry_after:
            response.headers["Retry-After"] = str(retry_after)
        return response
    _login_attempts.success(key)
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie(
        "shorts_token",
        credentials.token,
        max_age=86400,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    response.set_cookie("shorts_csrf", secrets.token_urlsafe(24), max_age=86400, httponly=False, secure=request.url.scheme == "https", samesite="strict")
    return response


@router.post("/api/auth/logout", tags=["system"])
def auth_logout() -> JSONResponse:
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie("shorts_token")
    response.delete_cookie("shorts_csrf")
    return response


@router.post("/api/open-folder")
def open_folder(request: OpenFolderRequest) -> Dict[str, Any]:
    """Open a safe local output folder on desktop builds."""
    studio = _studio()
    if request.job_id:
        with studio._lock:
            job = studio._jobs.get(request.job_id)
            if not job:
                raise HTTPException(404, "job not found")
            folder = studio._job_output_dir(job)
    else:
        folder = studio._output_root
    try:
        folder = folder.expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(400, f"output folder is unavailable: {exc}") from exc
    opened = False
    headless = os.getenv("SHORTS_STUDIO_HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"}
    if not headless:
        try:
            start_file = getattr(os, "startfile", None)
            if os.name == "nt" and callable(start_file):
                start_file(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            opened = True
        except FileNotFoundError:
            opened = False
        except OSError as exc:
            raise HTTPException(500, f"could not open folder: {exc}") from exc
    return {"status": "opened" if opened else "available", "opened": opened, "path": str(folder)}


@router.post("/api/uploads")
async def upload_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Store a browser-uploaded source in the local output area."""
    studio = _studio()
    original_name = Path(file.filename or "video.mp4").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in studio._allowed_upload_extensions:
        allowed = ", ".join(sorted(studio._allowed_upload_extensions))
        raise HTTPException(400, f"unsupported video type; use one of: {allowed}")

    safe_stem = Path(original_name).stem.strip() or "video"
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in safe_stem)
    safe_stem = safe_stem[:120] or "video"
    target = studio._uploads_dir / f"upload_{uuid.uuid4().hex[:12]}_{safe_stem}{suffix}"
    temporary = target.with_suffix(target.suffix + ".part")
    size = 0
    try:
        studio._uploads_dir.mkdir(parents=True, exist_ok=True)
        with temporary.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > studio._max_upload_bytes:
                    raise HTTPException(
                        413,
                        f"file is larger than the {studio._max_upload_bytes // (1024 * 1024)} MB upload limit",
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


@router.get("/api/uploads/{filename}")
def get_upload(filename: str) -> FileResponse:
    """Serve an uploaded source for an optional browser preview."""
    studio = _studio()
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(404, "upload not found")
    path = studio._uploads_dir / safe_name
    if not path.is_file():
        raise HTTPException(404, "upload not found")
    return FileResponse(path, filename=path.name)


@router.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz", tags=["system"])
def healthz() -> Dict[str, str]:
    """Minimal probe for load balancers that must not disclose local paths."""
    return {"status": "ok"}


@router.get("/api/setup")
def setup_report() -> Dict[str, Any]:
    return _studio()._setup_report()


@router.post("/api/setup/prepare")
def prepare_setup(update: Optional[SetupStateUpdate] = None) -> Dict[str, Any]:
    studio = _studio()
    update = update or SetupStateUpdate()
    try:
        studio._output_root.mkdir(parents=True, exist_ok=True)
        studio._jobs_dir.mkdir(parents=True, exist_ok=True)
        studio._uploads_dir.mkdir(parents=True, exist_ok=True)
        state = studio._setup_state()
        state["setup_dismissed"] = bool(update.dismissed)
        state["last_checked_at"] = time.time()
        studio._write_setup_state(state)
    except OSError as exc:
        raise HTTPException(500, f"could not prepare local folders: {exc}") from exc
    return studio._setup_report()


@router.post("/api/setup/dismiss")
def dismiss_setup(update: Optional[SetupStateUpdate] = None) -> Dict[str, Any]:
    return prepare_setup(update)


@router.post("/api/shutdown")
def shutdown() -> Dict[str, Any]:
    """Stop this local-only server (used by the portable launcher Quit button)."""
    return _studio()._request_shutdown()


@router.get("/api/system")
def system_status() -> Dict[str, Any]:
    studio = _studio()
    try:
        usage = shutil.disk_usage(studio._output_root)
        free_disk_gb = round(usage.free / (1024**3), 2)
    except OSError:
        free_disk_gb = 0.0
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "whisper_model": studio.LOCAL_WHISPER_MODEL,
        "whisper_device": studio.LOCAL_WHISPER_DEVICE,
        "gpu": studio.gpu_status(),
        "whisper_models": ["tiny", "base", "small", "medium", "large-v3"],
        "whisper_devices": ["auto", "cpu", "cuda", "mps", "directml", "rocm"],
        "captions_enabled": studio.LOCAL_BURN_CAPTIONS,
        "free_disk_gb": free_disk_gb,
        "max_concurrent_jobs": studio._max_concurrent_jobs,
        "setup": studio._setup_report(),
    }


@router.get("/api/diagnostics")
def diagnostics() -> Dict[str, Any]:
    studio = _studio()
    ffmpeg = shutil.which("ffmpeg")
    with studio._lock:
        counts: Dict[str, int] = {}
        for job in studio._jobs.values():
            status = str(job.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
    return {
        "python": sys.version,
        "ffmpeg_path": ffmpeg,
        "ffmpeg_ready": bool(ffmpeg),
        "output_root": str(studio._output_root),
        "free_disk_gb": round(shutil.disk_usage(studio._output_root).free / (1024**3), 2),
        "job_counts": counts,
        "captions_enabled": studio.LOCAL_BURN_CAPTIONS,
        "setup": studio._setup_report(),
    }


@router.get("/api/update")
def update_check() -> Dict[str, Any]:
    """Check the wiifhub release and describe the in-app update path."""
    studio = _studio()
    try:
        info = studio._release_info(studio._github_release())
        state = studio._set_update_state(
            status="available" if info["update_available"] else "current",
            current_version=info["current_version"],
            latest_version=info["latest_version"],
            progress=0,
            total=0,
            message="Update available" if info["update_available"] else "Shorts Studio is up to date",
            error=None,
        )
        info["state"] = state
        return info
    except Exception as exc:
        safe_error = redact_text(exc)
        state = studio._set_update_state(status="error", message="Update check failed", error=safe_error)
        return {
            "available": False,
            "update_available": False,
            "current_version": studio._APP_VERSION,
            "error": safe_error,
            "code": "update_check_failed",
            "state": state,
        }


@router.get("/api/update/status")
def update_status() -> Dict[str, Any]:
    studio = _studio()
    with studio._update_lock:
        return dict(studio._update_state)


@router.post("/api/update/apply")
def update_apply() -> Dict[str, Any]:
    """Download and apply the newest packaged release, then restart the app."""
    studio = _studio()
    with studio._update_lock:
        if studio._update_state.get("status") in {"checking", "starting", "downloading", "restarting"}:
            return dict(studio._update_state)
    try:
        release = studio._github_release()
        info = studio._release_info(release)
        if not info["update_available"]:
            return {"status": "current", "message": "Shorts Studio is already up to date", **info}
        asset = info.get("asset")
        if not asset or not info.get("can_install"):
            return {
                "status": "manual",
                "message": "This source install needs a manual update from the GitHub release page.",
                **info,
            }
        studio._set_update_state(
            status="starting",
            current_version=info["current_version"],
            latest_version=info["latest_version"],
            progress=0,
            total=0,
            message="Starting update...",
            error=None,
        )
        threading.Thread(
            target=studio._update_service.download_and_apply,
            args=(asset, info["latest_version"]),
            name="shorts-studio-update",
            daemon=True,
        ).start()
        return {"status": "starting", "message": "Update started", **info}
    except Exception as exc:
        safe_error = redact_text(exc)
        studio._set_update_state(status="error", message="Update failed", error=safe_error)
        return {
            "status": "error",
            "message": "Update failed",
            "error": safe_error,
            "code": "update_failed",
            "current_version": studio._APP_VERSION,
        }
