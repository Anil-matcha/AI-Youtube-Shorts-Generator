"""Analytics feedback and A/B variant routes for the v1 beta API."""

from __future__ import annotations

import importlib
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from web.analytics import aggregate, feedback, make_record
from web.models import AnalyticsUpdate, VariantCreate, VariantUpdate


router = APIRouter(tags=["experiments"])


def _studio() -> Any:
    return importlib.import_module("web.app")


def _find_job(studio: Any, job_id: str) -> Dict[str, Any]:
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, {"error": "job not found", "code": "job_not_found"})
        return job


def _variant_public(studio: Any, job: Dict[str, Any], variant: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(variant)
    clip_index = int(item.get("clip_index") or 0)
    shorts = studio._dict_items(job.get("raw_shorts"))
    source_short = shorts[clip_index] if 0 <= clip_index < len(shorts) else {}
    item["clip_index"] = clip_index
    item["clip_url"] = None
    if source_short:
        public = studio._public_shorts([source_short], str(job.get("id") or ""))
        if public:
            item["clip_url"] = public[0].get("play_url") or public[0].get("clip_url")
    item["analytics"] = aggregate(job.get("analytics") if isinstance(job.get("analytics"), list) else [], variant_id=str(item.get("id") or ""))
    return item


@router.get("/api/analytics/summary", tags=["experiments"])
def analytics_summary(platform: Optional[str] = Query(default=None, max_length=40)) -> Dict[str, Any]:
    studio = _studio()
    records: List[Dict[str, Any]] = []
    variants: List[Dict[str, Any]] = []
    with studio._lock:
        for job in studio._jobs.values():
            records.extend(item for item in studio._dict_items(job.get("analytics")))
            variants.extend(item for item in studio._dict_items(job.get("variants")))
    return {"platform": platform, "feedback": feedback([item for item in records if not platform or item.get("platform") == platform], variants)}


@router.get("/api/jobs/{job_id}/variants", tags=["experiments"])
def list_variants(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    job = _find_job(studio, job_id)
    with studio._lock:
        variants = studio._dict_items(job.get("variants"))
        return {"job_id": job_id, "variants": [_variant_public(studio, job, item) for item in variants]}


@router.post("/api/jobs/{job_id}/variants", tags=["experiments"])
def create_variant(job_id: str, request: VariantCreate) -> Dict[str, Any]:
    studio = _studio()
    job = _find_job(studio, job_id)
    with studio._lock:
        shorts = studio._dict_items(job.get("raw_shorts"))
        if request.clip_index >= len(shorts):
            raise HTTPException(404, {"error": "clip not found", "code": "clip_not_found"})
        base = studio._creator_metadata(shorts[request.clip_index])
        variant = {
            "id": "var_" + uuid.uuid4().hex[:16],
            "name": request.name,
            "clip_index": request.clip_index,
            "platform": request.platform,
            "title": request.title or base["title"],
            "description": request.description or base["description"],
            "hook": request.hook or str(shorts[request.clip_index].get("hook_sentence") or base["title"]),
            "thumbnail_text": request.thumbnail_text or base["thumbnail_text"],
            "status": "draft",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        variants = job.get("variants")
        if not isinstance(variants, list):
            variants = []
            job["variants"] = variants
        variants.append(variant)
        studio._append_job_log(job, "experiment", f"Created A/B variant {variant['name']}")
        studio._persist_job_locked(job)
        return {"variant": _variant_public(studio, job, variant)}


@router.patch("/api/jobs/{job_id}/variants/{variant_id}", tags=["experiments"])
def update_variant(job_id: str, variant_id: str, request: VariantUpdate) -> Dict[str, Any]:
    studio = _studio()
    job = _find_job(studio, job_id)
    with studio._lock:
        variants = studio._dict_items(job.get("variants"))
        variant = next((item for item in variants if str(item.get("id")) == variant_id), None)
        if variant is None:
            raise HTTPException(404, {"error": "variant not found", "code": "variant_not_found"})
        for key, value in request.model_dump(exclude_unset=True).items():
            if value is not None:
                variant[key] = value
        variant["updated_at"] = time.time()
        studio._append_job_log(job, "experiment", f"Updated A/B variant {variant_id}")
        studio._persist_job_locked(job)
        return {"variant": _variant_public(studio, job, variant)}


@router.get("/api/jobs/{job_id}/analytics", tags=["experiments"])
def job_analytics(
    job_id: str,
    platform: Optional[str] = Query(default=None, max_length=40),
    variant_id: Optional[str] = Query(default=None, max_length=80),
) -> Dict[str, Any]:
    studio = _studio()
    job = _find_job(studio, job_id)
    with studio._lock:
        records = studio._dict_items(job.get("analytics"))
        variants = studio._dict_items(job.get("variants"))
    selected_records = [
        item
        for item in records
        if (not platform or item.get("platform") == platform)
        and (not variant_id or str(item.get("variant_id") or "") == variant_id)
    ]
    return {
        "job_id": job_id,
        "summary": aggregate(selected_records),
        "feedback": feedback(selected_records, variants),
        "records": records[-200:],
    }


@router.post("/api/jobs/{job_id}/analytics", tags=["experiments"])
def record_analytics(job_id: str, request: AnalyticsUpdate) -> Dict[str, Any]:
    return _record_analytics(job_id, request, None)


@router.post("/api/jobs/{job_id}/variants/{variant_id}/analytics", tags=["experiments"])
def record_variant_analytics(job_id: str, variant_id: str, request: AnalyticsUpdate) -> Dict[str, Any]:
    return _record_analytics(job_id, request, variant_id)


def _record_analytics(job_id: str, request: AnalyticsUpdate, route_variant_id: Optional[str]) -> Dict[str, Any]:
    studio = _studio()
    job = _find_job(studio, job_id)
    payload = request.model_dump()
    selected_variant = route_variant_id or payload.get("variant_id")
    with studio._lock:
        variants = studio._dict_items(job.get("variants"))
        if selected_variant and not any(str(item.get("id")) == str(selected_variant) for item in variants):
            raise HTTPException(404, {"error": "variant not found", "code": "variant_not_found"})
        payload["variant_id"] = selected_variant
        record = make_record(payload)
        analytics_records = job.get("analytics")
        if not isinstance(analytics_records, list):
            analytics_records = []
            job["analytics"] = analytics_records
        analytics_records.append(record)
        if len(analytics_records) > 2000:
            del analytics_records[:-2000]
        studio._append_job_log(job, "analytics", f"Recorded {record['platform']} analytics")
        studio._persist_job_locked(job)
        records = studio._dict_items(job.get("analytics"))
        return {
            "record": record,
            "summary": aggregate(records, platform=record["platform"], variant_id=selected_variant),
            "feedback": feedback(records, variants),
        }
