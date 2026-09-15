"""Feature-oriented API routes for projects, storage, and the editor.

The application module owns process state and worker lifecycle.  This router
keeps the newer project-management features independently readable and lets
the handlers call the state boundary lazily, avoiding an import cycle during
FastAPI startup.
"""

from __future__ import annotations

import importlib
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from web.models import BrandPreset, CleanupRequest, ProviderCostRates, PublishRequest, TranscriptUpdate
from web.security import redact_structure
from web.publishing import PLATFORMS, build_publish_plan, platform_specs


router = APIRouter()


def _studio() -> Any:
    """Resolve the stateful app module only when a request is handled."""
    return importlib.import_module("web.app")


@router.get("/storage", tags=["system"])
def storage_report() -> Dict[str, Any]:
    return _studio()._storage_report()


@router.get("/provider-costs", tags=["system"])
def provider_costs() -> Dict[str, Any]:
    """Return configured rates without exposing any provider credentials."""
    return {"rates": _studio()._cost_rates_public(), "currency": "USD", "unit": "per_million_tokens"}


@router.put("/provider-costs", tags=["system"])
def save_provider_costs(rates: ProviderCostRates) -> Dict[str, Any]:
    return {
        "rates": _studio()._save_cost_rates(rates),
        "currency": "USD",
        "unit": "per_million_tokens",
    }


@router.post("/storage/cleanup", tags=["system"])
def cleanup_storage(request: CleanupRequest) -> Dict[str, Any]:
    studio = _studio()
    if not request.confirm:
        raise HTTPException(400, "Set confirm=true to clean generated caches")
    cutoff = time.time() - request.older_than_days * 86400
    removed: List[str] = []
    removed_bytes = 0
    roots = [studio._trash_dir]
    if request.include_uploads:
        roots.append(studio._uploads_dir)
    transcript_cache_files = set(studio._transcript_cache_files()) if request.include_transcript_caches else set()
    for root in roots:
        if not root.is_dir():
            continue
        for item in list(root.rglob("*")):
            if not item.is_file():
                continue
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
                size = item.stat().st_size
                item.unlink()
                removed.append(str(item))
                removed_bytes += size
            except OSError:
                continue
    # Previews and waveform caches are generated and safe to expire. Never
    # touch completed clips, source videos, model files, or custom save folders.
    for item in studio._output_root.rglob("*"):
        if not item.is_file():
            continue
        try:
            if item.stat().st_mtime >= cutoff:
                continue
            is_transcript = item in transcript_cache_files
            if "previews" not in item.parts and item.name != "waveform.json" and not is_transcript:
                continue
            size = item.stat().st_size
            item.unlink()
            removed.append(str(item))
            removed_bytes += size
        except OSError:
            continue
    if request.include_model_cache:
        for root in studio._model_cache_roots():
            if not root.is_dir():
                continue
            for item in root.rglob("*"):
                if not item.is_file():
                    continue
                try:
                    if item.stat().st_mtime >= cutoff:
                        continue
                    size = item.stat().st_size
                    item.unlink()
                    removed.append(str(item))
                    removed_bytes += size
                except OSError:
                    continue
    return {
        "removed": removed,
        "removed_count": len(removed),
        "removed_bytes": removed_bytes,
        "storage": studio._storage_report(),
    }


@router.get("/backup", tags=["system"])
def backup_projects() -> StreamingResponse:
    """Download project metadata/settings without copying source media."""
    studio = _studio()
    with studio._lock:
        records = []
        for job in studio._jobs.values():
            record = dict(job)
            record.pop("credentials", None)
            record.pop("_credentials", None)
            record["request"] = redact_structure(record.get("request"))
            record["result"] = redact_structure(record.get("result"))
            job_id = str(record.get("id") or "")
            record["error"] = studio._redact_log_text(record.get("error"), job_id) if record.get("error") else None
            record["logs"] = [
                {
                    **redact_structure(entry),
                    "message": studio._redact_log_text(entry.get("message"), job_id),
                }
                for entry in (record.get("logs") if isinstance(record.get("logs"), list) else [])
                if isinstance(entry, dict)
            ]
            records.append(record)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "backup.json",
            json.dumps({"schema_version": studio._JOB_SCHEMA_VERSION, "created_at": time.time()}, indent=2),
        )
        bundle.writestr("jobs.json", json.dumps(records, ensure_ascii=False, indent=2, default=str))
        bundle.writestr("studio_state.json", json.dumps(studio._setup_state(), ensure_ascii=False, indent=2))
        bundle.writestr("brand_presets.json", json.dumps(studio._load_brand_presets(), ensure_ascii=False, indent=2))
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="shorts_studio_backup.zip"'},
    )


@router.post("/restore", tags=["system"])
async def restore_projects(file: UploadFile = File(...), confirm: bool = Query(default=False)) -> Dict[str, Any]:
    """Merge a metadata backup while rejecting zip-slip and oversized archives."""
    studio = _studio()
    if not confirm:
        raise HTTPException(400, "Set confirm=true to restore a backup")
    max_backup_bytes = 100 * 1024 * 1024
    buffer = io.BytesIO()
    size = 0
    try:
        while True:
            chunk = await file.read(min(1024 * 1024, max_backup_bytes + 1 - size))
            if not chunk:
                break
            buffer.write(chunk)
            size += len(chunk)
            if size > max_backup_bytes:
                raise HTTPException(413, "backup is larger than the 100 MB limit")
        data = buffer.getvalue()
    finally:
        await file.close()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, "invalid backup archive") from exc
    names = archive.namelist()
    if len(names) > 10000:
        raise HTTPException(400, "backup contains too many files")
    total_uncompressed = sum(max(0, int(info.file_size)) for info in archive.infolist())
    if total_uncompressed > 200 * 1024 * 1024:
        raise HTTPException(413, "backup expands beyond the 200 MB safety limit")
    for name in names:
        normalized_name = str(name).replace("\\", "/")
        candidate = Path(normalized_name)
        if (
            not normalized_name
            or "\x00" in normalized_name
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.name != normalized_name.split("/")[-1]
        ):
            raise HTTPException(400, "backup contains an unsafe path")
    try:
        records = json.loads(archive.read("jobs.json"))
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise HTTPException(400, "backup is missing jobs.json") from exc
    if not isinstance(records, list):
        raise HTTPException(400, "jobs.json must contain an array")
    imported = 0
    with studio._lock:
        for raw in records:
            if not isinstance(raw, dict):
                continue
            job_id = str(raw.get("id") or "")
            if not studio._job_id_pattern.fullmatch(job_id) or job_id in studio._jobs:
                continue
            # Metadata backups contain no media. Reset restored filesystem
            # references so a crafted archive cannot read/write arbitrary paths.
            request_snapshot = studio._dict_value(raw.get("request"))
            request_snapshot["save_folder"] = None
            raw["request"] = request_snapshot
            raw["output_dir"] = str(studio._jobs_dir / job_id)
            source = raw.get("raw_source_video_url")
            raw["raw_source_video_url"] = source if str(source or "").startswith(("http://", "https://")) else None
            sanitized_shorts = []
            for short in studio._dict_items(raw.get("raw_shorts")):
                safe_short = dict(short)
                for key in ("clip_url", "thumbnail_path", "local_path", "play_url", "undo_path", "undo_metadata"):
                    safe_short.pop(key, None)
                safe_short["clip_url"] = None
                sanitized_shorts.append(safe_short)
            raw["raw_shorts"] = sanitized_shorts
            result_snapshot = studio._dict_value(raw.get("result"))
            result_snapshot["source_video_url"] = raw["raw_source_video_url"]
            result_snapshot["shorts"] = studio._public_shorts(sanitized_shorts, job_id)
            raw["result"] = result_snapshot
            raw["schema_version"] = studio._JOB_SCHEMA_VERSION
            raw["status"] = "interrupted" if raw.get("status") in {"running", "queued"} else str(raw.get("status") or "draft")
            raw["message"] = (
                "Restored from backup; retry to render again."
                if raw["status"] == "interrupted"
                else raw.get("message", "Restored project")
            )
            raw.pop("credentials", None)
            raw.pop("_credentials", None)
            raw["error"] = redact_structure(raw.get("error"))
            raw["logs"] = redact_structure(raw.get("logs"))
            studio._jobs[job_id] = raw
            studio._persist_job_locked(raw)
            imported += 1
    try:
        if "studio_state.json" in names:
            state = json.loads(archive.read("studio_state.json"))
            if isinstance(state, dict):
                studio._write_setup_state(state)
        if "brand_presets.json" in names:
            presets = json.loads(archive.read("brand_presets.json"))
            if isinstance(presets, dict):
                studio._save_brand_presets({str(k): v for k, v in presets.items() if isinstance(v, dict)})
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(400, f"backup settings are invalid: {exc}") from exc
    finally:
        archive.close()
    return {"status": "restored", "imported_jobs": imported, "skipped_existing": len(records) - imported}


@router.get("/brand-presets", tags=["projects"])
def list_brand_presets() -> Dict[str, Any]:
    return {"presets": list(_studio()._load_brand_presets().values())}


@router.post("/brand-presets", tags=["projects"])
def save_brand_preset(preset: BrandPreset) -> Dict[str, Any]:
    studio = _studio()
    values = preset.model_dump()
    presets = studio._load_brand_presets()
    presets[preset.name.casefold()] = values
    studio._save_brand_presets(presets)
    return {"preset": values, "presets": list(presets.values())}


@router.delete("/brand-presets/{name}", tags=["projects"])
def delete_brand_preset(name: str) -> Dict[str, Any]:
    studio = _studio()
    key = " ".join(str(name).split()).casefold()
    presets = studio._load_brand_presets()
    if key not in presets:
        raise HTTPException(404, "brand preset not found")
    presets.pop(key, None)
    studio._save_brand_presets(presets)
    return {"status": "deleted", "presets": list(presets.values())}


@router.get("/jobs/{job_id}/events", tags=["projects"])
def job_events(job_id: str) -> StreamingResponse:
    """Stream durable job snapshots for browser clients that support SSE."""
    studio = _studio()
    with studio._lock:
        if job_id not in studio._jobs:
            raise HTTPException(404, "job not found")

    def stream():
        last_payload = ""
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            with studio._lock:
                job = studio._jobs.get(job_id)
                if not job:
                    break
                snapshot = studio._job_snapshot(job)
                status = str(snapshot.get("status") or "")
            payload = json.dumps(snapshot, ensure_ascii=False, default=str)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if status in {"done", "error", "cancelled", "interrupted"}:
                break
            time.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/jobs/{job_id}/transcript")
def update_transcript(job_id: str, update: TranscriptUpdate) -> Dict[str, Any]:
    """Persist hand-edited transcript timing/text for captions and exports."""
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        current = studio._dict_value(job.get("raw_transcript"))
        duration = update.duration or studio._safe_transcript_duration(current)
        if duration <= 0:
            duration = update.segments[-1].end
        current["duration"] = duration
        current["segments"] = [segment.model_dump() for segment in update.segments]
        job["raw_transcript"] = current
        result = studio._dict_value(job.get("result"))
        if result:
            result["transcript_duration"] = duration
            result["segment_count"] = len(update.segments)
            job["result"] = result
        studio._append_job_log(job, "edit", f"Updated transcript ({len(update.segments)} segments)")
        studio._persist_job_locked(job)
        return studio._job_snapshot(job)


def _publishing_payload(short: Dict[str, Any], platform: str) -> Dict[str, Any]:
    studio = _studio()
    metadata = studio._creator_metadata(short)
    spec = PLATFORMS[platform]
    return {
        "platform": platform,
        "label": spec.label,
        "title": metadata["title"][: spec.title_limit],
        "description": metadata["description"][: spec.description_limit],
        "hashtags": metadata["hashtags"],
        "thumbnail_text": metadata["thumbnail_text"],
        "clip_start": short.get("start_time"),
        "clip_end": short.get("end_time"),
        "clip_url": short.get("play_url") or short.get("clip_url"),
        "upload_url": spec.upload_url,
        "authorization_url": spec.authorization_url,
        "requires_manual_upload": True,
        "oauth_status": "not_configured",
        "token_storage": "disabled",
    }


@router.get("/publishing/platforms", tags=["projects"])
def publishing_platforms() -> Dict[str, Any]:
    """List supported provider handoffs without requesting credentials."""
    return {"platforms": platform_specs(), "automatic_upload": False, "token_storage": "disabled"}


@router.get("/jobs/{job_id}/publishing", tags=["projects"])
def publishing_payloads(job_id: str, platform: Optional[str] = Query(default=None)) -> Dict[str, Any]:
    studio = _studio()
    platforms = ["youtube_shorts", "tiktok", "instagram_reels"]
    if platform and platform not in platforms:
        raise HTTPException(400, "platform must be youtube_shorts, tiktok, or instagram_reels")
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
    selected = [platform] if platform else platforms
    return {
        "job_id": job_id,
        "items": {name: [_publishing_payload(short, name) for short in shorts] for name in selected},
        "notice": "Shorts Studio prepares metadata and official upload links; upload and OAuth consent remain under your control.",
    }


@router.post("/jobs/{job_id}/publish", tags=["projects"])
def prepare_publish(job_id: str, request: PublishRequest) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
    if request.clip_index is not None and request.clip_index >= len(shorts):
        raise HTTPException(404, "clip not found")
    selected = shorts if request.clip_index is None else shorts[request.clip_index : request.clip_index + 1]
    plan = build_publish_plan(request.platform, [_publishing_payload(short, request.platform) for short in selected])
    return {
        "status": "ready_for_manual_upload",
        "platform": request.platform,
        "label": plan["label"],
        "upload_url": plan["upload_url"],
        "authorization_url": plan["authorization_url"],
        "items": plan["items"],
        "requires_manual_upload": True,
        "oauth_status": "not_configured",
        "token_storage": "disabled",
    }
