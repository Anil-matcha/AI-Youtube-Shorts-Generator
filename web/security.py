"""Authentication, rate limiting, and secret-redaction helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse


def error_response(message: str, code: str, status_code: int, **extra: Any) -> JSONResponse:
    payload: Dict[str, Any] = {"error": str(message), "code": str(code)}
    payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{8,}|mu_[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b(?:bearer|token|api[_ -]?key|secret)[=: ]+[A-Za-z0-9._~+/=-]{8,}"),
)


def _configured_secrets() -> Tuple[str, ...]:
    """Return runtime secrets that must never appear in API responses/logs."""
    values = []
    for name in ("SHORTS_API_TOKEN", "MUAPI_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        value = os.getenv(name, "").strip()
        if len(value) >= 4:
            values.append(value)
    return tuple(values)


def redact_text(value: Any, secrets: Optional[Dict[str, str]] = None, max_length: int = 4000) -> str:
    """Redact known provider formats and explicitly supplied session secrets."""
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    explicit = tuple(value for value in (secrets or {}).values() if isinstance(value, str))
    for secret in (*_configured_secrets(), *explicit):
        if isinstance(secret, str) and len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    return text[:max_length]


def redact_structure(value: Any, secrets: Optional[Dict[str, str]] = None) -> Any:
    """Recursively redact strings inside validation/error payloads."""
    if isinstance(value, dict):
        return {key: redact_structure(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_structure(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def configured_token() -> str:
    return os.getenv("SHORTS_API_TOKEN", "").strip()


def auth_enabled() -> bool:
    return bool(configured_token())


def _candidate_tokens(request: Request) -> Tuple[str, ...]:
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    return tuple(
        token
        for token in (
            bearer,
            request.headers.get("x-shorts-token", "").strip(),
            request.cookies.get("shorts_token", "").strip(),
        )
        if token
    )


def authorized(request: Request) -> bool:
    expected = configured_token()
    if not expected:
        return True
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return any(
        hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8")).digest(), expected_digest)
        for candidate in _candidate_tokens(request)
    )


class SlidingWindowLimiter:
    """Small process-local limiter; deployment docs recommend one worker."""

    def __init__(self, limit: int = 600, window_seconds: float = 60.0) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: Optional[int] = None) -> Tuple[bool, int]:
        now = time.monotonic()
        maximum = max(1, int(limit or self.limit))
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= maximum:
                retry_after = max(1, int(bucket[0] + self.window_seconds - now)) if bucket else 1
                return False, retry_after
            bucket.append(now)
            if len(self._hits) > 2048:
                stale = [name for name, values in self._hits.items() if not values or values[-1] <= cutoff]
                for name in stale:
                    self._hits.pop(name, None)
            return True, 0


def client_key(request: Request) -> str:
    trust_proxy = os.getenv("SHORTS_TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes", "on"}
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "local"


def rate_limit_response(retry_after: int) -> JSONResponse:
    response = error_response("Too many requests; try again shortly.", "rate_limited", 429)
    response.headers["Retry-After"] = str(max(1, retry_after))
    return response
