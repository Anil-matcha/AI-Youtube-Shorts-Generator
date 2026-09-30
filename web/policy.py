"""Deterministic publishing and story-safety preflight checks."""

from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, Iterable, List, Mapping
from urllib.parse import urlsplit

from web.security import redact_text


_RISK_TERMS = (
    "self-harm",
    "self harm",
    "suicide",
    "child sexual",
    "sexual minor",
    "graphic gore",
    "hate speech",
    "terrorist propaganda",
)
_RISK_PATTERN = re.compile("|".join(re.escape(item) for item in _RISK_TERMS), re.IGNORECASE)


def _number(value: object, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return converted if math.isfinite(converted) else default


def _text(value: object, limit: int = 5000) -> str:
    return redact_text(" ".join(str(value or "").replace("\x00", "").split()), max_length=limit)


def _check(code: str, status: str, message: str) -> Dict[str, str]:
    return {"code": code, "status": status, "message": message}


def _max_duration_seconds() -> float:
    try:
        value = float(os.getenv("SHORTS_POLICY_MAX_DURATION_SECONDS", "180"))
    except (TypeError, ValueError, OverflowError):
        value = 180.0
    return value if math.isfinite(value) and value > 0 else 180.0


def evaluate_publish_policy(
    payload: Mapping[str, Any],
    *,
    scheduled: bool = False,
    factory_approved: bool = True,
) -> Dict[str, Any]:
    """Return explainable pass/review/block results without calling a provider."""
    checks: List[Dict[str, str]] = []
    title = _text(payload.get("title"), 150)
    description = _text(payload.get("description"), 5000)
    combined_text = f"{title} {description} {_text(payload.get('hook_sentence'), 500)}"
    platform = _text(payload.get("platform"), 40).lower()
    privacy = _text(payload.get("privacy_status") or "private", 20).lower()
    auto_publish = bool(payload.get("auto_publish"))
    media_url = _text(payload.get("media_url"), 4096)
    start = _number(payload.get("start_time"), -1.0)
    end = _number(payload.get("end_time"), -1.0)
    duration = _number(payload.get("duration"), -1.0)
    if duration < 0 and start >= 0 and end >= start:
        duration = end - start

    if not title:
        checks.append(_check("title_missing", "review", "Add a clear title before publishing."))
    elif len(title) > 100:
        checks.append(_check("title_long", "review", "The title is longer than the recommended 100 characters."))
    else:
        checks.append(_check("title_present", "pass", "A publish title is present."))

    maximum = _max_duration_seconds()
    if duration > maximum + 0.01:
        checks.append(
            _check(
                "clip_too_long",
                "blocked",
                f"Clip duration {duration:.1f}s exceeds the configured {maximum:.0f}s Shorts limit.",
            )
        )
    elif duration > 0:
        checks.append(_check("clip_duration", "pass", f"Clip duration is within the {maximum:.0f}s limit."))
    else:
        checks.append(_check("clip_duration_unknown", "review", "Clip duration is unavailable; review the media manually."))

    if media_url:
        parsed = urlsplit(media_url)
        if parsed.scheme.casefold() != "https" or not parsed.netloc:
            checks.append(_check("media_url_not_https", "blocked", "External media URLs must use HTTPS."))
        else:
            checks.append(_check("media_url_https", "pass", "External media URL uses HTTPS."))

    if scheduled or payload.get("publish_at"):
        if privacy != "private":
            checks.append(_check("schedule_not_private", "blocked", "Scheduled entries must remain private until explicit confirmation."))
        else:
            checks.append(_check("schedule_private", "pass", "Scheduled entry remains private."))
        if not payload.get("publish_at"):
            checks.append(_check("schedule_time_missing", "blocked", "A scheduled entry needs a future publish time."))

    if auto_publish and not factory_approved:
        checks.append(_check("factory_approval_missing", "blocked", "Automatic publishing requires an approved review checkpoint."))
    elif not factory_approved:
        checks.append(_check("factory_review", "review", "A human should approve this factory clip before publishing."))

    risk_matches = sorted({match.group(0).casefold() for match in _RISK_PATTERN.finditer(combined_text)})
    if risk_matches:
        checks.append(
            _check(
                "sensitive_language",
                "review",
                "Potentially sensitive language was detected; complete a human policy review before distribution.",
            )
        )
    else:
        checks.append(_check("sensitive_language", "pass", "No configured sensitive-language signal was detected."))

    if platform not in {"youtube_shorts", "tiktok", "instagram_reels"}:
        checks.append(_check("platform_unknown", "blocked", "The platform is not supported by the policy catalog."))

    blockers = [item for item in checks if item["status"] == "blocked"]
    reviews = [item for item in checks if item["status"] == "review"]
    status = "blocked" if blockers else "review" if reviews else "pass"
    return {
        "policy_version": "v2.0-foundation",
        "status": status,
        "can_publish": not blockers and (not auto_publish or not reviews),
        "requires_human_review": bool(reviews or auto_publish),
        "scheduled": bool(scheduled or payload.get("publish_at")),
        "platform": platform,
        "risk_signals": risk_matches,
        "checks": checks,
    }


def policy_summary(results: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    """Aggregate policy states for dashboards and scheduler telemetry."""
    summary = {"pass": 0, "review": 0, "blocked": 0}
    for item in results:
        status = str(item.get("status") or "review")
        if status not in summary:
            status = "review"
        summary[status] += 1
    return summary
