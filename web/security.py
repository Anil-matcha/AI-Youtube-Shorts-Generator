"""Authentication, rate limiting, and secret-redaction helpers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse

def error_response(message: str, code: str, status_code: int, **extra: Any) -> JSONResponse:
    payload: Dict[str, Any] = {"error": str(message), "code": str(code)}
    payload.update(extra)
    return JSONResponse(status_code=status_code, content=payload)


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{8,}|mu_[A-Za-z0-9_-]{8,}|co_[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b(?:bearer|token|api[_ -]?key|secret)[=: ]+[A-Za-z0-9._~+/=-]{8,}"),
)


def _configured_secrets() -> Tuple[str, ...]:
    """Return runtime secrets that must never appear in API responses/logs."""
    values = []
    for name in ("SHORTS_API_TOKEN", "MUAPI_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OLLAMA_API_KEY"):
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
    # API tokens are compared using a constant-time SHA-256 digest; the token
    # itself is never persisted, which is the appropriate boundary for a
    # high-entropy bearer credential rather than a password.
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

    # This process-local limiter is intentionally bounded; multi-process
    # deployments should put a shared gateway limiter in front of the app.

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


class SQLiteRateLimiter:
    """SQLite-backed sliding-window limiter shared by workers on one host.

    SQLite gives a multi-process Uvicorn deployment one authoritative counter
    without introducing a mandatory Redis service. The database must live on
    a local/shared filesystem visible to every worker; deployments spanning
    multiple hosts should use an upstream gateway limiter instead.
    """

    def __init__(self, path: str | Path, limit: int = 600, window_seconds: float = 60.0) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rate_limit_hits "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, hit_at REAL NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_key_time ON rate_limit_hits(key, hit_at)")

    def allow(self, key: str, limit: Optional[int] = None) -> Tuple[bool, int]:
        maximum = max(1, int(limit or self.limit))
        now = time.time()
        cutoff = now - self.window_seconds
        try:
            with self._lock:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute("DELETE FROM rate_limit_hits WHERE hit_at <= ?", (cutoff,))
                    row = connection.execute(
                        "SELECT COUNT(*), MIN(hit_at) FROM rate_limit_hits WHERE key = ?",
                        (str(key),),
                    ).fetchone()
                    count = int(row[0] or 0) if row else 0
                    oldest = float(row[1]) if row and row[1] is not None else now
                    if count >= maximum:
                        retry_after = max(1, int(oldest + self.window_seconds - now))
                        connection.rollback()
                        return False, retry_after
                    connection.execute("INSERT INTO rate_limit_hits(key, hit_at) VALUES (?, ?)", (str(key), now))
                    connection.commit()
                    return True, 0
        except (OSError, sqlite3.Error):
            # A broken shared store must not silently disable abuse protection.
            return False, 1


def make_rate_limiter(limit: int, *, name: str = "general") -> SlidingWindowLimiter | SQLiteRateLimiter:
    """Build the configured limiter backend for a route group.

    ``SHORTS_RATE_LIMIT_BACKEND=sqlite`` enables a durable shared counter. The
    optional store path is shared by all route groups and workers; route names
    remain part of the key in the middleware.
    """

    backend = os.getenv("SHORTS_RATE_LIMIT_BACKEND", "memory").strip().lower()
    store = os.getenv("SHORTS_RATE_LIMIT_STORE", "").strip()
    if backend in {"sqlite", "shared", "file"} or store:
        if not store:
            data_root = os.getenv("SHORTS_STUDIO_DATA_DIR", "").strip() or "."
            store = str(Path(data_root).expanduser() / "rate_limits.sqlite3")
        return SQLiteRateLimiter(store, limit=limit)
    return SlidingWindowLimiter(limit)


def client_key(request: Request) -> str:
    trusted = os.getenv("SHORTS_TRUSTED_PROXIES", "").strip()
    remote = request.client.host if request.client else ""
    trusted_remote = False
    if trusted and remote:
        try:
            remote_ip = ipaddress.ip_address(remote)
            trusted_remote = any(remote_ip in ipaddress.ip_network(item.strip(), strict=False) for item in trusted.split(",") if item.strip())
        except ValueError:
            trusted_remote = False
    if trusted_remote:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        try:
            ipaddress.ip_address(forwarded)
        except ValueError:
            forwarded = ""
        if forwarded:
            return forwarded
    return remote or "local"


class LoginAttemptLimiter:
    """Bounded exponential lockout for invalid login attempts."""

    def __init__(self, limit: int = 5, window_seconds: float = 300.0) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(60.0, window_seconds)
        self._lock = threading.Lock()
        self._attempts: Dict[str, Deque[float]] = defaultdict(deque)

    def blocked(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) < self.limit:
                return 0
            exponent = min(6, len(bucket) - self.limit + 1)
            return max(1, min(900, 2**exponent))

    def failed(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            bucket.append(now)
            if len(self._attempts) > 2048:
                stale = [name for name, values in self._attempts.items() if not values or values[-1] <= cutoff]
                for name in stale:
                    self._attempts.pop(name, None)
        return self.blocked(key)

    def success(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


def sign_webhook_payload(payload: bytes | str, secret: str) -> str:
    """Create an interoperable HMAC-SHA256 webhook signature."""
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    return hmac.new(str(secret).encode("utf-8"), raw, hashlib.sha256).hexdigest()


def rate_limit_response(retry_after: int) -> JSONResponse:
    response = error_response("Too many requests; try again shortly.", "rate_limited", 429)
    response.headers["Retry-After"] = str(max(1, retry_after))
    return response
