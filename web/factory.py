"""Reviewable Shorts Factory package and approval checkpoints.

The factory deliberately separates generation from distribution.  A completed
job can expose one portable manifest containing the generated clip, caption,
hook, thumbnail, metadata, and platform handoff for every clip, but no upload
is started until a human records an approval checkpoint and submits the normal
publish confirmation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunsplit

from web.publishing import PLATFORMS, build_publish_plan, direct_platform_status


FACTORY_PACKAGE_VERSION = "1.0"


def initial_factory_state(enabled: bool = False) -> Dict[str, Any]:
    """Return the durable, credential-free factory state for a project."""
    return {
        "package_version": FACTORY_PACKAGE_VERSION,
        "enabled": bool(enabled),
        "status": "processing" if enabled else "not_requested",
        "approvals": [],
    }


def _approval_map(factory: Any) -> Dict[int, Dict[str, Any]]:
    """Read the most recent decision for each clip from tolerant persisted data."""
    values = factory.get("approvals") if isinstance(factory, dict) else []
    result: Dict[int, Dict[str, Any]] = {}
    if not isinstance(values, list):
        return result
    for value in values:
        if not isinstance(value, dict):
            continue
        try:
            index = int(value.get("clip_index"))
        except (TypeError, ValueError, OverflowError):
            continue
        decision = str(value.get("decision") or "").strip().lower()
        if decision not in {"approved", "rejected"}:
            continue
        result[index] = {
            "clip_index": index,
            "decision": decision,
            "note": str(value.get("note") or "")[:1000] or None,
            "decided_at": value.get("decided_at"),
        }
    return result


def _package_status(job_status: str, clip_count: int, decisions: Dict[int, Dict[str, Any]], enabled: bool) -> str:
    if not enabled:
        return "not_requested"
    if job_status not in {"done", "error", "cancelled", "interrupted"}:
        return "processing"
    if not clip_count:
        return "ready_for_review"
    selected = [decisions.get(index, {}).get("decision") for index in range(clip_count)]
    if all(value == "approved" for value in selected):
        return "approved"
    if all(value == "rejected" for value in selected):
        return "rejected"
    if any(value in {"approved", "rejected"} for value in selected):
        return "partially_reviewed"
    return "ready_for_review"


def _source_descriptor(request: Dict[str, Any]) -> Dict[str, Any]:
    raw = str(request.get("url") or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        secret_keys = {"token", "access_token", "signature", "sig", "expires", "expiry", "auth"}
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in secret_keys]
        safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        return {"kind": "url", "value": safe_url}
    name = Path(raw).name if raw else ""
    kind = "upload" if "uploads" in {part.casefold() for part in Path(raw).parts} else "local_file"
    return {"kind": kind, "name": name or "source"}


def factory_manifest(studio: Any, job: Dict[str, Any]) -> Dict[str, Any]:
    """Build a safe in-app factory manifest from a job record.

    The caller normally holds ``studio._lock``.  Only route URLs and creator
    metadata are returned; local absolute media paths are intentionally left
    out of the manifest.
    """
    job_id = str(job.get("id") or "")
    request = studio._dict_value(job.get("request"))
    raw_shorts = studio._dict_items(job.get("raw_shorts"))
    public_shorts = studio._public_shorts(raw_shorts, job_id)
    factory = job.get("factory") if isinstance(job.get("factory"), dict) else initial_factory_state(False)
    enabled = bool(factory.get("enabled"))
    decisions = _approval_map(factory)
    transcript = studio._dict_value(job.get("raw_transcript"))
    has_captions = bool(studio._dict_items(transcript.get("segments")))
    clips: List[Dict[str, Any]] = []

    for index, raw_short in enumerate(raw_shorts):
        public_short = public_shorts[index] if index < len(public_shorts) else dict(raw_short)
        metadata = studio._creator_metadata(raw_short)
        safe_clip_url = public_short.get("play_url") or public_short.get("clip_url")
        safe_thumbnail_url = public_short.get("thumbnail_url")
        plan_item = dict(public_short)
        plan_item["creator_metadata"] = metadata
        exports: Dict[str, Any] = {}
        for platform in PLATFORMS:
            plan = build_publish_plan(platform, [plan_item])
            plan["oauth_status"] = direct_platform_status().get(platform, {})
            exports[platform] = plan
        decision = decisions.get(index, {})
        clips.append(
            {
                "clip_index": index,
                "status": decision.get("decision") or "pending",
                "decision": decision or None,
                "title": str(raw_short.get("title") or metadata["title"])[:100],
                "hook": str(raw_short.get("hook_sentence") or metadata["thumbnail_text"])[:500],
                "virality_reason": str(raw_short.get("virality_reason") or "")[:1000],
                "score": raw_short.get("score"),
                "start_time": raw_short.get("start_time"),
                "end_time": raw_short.get("end_time"),
                "clip_url": safe_clip_url,
                "thumbnail_url": safe_thumbnail_url,
                "captions": {
                    "available": has_captions,
                    "srt_url": f"/api/v1/jobs/{job_id}/clip/{index}/captions?format=srt" if has_captions else None,
                    "vtt_url": f"/api/v1/jobs/{job_id}/clip/{index}/captions?format=vtt" if has_captions else None,
                },
                "metadata": metadata,
                "platform_exports": exports,
            }
        )

    package_status = _package_status(str(job.get("status") or "unknown"), len(clips), decisions, enabled)
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for clip in clips:
        state = str(clip.get("status") or "pending")
        counts[state] = counts.get(state, 0) + 1
    return {
        "job_id": job_id,
        "package_version": str(factory.get("package_version") or FACTORY_PACKAGE_VERSION),
        "enabled": enabled,
        "status": package_status,
        "source": _source_descriptor(request),
        "job_status": str(job.get("status") or "unknown"),
        "approval_required": True,
        "approval_policy": {
            "human_checkpoint_required": True,
            "public_upload_requires_allow_public": True,
            "public_auto_publish_requires_opt_in": True,
        },
        "approval_summary": counts,
        "clips": clips,
        "export_url": f"/api/v1/jobs/{job_id}/export",
        "approval_url": f"/api/v1/jobs/{job_id}/factory/approve",
        "token_storage": "process_memory_only",
    }


def approved_for_clip(job: Dict[str, Any], clip_index: int) -> bool:
    """Return whether a factory clip has an explicit approval decision."""
    factory = job.get("factory") if isinstance(job.get("factory"), dict) else {}
    return _approval_map(factory).get(int(clip_index), {}).get("decision") == "approved"
