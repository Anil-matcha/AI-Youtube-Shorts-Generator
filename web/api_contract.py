"""Versioning and error-contract helpers for the public HTTP API.

The original ``/api`` surface remains available for existing desktop clients,
but new clients should use ``/api/v1``.  A middleware alias keeps both surfaces
on the same handler implementation while the generated OpenAPI document lists
the versioned paths explicitly.
"""

from __future__ import annotations

import re
from typing import Any, Dict


API_VERSION = "v1"
LEGACY_SUNSET = "2027-09-15"

# Stable codes are intentionally small, human-readable identifiers.  The
# catalog is also exposed by the versioned API so generated clients can show a
# useful message without parsing prose.
ERROR_CATALOG: Dict[str, Dict[str, Any]] = {
    "validation_error": {"status": 422, "message": "Request validation failed"},
    "bad_request": {"status": 400, "message": "The request could not be processed"},
    "not_found": {"status": 404, "message": "The requested resource was not found"},
    "method_not_allowed": {"status": 405, "message": "The HTTP method is not supported for this resource"},
    "conflict": {"status": 409, "message": "The request conflicts with the current project state"},
    "unprocessable_entity": {"status": 422, "message": "The request contains invalid data"},
    "auth_required": {"status": 401, "message": "Authentication required"},
    "auth_invalid": {"status": 401, "message": "Invalid access token"},
    "auth_locked": {"status": 429, "message": "Too many failed login attempts; try again later"},
    "csrf_failed": {"status": 403, "message": "Cross-site mutation blocked"},
    "rate_limited": {"status": 429, "message": "Too many requests; try again shortly"},
    "request_too_large": {"status": 413, "message": "Request body is too large"},
    "invalid_content_length": {"status": 400, "message": "Content-Length is invalid"},
    "job_not_found": {"status": 404, "message": "Job not found"},
    "clip_not_found": {"status": 404, "message": "Clip not found"},
    "project_not_found": {"status": 404, "message": "Project not found"},
    "source_unavailable": {"status": 400, "message": "Source video is unavailable"},
    "media_unavailable": {"status": 400, "message": "Clip media is unavailable"},
    "unsupported_mode": {"status": 400, "message": "The selected mode is not supported"},
    "unsupported_platform": {"status": 400, "message": "The selected platform is not supported"},
    "credentials_required": {"status": 400, "message": "Provider credentials are required"},
    "oauth_not_configured": {"status": 400, "message": "OAuth is not configured"},
    "oauth_invalid": {"status": 400, "message": "OAuth authorization is invalid or expired"},
    "publish_approval_required": {"status": 409, "message": "Publishing requires explicit approval"},
    "factory_approval_required": {"status": 409, "message": "This factory clip requires a human approval checkpoint"},
    "factory_not_enabled": {"status": 409, "message": "The project was not created through the Shorts Factory"},
    "autopublish_disabled": {"status": 409, "message": "Automatic YouTube publishing is disabled"},
    "public_autopublish_disabled": {"status": 409, "message": "Public automatic publishing requires an explicit opt-in"},
    "quota_exceeded": {"status": 429, "message": "The YouTube API quota has been exceeded"},
    "publish_failed": {"status": 502, "message": "The platform rejected the publish request"},
    "dependency_failure": {"status": 502, "message": "An upstream service could not complete the request"},
    "insufficient_storage": {"status": 507, "message": "Not enough free storage is available"},
    "analytics_invalid": {"status": 422, "message": "Analytics data is invalid"},
    "variant_not_found": {"status": 404, "message": "Variant not found"},
    "migration_required": {"status": 409, "message": "Project data requires migration"},
    "backup_invalid": {"status": 400, "message": "Backup archive is invalid"},
    "internal_error": {"status": 500, "message": "Internal server error"},
}

_RULES = (
    (re.compile(r"\bjob not found\b", re.I), "job_not_found"),
    (re.compile(r"\bclip not found\b", re.I), "clip_not_found"),
    (re.compile(r"\b(project|deleted project) (?:not found|record is invalid)\b", re.I), "project_not_found"),
    (re.compile(r"source video is unavailable|source path .* does not exist", re.I), "source_unavailable"),
    (re.compile(r"clip media .* unavailable|clip is not a local file|file missing", re.I), "media_unavailable"),
    (re.compile(r"mode .* (?:api|local)|unsupported job mode", re.I), "unsupported_mode"),
    (re.compile(r"platform must be|only supports .*platform", re.I), "unsupported_platform"),
    (re.compile(r"(?:api key|credentials?).*(?:required|needs|configure|connect)", re.I), "credentials_required"),
    (re.compile(r"oauth.*(?:not configured|requires|missing)", re.I), "oauth_not_configured"),
    (re.compile(r"oauth.*(?:invalid|expired|state)", re.I), "oauth_invalid"),
    (re.compile(r"confirm=true|approval", re.I), "publish_approval_required"),
    (re.compile(r"factory.*(?:approval|not enabled)|approval.*factory", re.I), "factory_approval_required"),
    (re.compile(r"automatic.*(?:publishing|publish).*(?:disabled|opt.in)|autopublish", re.I), "autopublish_disabled"),
    (re.compile(r"quota(?:_| )exceed|dailylimit|ratelimit", re.I), "quota_exceeded"),
    (re.compile(r"analytics", re.I), "analytics_invalid"),
    (re.compile(r"variant not found", re.I), "variant_not_found"),
    (re.compile(r"backup", re.I), "backup_invalid"),
)

_STATUS_FALLBACKS = {
    400: "bad_request",
    401: "auth_required",
    403: "csrf_failed",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable_entity",
    413: "request_too_large",
    429: "rate_limited",
    502: "dependency_failure",
    507: "insufficient_storage",
    500: "internal_error",
}


def code_for_error(message: Any, status_code: int, *, fallback: str | None = None) -> str:
    """Return a stable code for a human detail string.

    Explicit codes always win.  The fallback preserves the legacy ``http_N``
    response contract for unversioned clients, while v1 handlers can request
    canonical codes for older route implementations as well.
    """

    text = str(message or "").strip()
    for pattern, code in _RULES:
        if pattern.search(text):
            return code
    if fallback:
        return str(fallback)
    return _STATUS_FALLBACKS.get(int(status_code), f"http_{int(status_code)}")


def is_versioned_path(path: str) -> bool:
    return path == "/api/v1" or path.startswith("/api/v1/")


def legacy_api_path(path: str) -> bool:
    return path.startswith("/api/") and not is_versioned_path(path)
