"""Local analytics ledger and deterministic performance feedback."""

from __future__ import annotations

import math
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional


COUNTERS = ("impressions", "views", "likes", "comments", "shares", "saves")
FLOATS = ("watch_time_seconds", "average_watch_time_seconds", "completion_rate")


def make_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a validated analytics payload for durable storage."""
    record: Dict[str, Any] = {
        "id": str(payload.get("id") or "a_" + os_random_token()),
        "platform": str(payload.get("platform") or "").strip().lower(),
        "variant_id": str(payload.get("variant_id") or "") or None,
        "source": str(payload.get("source") or "manual").strip().lower(),
        "recorded_at": str(payload.get("recorded_at") or "") or None,
        "created_at": float(payload.get("created_at") or time.time()),
        "notes": str(payload.get("notes") or "")[:1000] or None,
    }
    for name in COUNTERS:
        try:
            value = int(payload.get(name) or 0)
        except (TypeError, ValueError, OverflowError):
            value = 0
        record[name] = max(0, value)
    for name in FLOATS:
        try:
            value = float(payload.get(name) or 0.0)
        except (TypeError, ValueError, OverflowError):
            value = 0.0
        record[name] = value if math.isfinite(value) and value >= 0 else 0.0
    record["completion_rate"] = min(1.0, record["completion_rate"])
    return record


def os_random_token() -> str:
    # UUID is deliberately imported lazily so analytics remains a tiny module
    # for packaged startup and deterministic tests.
    import uuid

    return uuid.uuid4().hex[:16]


def _records(records: Iterable[Dict[str, Any]], platform: Optional[str] = None, variant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    wanted_platform = str(platform or "").strip().lower()
    wanted_variant = str(variant_id or "").strip()
    out = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if wanted_platform and str(record.get("platform") or "").lower() != wanted_platform:
            continue
        if wanted_variant and str(record.get("variant_id") or "") != wanted_variant:
            continue
        out.append(record)
    return out


def aggregate(records: Iterable[Dict[str, Any]], *, platform: Optional[str] = None, variant_id: Optional[str] = None) -> Dict[str, Any]:
    selected = _records(records, platform=platform, variant_id=variant_id)
    totals: Dict[str, Any] = {name: 0 for name in COUNTERS}
    totals.update({name: 0.0 for name in FLOATS})
    average_watch_sum = 0.0
    average_watch_weight = 0
    average_watch_unweighted_sum = 0.0
    average_watch_count = 0
    for record in selected:
        for name in COUNTERS:
            try:
                totals[name] += max(0, int(record.get(name) or 0))
            except (TypeError, ValueError, OverflowError):
                continue
        for name in ("watch_time_seconds", "average_watch_time_seconds"):
            try:
                value = float(record.get(name) or 0.0)
            except (TypeError, ValueError, OverflowError):
                value = 0.0
            if math.isfinite(value) and value >= 0:
                if name == "average_watch_time_seconds":
                    try:
                        weight = max(0, int(record.get("views") or 0))
                    except (TypeError, ValueError, OverflowError):
                        weight = 0
                    if weight:
                        average_watch_sum += value * weight
                        average_watch_weight += weight
                    else:
                        average_watch_unweighted_sum += value
                        average_watch_count += 1
                else:
                    totals[name] += value
    views = int(totals["views"])
    impressions = int(totals["impressions"])
    engagement_count = int(totals["likes"] + totals["comments"] + totals["shares"] + totals["saves"])
    completion_weight = 0.0
    completion_views = 0
    for record in selected:
        try:
            completion = min(1.0, max(0.0, float(record.get("completion_rate") or 0.0)))
            record_views = max(0, int(record.get("views") or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        completion_weight += completion * record_views
        completion_views += record_views
    totals["completion_rate"] = completion_weight / completion_views if completion_views else 0.0
    totals["engagement_rate"] = engagement_count / views if views else 0.0
    totals["view_rate"] = min(1.0, views / impressions) if impressions else 0.0
    if average_watch_weight:
        totals["average_watch_time_seconds"] = average_watch_sum / average_watch_weight
    elif average_watch_count:
        totals["average_watch_time_seconds"] = average_watch_unweighted_sum / average_watch_count
    totals["records"] = len(selected)
    totals["last_recorded_at"] = max((str(item.get("recorded_at") or "") for item in selected), default=None)
    return totals


def feedback(records: Iterable[Dict[str, Any]], variants: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Compare variants and return actionable, explainable recommendations."""
    records_list = [item for item in records if isinstance(item, dict)]
    variant_list = [item for item in variants if isinstance(item, dict)]
    by_variant: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records_list:
        key = str(record.get("variant_id") or "baseline")
        by_variant[key].append(record)
    comparisons: List[Dict[str, Any]] = []
    for key, grouped in by_variant.items():
        summary = aggregate(grouped, variant_id=None)
        score = min(1.0, (summary["completion_rate"] * 0.55) + (summary["engagement_rate"] * 0.45))
        comparisons.append({"variant_id": key, "score": round(score, 6), **summary})
    comparisons.sort(key=lambda item: (float(item.get("score") or 0), int(item.get("views") or 0)), reverse=True)
    overall = aggregate(records_list)
    recommendations: List[Dict[str, str]] = []
    if overall["records"] == 0:
        recommendations.append({"code": "collect_baseline", "message": "Record platform metrics before changing a variant."})
    elif overall["completion_rate"] < 0.35:
        recommendations.append({"code": "strengthen_hook", "message": "Completion is below 35%; test a shorter, clearer opening hook."})
    elif overall["engagement_rate"] < 0.02:
        recommendations.append({"code": "add_call_to_action", "message": "Engagement is below 2%; test a clearer question or call to action."})
    else:
        recommendations.append({"code": "keep_structure", "message": "Retention and engagement are healthy; preserve the winning structure."})
    if len(comparisons) > 1:
        winner = comparisons[0]
        recommendations.append({"code": "promote_winner", "message": f"Variant {winner['variant_id']} currently leads on retention and engagement."})
    return {
        "overall": overall,
        "variants": comparisons,
        "recommendations": recommendations,
        "variant_count": len(variant_list),
    }
