"""Feature-oriented API routes for projects, storage, and the editor.

The application module owns process state and worker lifecycle.  This router
keeps the newer project-management features independently readable and lets
the handlers call the state boundary lazily, avoiding an import cycle during
FastAPI startup.
"""

from __future__ import annotations

import importlib
import io
import asyncio
import json
import hashlib
import shutil
import time
import zipfile
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from web.models import BrandPreset, CleanupRequest, ProviderCostRates, PublishRequest, TranscriptUpdate
from web.security import redact_structure
from web.migrations import CURRENT_SCHEMA_VERSION, PROJECT_FORMAT_VERSION, migrate_job_record
from web.publishing import (
    PLATFORMS,
    build_publish_plan,
    complete_youtube_oauth,
    complete_instagram_oauth,
    complete_tiktok_oauth,
    direct_platform_status,
    platform_specs,
    publish_direct,
    start_instagram_oauth,
    start_tiktok_oauth,
    start_youtube_oauth,
    upload_youtube_video,
    youtube_oauth_status,
)
from shorts_generator.export_profiles import export_preset_specs


router = APIRouter()


def _studio() -> Any:
    """Resolve the stateful app module only when a request is handled."""
    return importlib.import_module("web.app")


_URL_SECRET_QUERY_KEYS = {"token", "access_token", "signature", "sig", "expires", "expiry", "auth"}
_BACKUP_URL_KEYS = {
    "raw_source_video_url",
    "source_video_url",
    "clip_url",
    "play_url",
    "thumbnail_url",
    "preview_url",
}
_BACKUP_MEDIA_PATH_KEYS = {
    "clip_url",
    "thumbnail_path",
    "local_path",
    "play_url",
    "preview_url",
    "undo_path",
    "redo_path",
    "undo_metadata",
    "redo_metadata",
}


def _safe_backup_value(value: Any, key: str = "") -> Any:
    """Copy metadata while removing media URLs and signed query parameters."""
    if key in _BACKUP_URL_KEYS:
        return None
    if isinstance(value, dict):
        return {str(name): _safe_backup_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_safe_backup_value(item, key) for item in value]
    if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
        try:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

            parts = urlsplit(value)
            query = [(name, item) for name, item in parse_qsl(parts.query, keep_blank_values=True) if name.lower() not in _URL_SECRET_QUERY_KEYS]
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        except (TypeError, ValueError):
            return None
    return value


def _strip_backup_media_fields(value: Any) -> Any:
    """Remove local media references from nested backup metadata."""
    if isinstance(value, dict):
        return {
            str(key): _strip_backup_media_fields(item)
            for key, item in value.items()
            if str(key) not in _BACKUP_MEDIA_PATH_KEYS
        }
    if isinstance(value, list):
        return [_strip_backup_media_fields(item) for item in value]
    return value


def _restore_job_media(
    archive: zipfile.ZipFile,
    names: List[str],
    studio: Any,
    job: Dict[str, Any],
    shorts: List[Dict[str, Any]],
) -> int:
    """Restore explicitly included job media inside the job trust boundary."""
    job_id = str(job.get("id") or "")
    prefix = f"media/{job_id}/"
    output_dir = studio._job_output_dir(job).resolve()
    extracted: List[Path] = []
    for name in names:
        normalized = str(name).replace("\\", "/")
        if not normalized.startswith(prefix) or normalized.endswith("/"):
            continue
        relative = Path(normalized[len(prefix) :])
        if not relative.parts:
            continue
        target = (output_dir / relative).resolve()
        try:
            target.relative_to(output_dir)
        except ValueError:
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name, "r") as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            extracted.append(target)
        except (OSError, KeyError, RuntimeError):
            continue

    # Generated clip files normally use the short_XX.mp4 template. Restrict
    # automatic relinking to root-level clip-like files so an included source
    # video or a nested history snapshot cannot become a playable short.
    clip_files = sorted(
        [
            path
            for path in extracted
            if path.parent == output_dir
            and path.suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}
            and ("short" in path.stem.lower() or "clip" in path.stem.lower())
        ],
        key=lambda path: path.name.casefold(),
    )
    for index, short in enumerate(shorts):
        if index >= len(clip_files):
            break
        clip = clip_files[index]
        short["clip_url"] = str(clip)
        thumbnail = clip.with_suffix(".jpg")
        if thumbnail in extracted:
            short["thumbnail_path"] = str(thumbnail)
    return len(extracted)


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
    with studio._lock:
        active_dirs = {
            str(studio._job_output_dir(job).resolve())
            for job in studio._jobs.values()
            if str(job.get("status")) in {"queued", "running"}
        }
        active_sources = set()
        for job in studio._jobs.values():
            if str(job.get("status")) not in {"queued", "running"}:
                continue
            request_snapshot = studio._dict_value(job.get("request"))
            source_path = studio._job_source_path(job, request_snapshot.get("url"))
            if source_path:
                active_sources.add(str(source_path.resolve()))
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
                if str(item.resolve()) in active_sources:
                    continue
                if item.stat().st_mtime >= cutoff:
                    continue
                size = item.stat().st_size
                item.unlink()
                removed.append(str(item))
                removed_bytes += size
            except OSError:
                continue
    # Previews, waveforms, and transcript sidecars are renderer-owned only
    # when they live below a job output directory. Snapshot active directories
    # under the same lock used by workers so cleanup never races a render.
    job_dirs = list(studio._jobs_dir.iterdir()) if studio._jobs_dir.is_dir() else []
    for job_dir in job_dirs:
        if not job_dir.is_dir() or str(job_dir.resolve()) in active_dirs:
            continue
        for item in job_dir.rglob("*"):
            if not item.is_file():
                continue
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
                rel = item.relative_to(job_dir)
                is_owned = rel.parts and (rel.parts[0] == "previews" or item.name == "waveform.json" or item in transcript_cache_files)
                if not is_owned:
                    continue
                size = item.stat().st_size
                item.unlink()
                removed.append(str(item))
                removed_bytes += size
            except (OSError, ValueError):
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
def backup_projects(include_media: bool = Query(default=False)) -> StreamingResponse:
    """Download project metadata/settings, optionally with job-owned media."""
    studio = _studio()
    media_files: List[tuple[str, Path, int]] = []
    media_bytes = 0
    max_media_bytes = 512 * 1024 * 1024
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
        ".tmp",
    )
    with studio._lock:
        records = []
        for job in studio._jobs.values():
            record = dict(job)
            record.pop("credentials", None)
            record.pop("_credentials", None)
            # History stacks contain absolute local paths and are rebuilt from
            # the optional media/ directory when a backup is inspected.
            record.pop("clip_history", None)
            record.pop("clip_redo", None)
            request_snapshot = _safe_backup_value(redact_structure(record.get("request")))
            if isinstance(request_snapshot, dict):
                request_snapshot["save_folder"] = None
            record["request"] = request_snapshot
            record["result"] = _strip_backup_media_fields(_safe_backup_value(redact_structure(record.get("result"))))
            record["raw_source_video_url"] = None
            record["output_dir"] = None
            safe_shorts = []
            for short in (record.get("raw_shorts") if isinstance(record.get("raw_shorts"), list) else []):
                if not isinstance(short, dict):
                    continue
                safe_short = _safe_backup_value(short)
                for key in (
                    "clip_url",
                    "thumbnail_path",
                    "local_path",
                    "play_url",
                    "undo_path",
                    "redo_path",
                    "undo_metadata",
                    "redo_metadata",
                ):
                    safe_short.pop(key, None)
                safe_shorts.append(safe_short)
            record["raw_shorts"] = safe_shorts
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
            if include_media:
                output_dir = studio._job_output_dir(job)
                if output_dir.is_dir():
                    for media_path in output_dir.rglob("*"):
                        if not media_path.is_file() or media_path.name.endswith(scratch_suffixes):
                            continue
                        try:
                            relative = media_path.relative_to(output_dir)
                            size = media_path.stat().st_size
                        except (OSError, ValueError):
                            continue
                        media_bytes += size
                        if media_bytes > max_media_bytes:
                            raise HTTPException(413, "media backup exceeds the 512 MB safety limit")
                        media_files.append((f"media/{job_id}/{relative.as_posix()}", media_path, size))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "backup.json",
            json.dumps(
                {
                    "schema_version": studio._JOB_SCHEMA_VERSION,
                    "project_format_version": PROJECT_FORMAT_VERSION,
                    "migration_target": CURRENT_SCHEMA_VERSION,
                    "created_at": time.time(),
                    "include_media": bool(include_media),
                    "media_count": len(media_files),
                    "media_bytes": media_bytes,
                },
                indent=2,
            ),
        )
        bundle.writestr("jobs.json", json.dumps(records, ensure_ascii=False, indent=2, default=str))
        bundle.writestr("studio_state.json", json.dumps(studio._setup_state(), ensure_ascii=False, indent=2))
        bundle.writestr("brand_presets.json", json.dumps(studio._load_brand_presets(), ensure_ascii=False, indent=2))
        bundle.writestr("provider_costs.json", json.dumps(studio._cost_rates_public(), ensure_ascii=False, indent=2))
        if include_media:
            manifest = []
            for arcname, media_path, size in media_files:
                try:
                    bundle.write(media_path, arcname=arcname)
                except OSError:
                    continue
                manifest.append({"path": arcname, "size": size})
            bundle.writestr(
                "media_manifest.json",
                json.dumps({"count": len(manifest), "bytes": sum(item["size"] for item in manifest), "files": manifest}, indent=2),
            )
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="shorts_studio_backup.zip"'},
    )


@router.post("/restore", tags=["system"])
async def restore_projects(file: UploadFile = File(...), confirm: bool = Query(default=False)) -> Dict[str, Any]:
    """Merge a metadata or media-inclusive backup with strict archive bounds."""
    studio = _studio()
    if not confirm:
        raise HTTPException(400, "Set confirm=true to restore a backup")
    max_backup_bytes = 512 * 1024 * 1024
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
                raise HTTPException(413, "backup is larger than the 512 MB limit")
        data = buffer.getvalue()
    finally:
        await file.close()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, "invalid backup archive") from exc
    names = archive.namelist()
    if len(names) > 10000:
        archive.close()
        raise HTTPException(400, "backup contains too many files")
    backup_meta: Dict[str, Any] = {}
    if "backup.json" in names:
        try:
            loaded_meta = json.loads(archive.read("backup.json"))
            if isinstance(loaded_meta, dict):
                backup_meta = loaded_meta
        except (KeyError, OSError, ValueError, TypeError):
            backup_meta = {}
    max_uncompressed = 512 * 1024 * 1024 if backup_meta.get("include_media") else 200 * 1024 * 1024
    total_uncompressed = sum(max(0, int(info.file_size)) for info in archive.infolist())
    if total_uncompressed > max_uncompressed:
        archive.close()
        raise HTTPException(413, f"backup expands beyond the {max_uncompressed // (1024 * 1024)} MB safety limit")
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
            archive.close()
            raise HTTPException(400, "backup contains an unsafe path")
    try:
        records = json.loads(archive.read("jobs.json"))
    except (KeyError, OSError, ValueError, TypeError) as exc:
        archive.close()
        raise HTTPException(400, "backup is missing jobs.json") from exc
    if not isinstance(records, list):
        archive.close()
        raise HTTPException(400, "jobs.json must contain an array")
    imported = 0
    migrated_jobs = 0
    restored_media_files = 0
    include_media = bool(backup_meta.get("include_media"))
    with studio._lock:
        for raw in records:
            if not isinstance(raw, dict):
                continue
            try:
                raw, migration_steps = migrate_job_record(raw, target=studio._JOB_SCHEMA_VERSION)
            except ValueError as exc:
                archive.close()
                raise HTTPException(409, {"error": str(exc), "code": "migration_required"}) from exc
            migrated_jobs += len(migration_steps)
            job_id = str(raw.get("id") or "")
            if not studio._job_id_pattern.fullmatch(job_id) or job_id in studio._jobs:
                continue
            # Reset restored filesystem references before optional, job-scoped
            # media relinking so a crafted archive cannot escape its boundary.
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
            if include_media:
                restored_media_files += _restore_job_media(archive, names, studio, raw, sanitized_shorts)
                result_snapshot["shorts"] = studio._public_shorts(sanitized_shorts, job_id)
                raw["result"] = result_snapshot
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
        if "provider_costs.json" in names:
            rates = json.loads(archive.read("provider_costs.json"))
            if isinstance(rates, dict):
                studio._save_cost_rates(ProviderCostRates.model_validate(rates))
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(400, f"backup settings are invalid: {exc}") from exc
    finally:
        archive.close()
    return {
        "status": "restored",
        "imported_jobs": imported,
        "skipped_existing": len(records) - imported,
        "restored_media_files": restored_media_files,
        "migrations_applied": migrated_jobs,
    }


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
async def job_events(job_id: str) -> StreamingResponse:
    """Stream durable job snapshots for browser clients that support SSE."""
    studio = _studio()
    with studio._lock:
        if job_id not in studio._jobs:
            raise HTTPException(404, "job not found")

    async def stream():
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
            await asyncio.sleep(0.5)

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


@router.get("/export-presets", tags=["projects"])
def export_presets() -> Dict[str, Any]:
    """List validated platform export profiles for the editor."""
    return {"presets": export_preset_specs()}


def _publishing_payload(short: Dict[str, Any], platform: str) -> Dict[str, Any]:
    studio = _studio()
    metadata = studio._creator_metadata(short)
    spec = PLATFORMS[platform]
    oauth_status = direct_platform_status().get(platform, {"configured": False, "authorized": False})
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
        "requires_manual_upload": not bool(oauth_status.get("authorized")) or spec.requires_public_media,
        "direct_api": spec.direct_api,
        "requires_public_media_url": spec.requires_public_media,
        "oauth_status": oauth_status,
        "token_storage": "disabled",
    }


@router.get("/publishing/platforms", tags=["projects"])
def publishing_platforms() -> Dict[str, Any]:
    """List supported provider handoffs without requesting credentials."""
    statuses = direct_platform_status()
    return {
        "platforms": platform_specs(),
        "automatic_upload": any(bool(item.get("authorized")) for item in statuses.values()),
        "approval_required": True,
        "youtube": statuses.get("youtube_shorts", youtube_oauth_status()),
        "direct": statuses,
        "token_storage": "process_memory_only",
    }


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
        "notice": "Review every plan before publishing. Direct uploads use official platform APIs and keep tokens in process memory only.",
    }


def _publish_selection(studio: Any, job: Dict[str, Any], request: PublishRequest) -> tuple[int, Dict[str, Any], Optional[Dict[str, Any]]]:
    shorts = studio._dict_items(job.get("raw_shorts"))
    variant: Optional[Dict[str, Any]] = None
    if request.variant_id:
        variant = next(
            (item for item in studio._dict_items(job.get("variants")) if str(item.get("id")) == request.variant_id),
            None,
        )
        if variant is None:
            raise HTTPException(404, {"error": "variant not found", "code": "variant_not_found"})
        try:
            index = int(variant.get("clip_index") or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(400, {"error": "variant clip index is invalid", "code": "validation_error"}) from exc
        if request.clip_index is not None and request.clip_index != index:
            raise HTTPException(400, {"error": "clip_index does not match variant", "code": "validation_error"})
    else:
        index = request.clip_index if request.clip_index is not None else 0
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, {"error": "clip not found", "code": "clip_not_found"})
    return index, shorts[index], variant


@router.post("/jobs/{job_id}/publish", tags=["projects"])
def prepare_publish(job_id: str, request: PublishRequest) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
        shorts = studio._dict_items(job.get("raw_shorts"))
        index, short, variant = _publish_selection(studio, job, request)
    selected = shorts if request.clip_index is None and request.variant_id is None else [short]
    plan = build_publish_plan(request.platform, [_publishing_payload(short, request.platform) for short in selected])
    status = direct_platform_status().get(request.platform, {})
    direct_ready = bool(status.get("authorized")) and not (
        request.platform == "instagram_reels" and not request.media_url
    )
    if request.confirm:
        if request.clip_index is None and request.variant_id is None:
            raise HTTPException(400, {"error": "choose one clip for a direct upload", "code": "validation_error"})
        if not status.get("authorized"):
            raise HTTPException(
                400,
                {
                    "error": f"Connect {plan['label']} before approving a direct upload",
                    "code": "credentials_required",
                },
            )
        if request.platform == "instagram_reels" and not request.media_url:
            raise HTTPException(
                400,
                {
                    "error": "Instagram Reels publishing requires a public media_url",
                    "code": "validation_error",
                },
            )
        if request.publish_at and request.platform != "youtube_shorts":
            raise HTTPException(
                400,
                {
                    "error": f"{plan['label']} direct publishing does not support scheduling yet",
                    "code": "validation_error",
                },
            )
        media = studio._job_media_path(job, short.get("clip_url"))
        if not media or not media.is_file():
            raise HTTPException(400, {"error": "clip media is unavailable", "code": "media_unavailable"})
        metadata = variant or studio._creator_metadata(short)
        title = request.title or str(metadata.get("title") or "Untitled highlight")
        description = request.description or str(metadata.get("description") or "")
        tags = request.tags or [tag for tag in str(metadata.get("hashtags") or "").split() if tag]
        idempotency_key = hashlib.sha256(
            f"{job_id}:{request.variant_id or index}:{title}:{request.publish_at or ''}:{request.privacy_status}".encode("utf-8")
        ).hexdigest()[:32]
        try:
            uploaded = publish_direct(
                request.platform,
                media,
                title=title,
                description=description,
                tags=tags,
                privacy_status=request.privacy_status,
                publish_at=request.publish_at,
                idempotency_key=idempotency_key,
                media_url=request.media_url,
            )
        except (ValueError, OSError, RuntimeError, requests.RequestException) as exc:
            raise HTTPException(502, {"error": str(exc), "code": "publish_failed"}) from exc
        with studio._lock:
            current = studio._jobs.get(job_id)
            if current is not None:
                publishing = current.get("publishing")
                if not isinstance(publishing, list):
                    publishing = []
                    current["publishing"] = publishing
                publishing.append(
                    {"platform": request.platform, "clip_index": index, "variant_id": request.variant_id, **uploaded, "approved_at": time.time()}
                )
                studio._append_job_log(current, "publish", f"Approved {request.platform} upload for clip {index + 1}")
                studio._persist_job_locked(current)
        return {"status": "uploaded", "message": f"{plan['label']} upload completed.", "plan": plan, "upload": uploaded}
    return {
        "status": "approval_required" if direct_ready else "ready_for_manual_upload",
        "platform": request.platform,
        "label": plan["label"],
        "upload_url": plan["upload_url"],
        "authorization_url": plan["authorization_url"],
        "items": plan["items"],
        "requires_manual_upload": not direct_ready,
        "direct_api": bool(PLATFORMS[request.platform].direct_api),
        "oauth_status": status,
        "token_storage": "disabled",
    }


@router.get("/youtube/oauth/status", tags=["projects"])
def youtube_oauth_status_route() -> Dict[str, Any]:
    return youtube_oauth_status()


@router.get("/tiktok/oauth/status", tags=["projects"])
def tiktok_oauth_status_route() -> Dict[str, Any]:
    return direct_platform_status()["tiktok"]


@router.get("/tiktok/oauth/start", tags=["projects"])
def tiktok_oauth_start() -> Dict[str, Any]:
    try:
        return start_tiktok_oauth()
    except ValueError as exc:
        raise HTTPException(400, {"error": str(exc), "code": "oauth_not_configured"}) from exc


@router.get("/tiktok/oauth/callback", tags=["projects"])
def tiktok_oauth_callback(code: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
    if not code or not state:
        raise HTTPException(400, {"error": "TikTok OAuth callback requires code and state", "code": "oauth_invalid"})
    try:
        return {"status": "authorized", **complete_tiktok_oauth(code, state)}
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        raise HTTPException(400, {"error": str(exc), "code": "oauth_invalid"}) from exc


@router.get("/instagram/oauth/status", tags=["projects"])
def instagram_oauth_status_route() -> Dict[str, Any]:
    return direct_platform_status()["instagram_reels"]


@router.get("/instagram/oauth/start", tags=["projects"])
def instagram_oauth_start() -> Dict[str, Any]:
    try:
        return start_instagram_oauth()
    except ValueError as exc:
        raise HTTPException(400, {"error": str(exc), "code": "oauth_not_configured"}) from exc


@router.get("/instagram/oauth/callback", tags=["projects"])
def instagram_oauth_callback(code: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
    if not code or not state:
        raise HTTPException(400, {"error": "Instagram OAuth callback requires code and state", "code": "oauth_invalid"})
    try:
        return {"status": "authorized", **complete_instagram_oauth(code, state)}
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        raise HTTPException(400, {"error": str(exc), "code": "oauth_invalid"}) from exc


@router.get("/youtube/oauth/start", tags=["projects"])
def youtube_oauth_start() -> Dict[str, Any]:
    try:
        return start_youtube_oauth()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/youtube/oauth/callback", tags=["projects"])
def youtube_oauth_callback(code: Optional[str] = None, state: Optional[str] = None) -> Dict[str, Any]:
    if not code or not state:
        raise HTTPException(400, "YouTube OAuth callback requires code and state")
    try:
        return {"status": "authorized", **complete_youtube_oauth(code, state)}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/jobs/{job_id}/youtube/publish", tags=["projects"])
def publish_youtube(job_id: str, request: PublishRequest) -> Dict[str, Any]:
    """Prepare or execute one approval-first, private-by-default upload."""
    if request.platform != "youtube_shorts":
        raise HTTPException(400, "this endpoint only supports youtube_shorts")
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
    index = request.clip_index if request.clip_index is not None else 0
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "clip not found")
    short = shorts[index]
    metadata = studio._creator_metadata(short)
    title = request.title or metadata["title"]
    description = request.description or metadata["description"]
    tags = request.tags or [tag for tag in metadata["hashtags"].split() if tag]
    plan = {
        "platform": "youtube_shorts",
        "clip_index": index,
        "title": title[:100],
        "description": description[:5000],
        "tags": tags[:30],
        "privacy_status": request.privacy_status,
        "publish_at": request.publish_at,
        "approval_required": True,
        "resumable": True,
        "idempotency_key": hashlib.sha256(
            f"{job_id}:{index}:{title}:{request.publish_at or ''}:{request.privacy_status}".encode("utf-8")
        ).hexdigest()[:32],
    }
    if not request.confirm:
        return {"status": "approval_required", "message": "Review this plan and resend with confirm=true.", "plan": plan}
    media = studio._job_media_path(job, short.get("clip_url"))
    if not media or not media.is_file():
        raise HTTPException(400, "YouTube publishing requires a local rendered clip")
    try:
        uploaded = upload_youtube_video(
            media,
            title=title,
            description=description,
            tags=tags,
            privacy_status=request.privacy_status,
            publish_at=request.publish_at,
            idempotency_key=plan["idempotency_key"],
        )
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    with studio._lock:
        job = studio._jobs.get(job_id)
        if job:
            job.setdefault("youtube_uploads", []).append({"clip_index": index, **uploaded, "approved_at": time.time()})
            studio._append_job_log(job, "publish", f"Approved YouTube upload for clip {index + 1}")
            studio._persist_job_locked(job)
    return {"status": "uploaded", "message": "YouTube upload completed.", "plan": plan, "upload": uploaded}
