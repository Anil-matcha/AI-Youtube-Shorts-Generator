"""Cross-project performance, publishing, and creator-style dashboards."""

from __future__ import annotations

import importlib
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from web.analytics import aggregate, feedback, make_record
from web.models import AnalyticsImportRequest, StyleProfileLearnRequest, StyleProfileUpdate
from web.model_manager import delete as delete_model
from web.model_manager import download as download_model
from web.model_manager import list_models
from web.style_memory import learn_profile


router = APIRouter(tags=["dashboard"])


def _studio() -> Any:
    return importlib.import_module("web.app")


def _dashboard_payload(platform: Optional[str] = None) -> Dict[str, Any]:
    studio = _studio()
    wanted_platform = str(platform or "").strip().lower()
    records: List[Dict[str, Any]] = []
    variants: List[Dict[str, Any]] = []
    publishing: List[Dict[str, Any]] = []
    project_counts: Dict[str, int] = defaultdict(int)
    project_names: Dict[str, str] = {}
    with studio._lock:
        jobs = [dict(job) for job in studio._jobs.values()]
        for job in jobs:
            job_id = str(job.get("id") or "")
            project_names[job_id] = str(job.get("name") or "Untitled project")[:100]
            project_counts[str(job.get("status") or "unknown")] += 1
            for record in studio._dict_items(job.get("analytics")):
                if not wanted_platform or str(record.get("platform") or "").lower() == wanted_platform:
                    item = dict(record)
                    item["job_id"] = job_id
                    records.append(item)
            for variant in studio._dict_items(job.get("variants")):
                item = dict(variant)
                item["job_id"] = job_id
                item["project_name"] = project_names[job_id]
                variants.append(item)
            for entry in studio._dict_items(job.get("publishing")):
                item = {
                    "job_id": job_id,
                    "project_name": project_names[job_id],
                    "platform": str(entry.get("platform") or ""),
                    "clip_index": entry.get("clip_index"),
                    "variant_id": entry.get("variant_id"),
                    "privacy_status": entry.get("privacy_status"),
                    "publish_at": entry.get("publish_at"),
                    "completed_at": entry.get("completed_at"),
                    "auto_publish": bool(entry.get("auto_publish")),
                    "status": str(studio._dict_value(entry.get("result")).get("status") or "uploaded"),
                }
                if not wanted_platform or item["platform"].lower() == wanted_platform:
                    publishing.append(item)

    overall = aggregate(records)
    feedback_payload = feedback(records, variants)
    by_platform: List[Dict[str, Any]] = []
    platforms = sorted({str(item.get("platform") or "") for item in records if item.get("platform")})
    for value in platforms:
        by_platform.append({"platform": value, **aggregate(records, platform=value)})

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    variant_names: Dict[str, str] = {}
    variant_platforms: Dict[str, str] = {}
    for variant in variants:
        key = f"{variant.get('job_id')}:{variant.get('id')}"
        variant_names[key] = str(variant.get("name") or variant.get("id") or "Variant")[:80]
        variant_platforms[key] = str(variant.get("platform") or "")
    for record in records:
        job_id = str(record.get("job_id") or "")
        variant_id = str(record.get("variant_id") or "baseline")
        grouped[f"{job_id}:{variant_id}"].append(record)
    top_variants: List[Dict[str, Any]] = []
    for key, grouped_records in grouped.items():
        job_id, _, variant_id = key.partition(":")
        metrics = aggregate(grouped_records)
        score = min(1.0, float(metrics.get("completion_rate") or 0.0) * 0.55 + float(metrics.get("engagement_rate") or 0.0) * 0.45)
        top_variants.append(
            {
                "job_id": job_id,
                "project_name": project_names.get(job_id, "Untitled project"),
                "variant_id": None if variant_id == "baseline" else variant_id,
                "name": "Base clip" if variant_id == "baseline" else variant_names.get(key, variant_id),
                "platform": variant_platforms.get(key),
                "score": round(score, 6),
                **metrics,
            }
        )
    top_variants.sort(key=lambda item: (float(item.get("score") or 0), int(item.get("views") or 0)), reverse=True)

    publishing_by_platform: Dict[str, int] = defaultdict(int)
    for item in publishing:
        publishing_by_platform[str(item.get("platform") or "unknown")] += 1
    publishing.sort(key=lambda item: float(item.get("completed_at") or 0), reverse=True)
    return {
        "generated_at": time.time(),
        "platform": wanted_platform or None,
        "projects": {"total": len(jobs), "by_status": dict(project_counts)},
        "performance": {
            "overall": overall,
            "by_platform": by_platform,
            "top_variants": top_variants[:50],
            "feedback": feedback_payload,
        },
        "publishing": {
            "total": len(publishing),
            "by_platform": dict(publishing_by_platform),
            "recent": publishing[:50],
        },
        "models": list_models(),
        "style_profile": studio._load_style_profile(),
    }


@router.get("/api/analytics/dashboard")
def analytics_dashboard(platform: Optional[str] = Query(default=None, max_length=40)) -> Dict[str, Any]:
    return _dashboard_payload(platform)


@router.get("/api/publishing/dashboard")
def publishing_dashboard(platform: Optional[str] = Query(default=None, max_length=40)) -> Dict[str, Any]:
    return _dashboard_payload(platform)


@router.post("/api/analytics/import")
def import_analytics(request: AnalyticsImportRequest) -> Dict[str, Any]:
    studio = _studio()
    # Validate the complete target set before writing anything, so a malformed
    # export cannot leave half of an import applied.
    with studio._lock:
        targets = {item.job_id: studio._jobs.get(item.job_id) for item in request.records}
        missing = [job_id for job_id, job in targets.items() if job is None]
        if missing:
            raise HTTPException(404, {"error": f"job not found: {missing[0]}", "code": "job_not_found"})
        for item in request.records:
            job = targets[item.job_id]
            variants = studio._dict_items(job.get("variants")) if job else []
            if item.variant_id and not any(str(value.get("id")) == item.variant_id for value in variants):
                raise HTTPException(404, {"error": "variant not found", "code": "variant_not_found"})

        imported: List[Dict[str, Any]] = []
        for item in request.records:
            job = targets[item.job_id]
            payload = item.model_dump(exclude={"job_id"})
            payload["source"] = "import"
            record = make_record(payload)
            values = job.get("analytics")
            if not isinstance(values, list):
                values = []
                job["analytics"] = values
            values.append(record)
            if len(values) > 2000:
                del values[:-2000]
            studio._append_job_log(job, "analytics", f"Imported {record['platform']} analytics")
            studio._persist_job_locked(job)
            imported.append({"job_id": item.job_id, "record": record})
    return {"imported": len(imported), "records": imported, "dashboard": _dashboard_payload()}


@router.get("/api/style-profile")
def get_style_profile() -> Dict[str, Any]:
    return {"profile": _studio()._load_style_profile()}


@router.put("/api/style-profile")
def update_style_profile(request: StyleProfileUpdate) -> Dict[str, Any]:
    studio = _studio()
    current = studio._load_style_profile()
    values = request.model_dump(exclude_none=True)
    if "name" in values:
        current["name"] = values.pop("name")
    if "notes" in values:
        current["notes"] = values.pop("notes")
    preferences = current.get("preferences") if isinstance(current.get("preferences"), dict) else {}
    preferences.update(values)
    current["preferences"] = preferences
    current["updated_at"] = time.time()
    saved = studio._save_style_profile(current)
    return {"profile": saved}


@router.post("/api/style-profile/learn")
def learn_style_profile(request: StyleProfileLearnRequest) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        source = [studio._jobs[item] for item in request.job_ids if item in studio._jobs] if request.job_ids else list(studio._jobs.values())
        profile = learn_profile(source, name=request.name, include_unreviewed=request.include_unreviewed)
    return {"profile": studio._save_style_profile(profile)}


@router.delete("/api/style-profile")
def reset_style_profile() -> Dict[str, Any]:
    studio = _studio()
    return {"profile": studio._reset_style_profile()}


@router.get("/api/local/models")
def local_models() -> Dict[str, Any]:
    return {"models": list_models()}


@router.post("/api/local/models/{model_name}/download")
def download_local_model(model_name: str) -> Dict[str, Any]:
    try:
        return {"model": download_model(model_name)}
    except ValueError as exc:
        raise HTTPException(400, {"error": str(exc), "code": "validation_error"}) from exc


@router.delete("/api/local/models/{model_name}")
def delete_local_model(model_name: str, confirm: bool = Query(default=False)) -> Dict[str, Any]:
    if not confirm:
        raise HTTPException(400, {"error": "Set confirm=true to remove a cached model", "code": "confirmation_required"})
    try:
        return delete_model(model_name)
    except ValueError as exc:
        raise HTTPException(400, {"error": str(exc), "code": "validation_error"}) from exc
