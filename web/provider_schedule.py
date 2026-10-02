"""Explicit provider scheduling with durable approvals and conservative retries.

No timer or background worker calls this module. An approved queue entry is
uploaded only by a separate, explicit dispatch that acknowledges YouTube will
make the initially private video public at the requested time.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from fastapi import HTTPException
from pydantic import Field

from web.factory import approved_for_clip
from web.models import PublishRequest, StrictModel
from web.policy import evaluate_publish_policy
from web.publishing import YouTubePublishError, upload_youtube_video, youtube_oauth_status, youtube_video_schedule
from web.security import redact_structure


_ACTIVE_STATES = {"provider_dispatching", "provider_unknown", "provider_scheduled"}
_MAX_ATTEMPTS = 5
_MINIMUM_LEAD_SECONDS = 300


class ScheduleDispatchRequest(StrictModel):
    confirm: bool = False
    acknowledge_public_publish: bool = False


class ScheduleReconcileRequest(StrictModel):
    confirm: bool = False
    video_id: str = Field(min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")


class ScheduleRefreshRequest(StrictModel):
    confirm: bool = False


def dispatch_inflight(job: Dict[str, Any]) -> bool:
    return any(
        isinstance(entry, dict) and entry.get("status") == "provider_dispatching"
        for entry in (job.get("schedule") if isinstance(job.get("schedule"), list) else [])
    )


def provider_schedule_active(job: Dict[str, Any]) -> bool:
    return any(
        isinstance(entry, dict) and entry.get("status") in _ACTIVE_STATES
        for entry in (job.get("schedule") if isinstance(job.get("schedule"), list) else [])
    )


def recover_interrupted_dispatches(job: Dict[str, Any]) -> bool:
    """Fail closed after a restart; the provider may have accepted the upload."""
    changed = False
    for entry in (job.get("schedule") if isinstance(job.get("schedule"), list) else []):
        if isinstance(entry, dict) and entry.get("status") == "provider_dispatching":
            entry["status"] = "provider_unknown"
            entry["provider_error"] = {
                "code": "interrupted_dispatch",
                "message": "Dispatch was interrupted. Check YouTube Studio and reconcile the video before any further upload.",
                "at": time.time(),
            }
            changed = True
    return changed


def capabilities() -> Dict[str, Any]:
    auth = youtube_oauth_status()
    return {
        "platforms": {
            "youtube_shorts": {
                "provider_scheduling": True,
                "authorized": bool(auth.get("authorized")),
                "privacy_required": "private",
                "explicit_dispatch_required": True,
                "public_publish_acknowledgement_required": True,
                "minimum_lead_seconds": _MINIMUM_LEAD_SECONDS,
                "provider_cancel_supported": False,
                "reconciliation_supported": True,
            },
            "tiktok": {"provider_scheduling": False, "reason": "Schedule through TikTok Studio."},
            "instagram_reels": {"provider_scheduling": False, "reason": "Schedule through the provider's studio."},
        },
        "notice": "Dispatch is manual. YouTube publishes the private upload at the chosen time. Cancel provider schedules in YouTube Studio.",
    }


def _file_digest(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schedule_snapshot(
    studio: Any, job: Dict[str, Any], entry: Dict[str, Any]
) -> Tuple[Dict[str, Any], str, Optional[Path]]:
    """Bind approval to actual media, chosen metadata and generated assets.

    The returned digest contains no recoverable paths or credentials. The
    caller holds the job lock; dispatch also holds the clip's artifact lock so
    an editor cannot replace the approved bytes during upload.
    """
    from web.editor_routes import _captions_for_short
    from web.v2_routes import _clip_selection

    index, short, variant = _clip_selection(studio, job, entry.get("clip_index"), entry.get("variant_id"))
    stored = entry.get("request") if isinstance(entry.get("request"), dict) else {}
    metadata = studio._creator_metadata(short)
    if variant:
        metadata = {**metadata, **variant}
    payload = dict(stored)
    payload.update(
        {
            "clip_index": index,
            "variant_id": entry.get("variant_id"),
            "publish_at": entry.get("publish_at"),
            "title": str(stored.get("title") or metadata.get("title") or "Untitled highlight")[:100],
            "description": str(stored.get("description") or metadata.get("description") or ""),
            "tags": stored.get("tags") or str(metadata.get("hashtags") or "").split(),
            "privacy_status": stored.get("privacy_status") or "private",
            "auto_publish": False,
        }
    )
    media = studio._job_media_path(job, short.get("clip_url"))
    thumbnail = studio._job_media_path(job, short.get("thumbnail_path"))
    transcript = studio._dict_value(job.get("raw_transcript"))
    reviewed = {
        "payload": payload,
        "clip": short,
        "variant": variant,
        "media_sha256": _file_digest(media),
        "thumbnail_sha256": _file_digest(thumbnail),
        "captions": _captions_for_short(short, transcript, "srt"),
    }
    digest = hashlib.sha256(json.dumps(reviewed, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    return payload, digest, media


def approve_snapshot(studio: Any, job: Dict[str, Any], entry: Dict[str, Any]) -> None:
    _require_no_clip_edit(studio, job)
    payload, fingerprint, _media = schedule_snapshot(studio, job, entry)
    entry["approval_fingerprint"] = fingerprint
    # Persist the exact provider metadata separately from the editable intent.
    # Local paths have already been removed from the intent at creation.
    entry["approved_payload"] = payload


def _require_no_clip_edit(studio: Any, job: Dict[str, Any]) -> None:
    if getattr(studio, "_clip_edit_counts", {}).get(str(job.get("id") or ""), 0):
        raise HTTPException(409, {"error": "Wait for the current clip edit to finish before reviewing or dispatching its schedule.", "code": "clip_edit_busy"})


def _immutable_assets(
    studio: Any, job: Dict[str, Any], short: Dict[str, Any], directory: Path
) -> Tuple[Optional[Path], Optional[Path]]:
    """Prepare request-owned assets; shared publishing files can be rewritten."""
    from web.editor_routes import _captions_for_short

    thumbnail: Optional[Path] = None
    source = studio._job_media_path(job, short.get("thumbnail_path"))
    if source is not None and source.is_file():
        thumbnail = directory / f"thumbnail{source.suffix.lower()}"
        shutil.copyfile(source, thumbnail)
        if _file_digest(source) != _file_digest(thumbnail):
            raise HTTPException(409, {"error": "Thumbnail changed while preparing dispatch. Review the schedule again.", "code": "approval_stale"})
    captions: Optional[Path] = None
    text = _captions_for_short(short, studio._dict_value(job.get("raw_transcript")), "srt")
    if text:
        captions = directory / "captions.srt"
        captions.write_text(text, encoding="utf-8")
    return thumbnail, captions


def _policy(studio: Any, job: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    from web.v2_routes import _clip_selection

    index, short, _variant = _clip_selection(studio, job, payload.get("clip_index"), payload.get("variant_id"))
    factory = studio._dict_value(job.get("factory"))
    approved = not factory.get("enabled") or approved_for_clip(job, index)
    if not approved:
        raise HTTPException(409, {"error": "Factory approval is required before dispatch.", "code": "factory_approval_required"})
    policy = evaluate_publish_policy(
        {**payload, "start_time": short.get("start_time"), "end_time": short.get("end_time"), "hook_sentence": short.get("hook_sentence")},
        scheduled=True,
        factory_approved=approved,
    )
    if policy["status"] == "blocked":
        raise HTTPException(409, {"error": "Schedule policy blocked dispatch.", "code": "policy_blocked", "policy": policy})
    return policy


def _response(entry: Dict[str, Any], *, replayed: bool = False) -> Dict[str, Any]:
    return {"status": entry["status"], "entry": redact_structure(dict(entry)), "replayed": replayed}


def _provider_error_message(exc: Exception, *, safe_retry: bool) -> str:
    # SDK/transport exception strings may echo OAuth headers or POST bodies.
    # Keep actionable, known messages instead of depending on URL redaction.
    if not safe_retry:
        return "YouTube upload outcome is uncertain. Check YouTube Studio and reconcile before any further upload."
    if getattr(exc, "code", "") == "quota_exceeded":
        return "YouTube quota was exceeded before any video bytes were sent. Wait for the quota window before retrying."
    if getattr(exc, "code", "") == "credentials_required" or isinstance(exc, ValueError):
        return "YouTube upload validation or authorization failed before any video bytes were sent. Check the clip and reconnect YouTube."
    return "YouTube upload initialization failed before any video bytes were sent. An explicit retry is available after the delay."


def _record_completion(job: Dict[str, Any], entry: Dict[str, Any], completed_at: float) -> None:
    publishing = job.get("publishing")
    if not isinstance(publishing, list):
        publishing = []
        job["publishing"] = publishing
    publishing.append(
        {
            "platform": "youtube_shorts",
            "schedule_id": entry["id"],
            "clip_index": entry["clip_index"],
            "variant_id": entry.get("variant_id"),
            "privacy_status": "private",
            "publish_at": entry["publish_at"],
            "auto_publish": False,
            "confirmed_at": entry.get("dispatch_started_at"),
            "completed_at": completed_at,
            "result": entry["provider_result"],
        }
    )


def _preflight_state(entry: Dict[str, Any]) -> None:
    state = str(entry.get("status") or "")
    if state == "provider_unknown":
        raise HTTPException(409, {"error": "Provider upload outcome is uncertain. Check YouTube Studio and reconcile; retrying could duplicate the upload.", "code": "provider_state_unknown"})
    if state == "provider_dispatching":
        raise HTTPException(409, {"error": "A dispatch is already in progress.", "code": "dispatch_inflight"})
    if state not in {"approved_pending_publish", "retryable_failed"}:
        raise HTTPException(409, {"error": "Approve this schedule before dispatch.", "code": "schedule_state"})
    if int(entry.get("dispatch_attempts") or 0) >= _MAX_ATTEMPTS:
        raise HTTPException(409, {"error": "Dispatch retry limit reached. Review the provider and create a fresh schedule if appropriate.", "code": "dispatch_retry_limit"})
    retry_after = float(entry.get("retry_after") or 0)
    if retry_after > time.time():
        raise HTTPException(429, {"error": "Wait before explicitly retrying this schedule.", "code": "dispatch_backoff", "retry_after_seconds": int(retry_after - time.time()) + 1})


def dispatch(studio: Any, schedule_id: str, request: ScheduleDispatchRequest) -> Dict[str, Any]:
    from web.v2_routes import _find_schedule

    if not request.confirm or not request.acknowledge_public_publish:
        raise HTTPException(400, {"error": "Confirm dispatch and acknowledge that YouTube will publish publicly at the scheduled time.", "code": "schedule_confirmation_required"})
    with studio._lock:
        job, entry = _find_schedule(studio, schedule_id)
        if entry.get("status") == "provider_scheduled":
            return _response(entry, replayed=True)
        _preflight_state(entry)
        if studio._dict_value(entry.get("request")).get("platform") != "youtube_shorts":
            raise HTTPException(400, {"error": "This provider does not support direct scheduling.", "code": "provider_schedule_unsupported"})
        if str(job.get("status") or "") != "done":
            raise HTTPException(409, {"error": "Only completed projects can be dispatched.", "code": "job_not_ready"})
        _require_no_clip_edit(studio, job)
        _payload, _fingerprint, media = schedule_snapshot(studio, job, entry)
        if media is None or not media.is_file() or media.stat().st_size <= 0:
            raise HTTPException(400, {"error": "Clip media is unavailable.", "code": "media_unavailable"})
    # Never wait for an artifact lock while holding the job lock. Re-read both
    # intent and bytes after acquisition, because a cancellation/edit can land
    # while waiting for an existing writer to finish.
    with studio._artifact_lock(str(media)), tempfile.TemporaryDirectory(prefix="shorts-schedule-assets-") as asset_scratch:
        with studio._lock:
            job, entry = _find_schedule(studio, schedule_id)
            if entry.get("status") == "provider_scheduled":
                return _response(entry, replayed=True)
            _preflight_state(entry)
            if str(job.get("status") or "") != "done":
                raise HTTPException(409, {"error": "Project changed before dispatch.", "code": "job_not_ready"})
            _require_no_clip_edit(studio, job)
            payload, fingerprint, selected_media = schedule_snapshot(studio, job, entry)
            if selected_media != media or fingerprint != entry.get("approval_fingerprint"):
                entry["status"] = "pending_review"
                entry.pop("approval_fingerprint", None)
                entry.pop("approved_payload", None)
                studio._persist_job_locked(job)
                raise HTTPException(409, {"error": "Clip, assets or publish metadata changed after approval. Review this schedule again.", "code": "approval_stale"})
            try:
                publish_request = PublishRequest.model_validate(payload)
            except ValueError as exc:
                raise HTTPException(409, {"error": "Schedule is no longer valid; check its publish time and metadata.", "code": "schedule_expired"}) from exc
            publish_time = datetime.fromisoformat(str(publish_request.publish_at).replace("Z", "+00:00"))
            if publish_time.astimezone(timezone.utc) <= datetime.now(timezone.utc) + timedelta(seconds=_MINIMUM_LEAD_SECONDS):
                raise HTTPException(409, {"error": "Choose a publish time at least five minutes in the future before dispatch.", "code": "schedule_too_soon"})
            if len(str(payload.get("description") or "").encode("utf-8")) > 5000:
                raise HTTPException(400, {"error": "YouTube description exceeds 5000 UTF-8 bytes.", "code": "validation_error"})
            policy = _policy(studio, job, payload)
            if not youtube_oauth_status().get("authorized"):
                raise HTTPException(400, {"error": "Connect YouTube before dispatching this schedule.", "code": "credentials_required"})
            from web.v2_routes import _clip_selection

            index, short, _variant = _clip_selection(studio, job, entry.get("clip_index"), entry.get("variant_id"))
            try:
                thumbnail, captions = _immutable_assets(studio, job, short, Path(asset_scratch))
            except OSError as exc:
                raise HTTPException(400, {"error": "Could not prepare the approved thumbnail and caption assets.", "code": "media_unavailable"}) from exc
            # Verify the source again after copying; even an external writer
            # cannot silently substitute a thumbnail during this preparation.
            _copied_payload, copied_fingerprint, _copied_media = schedule_snapshot(studio, job, entry)
            if copied_fingerprint != fingerprint:
                raise HTTPException(409, {"error": "Clip or assets changed while preparing dispatch. Review the schedule again.", "code": "approval_stale"})
            entry["policy"] = policy
            entry["status"] = "provider_dispatching"
            entry["dispatch_attempts"] = int(entry.get("dispatch_attempts") or 0) + 1
            entry["dispatch_started_at"] = time.time()
            entry.setdefault("dispatch_key", secrets.token_hex(24))
            entry.pop("provider_error", None)
            dispatch_key = entry["dispatch_key"]
            # This write is the durable claim. A restart can never blindly
            # resend an entry whose remote completion was not persisted.
            studio._persist_job_locked(job)
        try:
            uploaded = upload_youtube_video(
                media,
                title=publish_request.title or "Untitled highlight",
                description=publish_request.description or "",
                tags=publish_request.tags,
                category_id=publish_request.category_id,
                privacy_status="private",
                publish_at=publish_request.publish_at,
                idempotency_key=f"schedule:{schedule_id}:{dispatch_key}",
                thumbnail_path=thumbnail,
                captions_path=captions,
                caption_language=publish_request.caption_language,
                caption_name=publish_request.caption_name,
                captions_draft=publish_request.captions_draft,
            )
            if not isinstance(uploaded, dict) or not uploaded.get("video_id"):
                raise YouTubePublishError("Provider response omitted the uploaded video id.")
        except (ValueError, OSError, RuntimeError, requests.RequestException) as exc:
            safe_retry = isinstance(exc, ValueError) or (
                isinstance(exc, YouTubePublishError) and exc.external_state == "not_created"
            )
            safe_message = _provider_error_message(exc, safe_retry=safe_retry)
            with studio._lock:
                job, entry = _find_schedule(studio, schedule_id)
                entry["status"] = "retryable_failed" if safe_retry else "provider_unknown"
                entry["provider_error"] = {
                    "code": str(getattr(exc, "code", "publish_failed")),
                    "message": safe_message,
                    "at": time.time(),
                }
                if safe_retry:
                    entry["retry_after"] = time.time() + min(900, 30 * (2 ** (entry["dispatch_attempts"] - 1)))
                studio._append_job_log(job, "schedule", f"YouTube dispatch outcome: {entry['status']}")
                studio._persist_job_locked(job)
                state = entry["status"]
            raise HTTPException(
                getattr(exc, "status_code", 502),
                {"error": safe_message, "code": "dispatch_failed" if safe_retry else "provider_state_unknown", "status": state, "can_retry": safe_retry},
            ) from exc
        with studio._lock:
            job, entry = _find_schedule(studio, schedule_id)
            entry["status"] = "provider_scheduled"
            entry["provider_result"] = redact_structure(uploaded)
            entry["dispatched_at"] = time.time()
            entry.pop("retry_after", None)
            _record_completion(job, entry, entry["dispatched_at"])
            studio._append_job_log(job, "schedule", "YouTube accepted the scheduled private upload")
            studio._persist_job_locked(job)
            return _response(entry)


def _same_timestamp(left: object, right: object) -> bool:
    try:
        a = datetime.fromisoformat(str(left).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(right).replace("Z", "+00:00"))
        return a.tzinfo is not None and b.tzinfo is not None and a == b
    except ValueError:
        return False


def reconcile(studio: Any, schedule_id: str, request: ScheduleReconcileRequest) -> Dict[str, Any]:
    from web.v2_routes import _find_schedule

    if not request.confirm:
        raise HTTPException(400, {"error": "Confirm reconciliation of the video found in YouTube Studio.", "code": "schedule_confirmation_required"})
    with studio._lock:
        _job, entry = _find_schedule(studio, schedule_id)
        if entry.get("status") != "provider_unknown":
            raise HTTPException(409, {"error": "Only an uncertain provider dispatch can be reconciled.", "code": "schedule_state"})
        approved = dict(studio._dict_value(entry.get("approved_payload")))
        dispatch_key = entry.get("dispatch_key")
    try:
        result = youtube_video_schedule(request.video_id)
    except (ValueError, OSError, RuntimeError, requests.RequestException) as exc:
        raise HTTPException(getattr(exc, "status_code", 502), {"error": "Could not verify this video through the connected YouTube account. Check the video id and authorization.", "code": "reconcile_failed"}) from exc
    if (
        result.get("video_id") != request.video_id
        or result.get("privacy_status") != "private"
        or result.get("upload_status") not in {"uploaded", "processed"}
        or not _same_timestamp(result.get("publish_at"), approved.get("publish_at"))
        or result.get("title") != approved.get("title")
        or result.get("description") != approved.get("description")
        or result.get("category_id") != str(approved.get("category_id") or "22")
        or sorted(result.get("tags") or []) != sorted(approved.get("tags") or [])
    ):
        raise HTTPException(409, {"error": "The provider video does not match the approved private schedule. Review it in YouTube Studio.", "code": "reconcile_mismatch"})
    with studio._lock:
        job, entry = _find_schedule(studio, schedule_id)
        if entry.get("status") != "provider_unknown" or dispatch_key != entry.get("dispatch_key"):
            raise HTTPException(409, {"error": "Schedule changed during reconciliation.", "code": "schedule_state"})
        entry["status"] = "provider_scheduled"
        entry["provider_result"] = {"video_id": result["video_id"], "url": result["url"], "privacy_status": "private", "publish_at": result["publish_at"], "status": "reconciled"}
        entry["reconciled_at"] = time.time()
        entry.pop("provider_error", None)
        _record_completion(job, entry, entry["reconciled_at"])
        studio._append_job_log(job, "schedule", "YouTube scheduled upload reconciled from provider metadata")
        studio._persist_job_locked(job)
        return _response(entry)


def refresh(studio: Any, schedule_id: str, request: ScheduleRefreshRequest) -> Dict[str, Any]:
    """Explicitly observe a known video; never mutate or cancel it remotely."""
    from web.v2_routes import _find_schedule

    if not request.confirm:
        raise HTTPException(400, {"error": "Confirm refreshing this video's state from YouTube.", "code": "schedule_confirmation_required"})
    with studio._lock:
        _job, entry = _find_schedule(studio, schedule_id)
        if entry.get("status") != "provider_scheduled":
            raise HTTPException(409, {"error": "Only a known provider schedule can be refreshed.", "code": "schedule_state"})
        video_id = str(studio._dict_value(entry.get("provider_result")).get("video_id") or "")
        publish_at = entry.get("publish_at")
    try:
        result = youtube_video_schedule(video_id)
    except (ValueError, OSError, RuntimeError, requests.RequestException) as exc:
        # Empty results can mean changed account/scope, not just deletion.
        # Keeping the active audit prevents falsely declaring it cancelled.
        raise HTTPException(409, {"error": "YouTube could not verify this video for the connected owner. Check its state in YouTube Studio.", "code": "provider_refresh_unverified"}) from exc
    if result.get("video_id") != video_id or not result.get("owner_verified"):
        raise HTTPException(409, {"error": "Reconnect the owner of this YouTube upload before refreshing its provider state.", "code": "provider_refresh_unverified"})
    privacy = result.get("privacy_status")
    upload_state = result.get("upload_status")
    if upload_state == "deleted":
        state = "provider_removed"
    elif upload_state in {"failed", "rejected"}:
        state = "provider_rejected"
    elif privacy == "public":
        state = "provider_published"
    elif privacy in {"private", "unlisted"} and not result.get("publish_at"):
        state = "provider_unscheduled"
    elif privacy == "private" and _same_timestamp(result.get("publish_at"), publish_at):
        state = "provider_scheduled"
    else:
        raise HTTPException(409, {"error": "The provider schedule changed. Review its current release time and privacy in YouTube Studio.", "code": "provider_schedule_changed"})
    with studio._lock:
        job, entry = _find_schedule(studio, schedule_id)
        if entry.get("status") != "provider_scheduled" or video_id != str(studio._dict_value(entry.get("provider_result")).get("video_id") or ""):
            raise HTTPException(409, {"error": "Schedule changed while refreshing provider state.", "code": "schedule_state"})
        entry["status"] = state
        entry["provider_observed_at"] = time.time()
        entry["provider_observation"] = {
            "video_id": video_id,
            "privacy_status": privacy,
            "publish_at": result.get("publish_at") or None,
            "upload_status": upload_state,
        }
        studio._append_job_log(job, "schedule", f"YouTube schedule refreshed: {state}")
        studio._persist_job_locked(job)
        return _response(entry)
