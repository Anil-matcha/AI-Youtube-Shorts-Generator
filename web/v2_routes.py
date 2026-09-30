"""v2 foundation routes: story search, policy preflight, and reviewable scheduling."""

from __future__ import annotations

import importlib
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query

from web.factory import approved_for_clip
from web.models import (
    PolicyCheckRequest,
    ScheduleCreateRequest,
    ScheduleDecisionRequest,
    StorySearchRequest,
)
from web.policy import evaluate_publish_policy, policy_summary
from web.security import redact_structure
from web.story_search import search_jobs


router = APIRouter(tags=["v2 foundation"])


def _studio() -> Any:
    return importlib.import_module("web.app")


def _clip_selection(
    studio: Any,
    job: Dict[str, Any],
    clip_index: Optional[int],
    variant_id: Optional[str],
) -> Tuple[int, Dict[str, Any], Optional[Dict[str, Any]]]:
    shorts = studio._dict_items(job.get("raw_shorts"))
    variant: Optional[Dict[str, Any]] = None
    index = clip_index if clip_index is not None else 0
    if variant_id:
        variant = next(
            (item for item in studio._dict_items(job.get("variants")) if str(item.get("id")) == variant_id),
            None,
        )
        if variant is None:
            raise HTTPException(404, {"error": "variant not found", "code": "variant_not_found"})
        try:
            index = int(variant.get("clip_index") or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(400, {"error": "variant clip index is invalid", "code": "validation_error"}) from exc
        if clip_index is not None and clip_index != index:
            raise HTTPException(400, {"error": "clip_index does not match variant", "code": "validation_error"})
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, {"error": "clip not found", "code": "clip_not_found"})
    return index, shorts[index], variant


def _policy_payload(
    studio: Any,
    job: Optional[Dict[str, Any]],
    request: Any,
    *,
    index: Optional[int] = None,
    short: Optional[Dict[str, Any]] = None,
    variant: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    values = request.model_dump(exclude_none=True) if hasattr(request, "model_dump") else dict(request)
    if short is not None:
        metadata = studio._creator_metadata(short)
        if variant:
            metadata = {**metadata, **variant}
        values.setdefault("title", metadata.get("title"))
        values.setdefault("description", metadata.get("description"))
        values.setdefault("hook_sentence", short.get("hook_sentence"))
        values["start_time"] = short.get("start_time")
        values["end_time"] = short.get("end_time")
    if job is not None:
        factory = job.get("factory") if isinstance(job.get("factory"), dict) else {}
        enabled = bool(factory.get("enabled"))
        approved = not enabled or (index is not None and approved_for_clip(job, index))
    else:
        approved = True
    values.pop("job_id", None)
    values.pop("note", None)
    values.pop("confirm", None)
    return {"values": values, "factory_approved": approved}


@router.post("/api/story/search")
def story_search(request: StorySearchRequest) -> Dict[str, Any]:
    studio = _studio()
    wanted = set(request.job_ids)
    with studio._lock:
        jobs = [
            dict(job)
            for job_id, job in studio._jobs.items()
            if not wanted or job_id in wanted
        ]
    jobs = jobs[:500]
    return search_jobs(jobs, request.query, limit=request.limit)


@router.post("/api/policy/check")
def policy_check(request: PolicyCheckRequest) -> Dict[str, Any]:
    studio = _studio()
    job: Optional[Dict[str, Any]] = None
    short: Optional[Dict[str, Any]] = None
    variant: Optional[Dict[str, Any]] = None
    index = request.clip_index
    if request.job_id:
        with studio._lock:
            job = studio._jobs.get(request.job_id)
            if not job:
                raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
            index, short, variant = _clip_selection(studio, job, request.clip_index, request.variant_id)
    payload = _policy_payload(studio, job, request, index=index, short=short, variant=variant)
    result = evaluate_publish_policy(payload["values"], factory_approved=payload["factory_approved"])
    return {"policy": result, "job_id": request.job_id, "clip_index": index, "variant_id": request.variant_id}


@router.post("/api/scheduler")
def create_schedule(request: ScheduleCreateRequest) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(request.job_id)
        if not job:
            raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
        if str(job.get("status") or "") != "done":
            raise HTTPException(409, {"error": "only completed projects can be scheduled", "code": "job_not_ready"})
        index, short, variant = _clip_selection(studio, job, request.clip_index, request.variant_id)
        payload = _policy_payload(studio, job, request, index=index, short=short, variant=variant)
        policy = evaluate_publish_policy(payload["values"], scheduled=True, factory_approved=payload["factory_approved"])
        if policy["status"] == "blocked":
            raise HTTPException(409, {"error": "schedule failed policy preflight", "code": "policy_blocked", "policy": policy})
        entries = job.get("schedule") if isinstance(job.get("schedule"), list) else []
        if len(entries) >= 200:
            raise HTTPException(429, {"error": "project schedule is full", "code": "schedule_limit"})
        schedule_id = uuid.uuid4().hex[:16]
        stored_request = request.model_dump(exclude={"job_id", "note", "confirm"})
        # A schedule is a review intent. Keep metadata needed to recreate the
        # intent, but never persist or echo local asset paths in this queue.
        stored_request.pop("thumbnail_path", None)
        stored_request.pop("captions_path", None)
        entry = {
            "id": schedule_id,
            "job_id": request.job_id,
            "clip_index": index,
            "variant_id": request.variant_id,
            "project_name": str(job.get("name") or "Untitled project")[:100],
            "status": "pending_review",
            "created_at": time.time(),
            "publish_at": request.publish_at,
            "note": request.note,
            "request": stored_request,
            "policy": policy,
        }
        entries.append(entry)
        job["schedule"] = entries
        studio._append_job_log(job, "schedule", f"Queued {request.platform} entry for review")
        studio._persist_job_locked(job)
    return {"status": entry["status"], "entry": redact_structure(entry)}


def _all_schedule_entries(studio: Any, wanted_status: Optional[str] = None) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    with studio._lock:
        for job in studio._jobs.values():
            if not isinstance(job, dict):
                continue
            for raw in studio._dict_items(job.get("schedule")):
                if wanted_status and str(raw.get("status") or "") != wanted_status:
                    continue
                item = dict(raw)
                item["project_name"] = str(job.get("name") or item.get("project_name") or "Untitled project")[:100]
                entries.append(item)
    # ISO timestamps sort lexically when they are normalized by the request
    # model; keep malformed historical values bounded rather than letting one
    # record take down the scheduler list.
    entries.sort(
        key=lambda item: (
            str(item.get("publish_at") or "~"),
            _safe_timestamp(item.get("created_at")),
        )
    )
    return [redact_structure(item) for item in entries[:500]]


def _safe_timestamp(value: object) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return converted if converted == converted and abs(converted) != float("inf") else 0.0


@router.get("/api/scheduler")
def list_schedule(status: Optional[str] = Query(default=None, max_length=40)) -> Dict[str, Any]:
    studio = _studio()
    entries = _all_schedule_entries(studio, status.strip() if status else None)
    return {
        "entries": entries,
        "count": len(entries),
        "notice": "Entries are reviewable intents only; Shorts Studio never uploads from the scheduler automatically.",
    }


def _find_schedule(studio: Any, schedule_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    safe_id = str(schedule_id or "").strip()
    if not safe_id or len(safe_id) > 32 or any(char not in "0123456789abcdef" for char in safe_id.lower()):
        raise HTTPException(404, {"error": "schedule entry not found", "code": "schedule_not_found"})
    for job in studio._jobs.values():
        if not isinstance(job, dict):
            continue
        for entry in studio._dict_items(job.get("schedule")):
            if str(entry.get("id") or "") == safe_id:
                return job, entry
    raise HTTPException(404, {"error": "schedule entry not found", "code": "schedule_not_found"})


@router.post("/api/scheduler/{schedule_id}/decision")
def decide_schedule(schedule_id: str, request: ScheduleDecisionRequest) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job, entry = _find_schedule(studio, schedule_id)
        if str(entry.get("status") or "") not in {"pending_review", "approved_pending_publish"}:
            raise HTTPException(409, {"error": "schedule entry is no longer reviewable", "code": "schedule_state"})
        if request.decision == "approved" and str(studio._dict_value(entry.get("policy")).get("status")) == "blocked":
            raise HTTPException(409, {"error": "blocked policy result cannot be approved", "code": "policy_blocked"})
        entry["status"] = "approved_pending_publish" if request.decision == "approved" else "rejected"
        entry["decision"] = request.decision
        entry["decision_note"] = request.note
        entry["decided_at"] = time.time()
        studio._append_job_log(job, "schedule", f"Schedule {request.decision} decision recorded")
        studio._persist_job_locked(job)
        result = redact_structure(dict(entry))
    return {"status": result["status"], "entry": result}


@router.delete("/api/scheduler/{schedule_id}")
def cancel_schedule(schedule_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job, entry = _find_schedule(studio, schedule_id)
        if str(entry.get("status") or "") in {"published", "cancelled", "rejected"}:
            raise HTTPException(409, {"error": "schedule entry cannot be cancelled", "code": "schedule_state"})
        entry["status"] = "cancelled"
        entry["cancelled_at"] = time.time()
        studio._append_job_log(job, "schedule", "Schedule entry cancelled")
        studio._persist_job_locked(job)
        result = redact_structure(dict(entry))
    return {"status": "cancelled", "entry": result}


@router.get("/api/publishing/telemetry")
@router.get("/api/publishing/quota")
def publishing_telemetry() -> Dict[str, Any]:
    studio = _studio()
    platforms: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "attempts": 0,
            "completed": 0,
            "quota_errors": 0,
            "last_completed_at": None,
            "last_error_at": None,
            "quota_status": "unknown",
        }
    )
    policies: List[Dict[str, Any]] = []
    with studio._lock:
        jobs = list(studio._jobs.values())
        for job in jobs:
            for item in studio._dict_items(job.get("publishing"))[:1000]:
                platform = str(item.get("platform") or "unknown")[:40]
                state = platforms[platform]
                state["attempts"] += 1
                state["completed"] += 1
                state["last_completed_at"] = max(
                    _safe_timestamp(item.get("completed_at")),
                    _safe_timestamp(state["last_completed_at"]),
                ) or None
            for item in studio._dict_items(job.get("publishing_errors"))[:1000]:
                platform = str(item.get("platform") or "unknown")[:40]
                state = platforms[platform]
                state["attempts"] += 1
                state["last_error_at"] = max(
                    _safe_timestamp(item.get("at")),
                    _safe_timestamp(state["last_error_at"]),
                ) or None
                if str(item.get("code") or "") == "quota_exceeded":
                    state["quota_errors"] += 1
                    state["quota_status"] = "throttled"
            for entry in studio._dict_items(job.get("schedule"))[:500]:
                policy = entry.get("policy") if isinstance(entry.get("policy"), dict) else {}
                if len(policies) < 5000:
                    policies.append(policy)
    for state in platforms.values():
        state["quota_status"] = state["quota_status"] or "unknown"
    return {
        "generated_at": time.time(),
        "platforms": dict(platforms),
        "policy_summary": policy_summary(policies),
        "notice": "Provider quota is reported from observed API responses; no provider quota is inferred or bypassed.",
    }
