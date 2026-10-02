"""Authentication, rate limiting, and secret-redaction helpers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

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

# Query-parameter names that carry a credential.  Matching is on the *whole*
# name (casefolded, with ``-``/``_``/``.`` removed) plus the unambiguous provider
# signing namespaces, never on a substring: a substring rule also treats
# functional parameters such as ``key``, ``author``, ``design``, ``si`` or
# ``size`` as secrets, which silently rewrites a source URL the downloader
# still needs.  Matching is shared by URL and free-text scrubbing so a new
# provider parameter cannot be covered on one path and missed on another.
_SECRET_QUERY_NAMES = frozenset(
    (
        "token", "accesstoken", "refreshtoken", "idtoken", "authtoken", "bearertoken", "securitytoken",
        "sessiontoken", "sessionid", "session", "secret", "clientsecret", "apisecret", "secretkey",
        "secretaccesskey", "password", "passwd", "pwd", "apikey", "accesskeyid", "awsaccesskeyid",
        "googleaccessid", "signature", "sig", "signedheaders", "credential", "credentials", "credentialid",
        "jwt", "assertion", "authorization", "auth", "expires", "expiry", "expire",
    )
)
_SECRET_QUERY_PREFIXES = ("xamz", "xgoog")

# One parameter matcher shared by URL and free-text scrubbing.  ``#`` is included
# because implicit-flow tokens arrive in the fragment, not the query.
_QUERY_PARAMETER_PATTERN = re.compile(r"(?i)([?&#])([\w.\-]+)=([^&\s'\"<>]*)")


def _query_key_is_secret(name: str) -> bool:
    """True only for whole credential parameter names, never for substrings."""
    folded = re.sub(r"[-_.]", "", str(name).casefold())
    return folded in _SECRET_QUERY_NAMES or folded.startswith(_SECRET_QUERY_PREFIXES)


# RFC 3986 allows credentials in the authority, which is how a self-hosted
# media server or a signed direct-download link carries basic auth.  A bare
# username is not a credential, and removing it would rewrite a URL that still
# has to be fetched, so only ``user:password@`` is dropped.
_USERINFO_PATTERN = re.compile(r"(?i)\b([A-Za-z][A-Za-z0-9+.\-]*://)([^/?#\s@]*:[^/?#\s@]*)@")


def _scrub_userinfo(netloc: str) -> str:
    """Drop ``user:password@`` credentials from a URL authority."""
    if "@" not in netloc:
        return netloc
    userinfo, host = netloc.rsplit("@", 1)
    return host if ":" in userinfo else netloc


def _redact_userinfo(text: str) -> str:
    """Replace ``scheme://user:password@`` inside free text with a marker.

    A log line or an upstream error quotes the address it failed on, so the
    authority credential is scrubbed in prose as well as in a whole URL.
    """

    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}[redacted]@"

    return _USERINFO_PATTERN.sub(replace, text)


def _scrub_parameters(component: str) -> str:
    """Drop credential parameters from a query or fragment, keeping the rest."""
    if not component or "=" not in component:
        return component
    kept = [
        (name, item)
        for name, item in parse_qsl(component, keep_blank_values=True)
        if not _query_key_is_secret(name)
    ]
    return urlencode(kept)


# Some providers sign the *path* instead of the query, putting the credential
# where the public video id normally sits: Cloudflare Stream serves
# ``customer-<code>.cloudflarestream.com/<TOKEN>/manifest/video.m3u8``,
# ``/<TOKEN>/iframe`` and ``/<TOKEN>/downloads/default.mp4``.  That token is a
# JWS compact serialization -- three base64url segments whose header decodes to
# a JSON object, hence the ``eyJ`` prefix -- which is a structural signature
# rather than an entropy guess: a functional segment (a video id, a ``manifest``
# route, a filename) never has that shape, so an unrecognised host keeps its
# path byte-for-byte.  The downloader is never handed the scrubbed form; only
# the durable copy loses the token, and that record is flagged so resume and
# retry refuse it rather than fetching a mangled address.
_JWT_SEGMENT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{16,}")


def _scrub_path(path: str) -> str:
    """Drop credential-shaped path segments, keeping the rest of the path."""
    if "." not in path:
        return path
    segments = path.split("/")
    kept = [segment for segment in segments if not _JWT_SEGMENT_PATTERN.fullmatch(segment)]
    if len(kept) == len(segments):
        return path
    return "/".join(kept)


def redact_url_query(value: str) -> str:
    """Strip credentials from a URL's query, fragment *and* signed path.

    Long signed-URL parameters (S3, Azure, GCS, OAuth) routinely outlive the
    request that produced them, implicit-flow tokens live in the fragment, and
    path-signing providers carry the token in place of the video id, so anything
    surviving in a persisted job record, a backup, or an API error message must
    not carry those values.  Non-credential parameters and path segments -- and
    a URL with no credentials at all -- are returned byte-for-byte unchanged so
    a legitimate source URL keeps working.
    """
    text = str(value or "")
    try:
        parts = urlsplit(text)
    except (TypeError, ValueError):
        return ""
    path = _scrub_path(parts.path)
    query = _scrub_parameters(parts.query)
    fragment = _scrub_parameters(parts.fragment)
    netloc = _scrub_userinfo(parts.netloc)
    if path == parts.path and query == parts.query and fragment == parts.fragment and netloc == parts.netloc:
        return text
    return urlunsplit((parts.scheme, netloc, path, query, fragment))


# A durable record can hold a URL in any field, and neither a field added later
# nor a newly supported provider shape may leak by omission, so the durable
# write scrubs every value that *is* an absolute URL instead of a hand-picked
# set of keys.  Values that are prose (a log line, a caption, a transcript) are
# left alone: only a whole-string URL can be handed to the URL policy without
# rewriting the text around it.
_ABSOLUTE_URL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://\S+\Z")


def _redact_record_urls_in(value: Any) -> Any:
    """Return one node of a record with credential-bearing URLs stripped."""
    if isinstance(value, str):
        if "://" not in value or not _ABSOLUTE_URL_PATTERN.match(value):
            return value
        return redact_url_query(value)
    if isinstance(value, dict):
        for name, item in list(value.items()):
            value[name] = _redact_record_urls_in(item)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _redact_record_urls_in(item)
        return value
    if isinstance(value, tuple):
        return tuple(_redact_record_urls_in(item) for item in value)
    return value


def redact_record_urls(record: Any) -> None:
    """Scrub credential-bearing URLs anywhere inside a record, in place.

    The durable write path calls this, so a record cannot reach the SQLite
    store, the JSON mirror or a portable manifest with a credential in a field
    the policy owner was never told about.  Only a value that *is* an absolute
    URL reaches the URL policy, so prose and functional URLs are left
    byte-for-byte unchanged.
    """
    _redact_record_urls_in(record)


def _redact_record_secrets_in(value: Any, values: Tuple[str, ...]) -> Any:
    """Return one node of a record with known credential values replaced."""
    if isinstance(value, str):
        return _replace_secret_values(value, values) if values else value
    if isinstance(value, dict):
        for name, item in list(value.items()):
            value[name] = _redact_record_secrets_in(item, values)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _redact_record_secrets_in(item, values)
        return value
    if isinstance(value, tuple):
        return tuple(_redact_record_secrets_in(item, values) for item in value)
    return value


# A record is not a log line.  The text policy masks any configured value from
# four characters up, because a log line is disposable, but the durable record
# holds the creator's own words -- the transcript, the captions, the clip
# titles.  Rewriting those because an operator configured a short, ordinary
# secret would silently corrupt the work itself, so the record owner only
# rewrites a value long enough to actually be a credential.
_RECORD_SECRET_MIN_LENGTH = 12


def redact_record_secrets(record: Any, secrets: Optional[Dict[str, str]] = None) -> None:
    """Replace known credential values anywhere inside a record, in place.

    The URL policy above only recognises a value that *is* an absolute URL.  A
    credential the app itself holds also arrives as prose: a dependency that
    narrates or echoes back the request it just rejected, or a provider payload
    that lands in a result field.  The durable write path is the single owner of
    what a record may contain, so it scrubs those values as well and no field
    added later can leak by omission.  Only a credential-shaped value the policy
    already knows is replaced, so functional and creator-authored text is left
    byte-for-byte unchanged.
    """
    values = tuple(value for value in _secret_values(secrets) if len(value) >= _RECORD_SECRET_MIN_LENGTH)
    if not values:
        return
    _redact_record_secrets_in(record, values)


def _redact_query_parameters(text: str) -> str:
    """Replace credential parameter values found anywhere in a string."""

    def replace(match: re.Match[str]) -> str:
        if not _query_key_is_secret(match.group(2)):
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}=[redacted]"

    return _QUERY_PARAMETER_PATTERN.sub(replace, text)


def _configured_secrets() -> Tuple[str, ...]:
    """Return runtime secrets that must never appear in API responses/logs."""
    values = []
    for name in ("SHORTS_API_TOKEN", "MUAPI_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OLLAMA_API_KEY"):
        value = os.getenv(name, "").strip()
        if len(value) >= 4:
            values.append(value)
    return tuple(values)


def _secret_values(secrets: Optional[Dict[str, str]] = None) -> Tuple[str, ...]:
    """Return every credential value the policy knows about.

    The configured environment values are always in scope, because a provider
    error can echo whichever one the process is actually using; the caller's
    map adds the session credentials that were never written to disk.
    """
    explicit = tuple(value for value in (secrets or {}).values() if isinstance(value, str))
    return tuple(
        secret for secret in (*_configured_secrets(), *explicit) if isinstance(secret, str) and len(secret) >= 4
    )


def _replace_secret_values(text: str, values: Tuple[str, ...]) -> str:
    for secret in values:
        text = text.replace(secret, "[redacted]")
    return text


def redact_secret_values(text: str, secrets: Optional[Dict[str, str]] = None) -> str:
    """Replace every known credential value found anywhere in ``text``."""
    return _replace_secret_values(text, _secret_values(secrets))


def redact_text(value: Any, secrets: Optional[Dict[str, str]] = None, max_length: int = 4000) -> str:
    """Redact known provider formats and explicitly supplied session secrets."""
    text = str(value or "")
    if "://" in text:
        text = redact_url_query(text)
    text = _redact_query_parameters(text)
    text = _redact_userinfo(text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = _replace_secret_values(text, _secret_values(secrets))
    return text[:max_length]


def redact_structure(value: Any, secrets: Optional[Dict[str, str]] = None) -> Any:
    """Recursively redact strings inside validation/error payloads."""
    if isinstance(value, dict):
        return {key: redact_structure(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_structure(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, float) and not math.isfinite(value):
        # Validation details may echo an invalid Infinity/NaN input. Preserve
        # its description without letting strict JSON encoding fail with 500.
        return str(value)
    return value


def configured_token() -> str:
    return os.getenv("SHORTS_API_TOKEN", "").strip()


def auth_enabled() -> bool:
    return bool(configured_token())


# ---------------------------------------------------------------------------
# Session cookie: the configured API token is a high-entropy credential and is
# accepted as a bearer header, but it is never stored in the browser.  The
# login route exchanges it for a random stateless session value whose digest
# is bound to the active SHORTS_API_TOKEN, so a cookie copied from browser
# storage cannot be replayed as the bearer token and a rotated
# SHORTS_API_TOKEN invalidates every issued session immediately.
# ---------------------------------------------------------------------------

_SESSION_SERVER_KEY_SALT = b"shorts-studio-session-v1"
_SESSION_COOKIE_TTL_SECONDS = 86400


def _session_binding(configured: str, csrf_value: str, cookie_value: str) -> str:
    """Digest tying a (CSRF, session-cookie) pair to the configured token."""
    material = _SESSION_SERVER_KEY_SALT + configured.encode("utf-8") + csrf_value.encode("utf-8") + b":" + cookie_value.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def issue_session_token() -> Tuple[str, str, int]:
    """Return ``(cookie_value, csrf_token, max_age)`` for a fresh session.

    The CSRF cookie carries ``<csrf_value>:<binding>`` where the binding is a
    digest of the CSRF value together with the session cookie value and the
    token configured at login time.  The middleware double-submit check
    compares the ``X-CSRF-Token`` header against this cookie, and
    :func:`verify_session_token` re-derives the same binding from the two
    presented cookies, so a pair from a different token era is rejected and
    neither cookie alone authenticates anything.
    """
    configured = configured_token()
    cookie_value = secrets.token_urlsafe(32)
    csrf_value = secrets.token_urlsafe(24)
    binding = _session_binding(configured, csrf_value, cookie_value)
    return cookie_value, f"{csrf_value}:{binding}", _SESSION_COOKIE_TTL_SECONDS


def verify_session_token(cookie_value: str, csrf_token: Optional[str] = None) -> bool:
    """Validate a session cookie against the currently configured token.

    The digest is computed with the active ``SHORTS_API_TOKEN`` so rotating or
    clearing that variable revokes every previously issued session at once.
    When a CSRF token is supplied it must match the binding recorded at login
    (double-submit cookie pattern, constant-time comparison).
    """
    configured = configured_token()
    if not configured or not cookie_value or not cookie_value.strip():
        return False
    if csrf_token is None:
        return False
    csrf_value, separator, binding = str(csrf_token).partition(":")
    if separator != ":" or not csrf_value or not binding:
        return False
    expected = _session_binding(configured, csrf_value, cookie_value)
    return hmac.compare_digest(binding, expected)


def session_cookie_secure(request: Optional[Request] = None) -> bool:
    """Decide the ``Secure`` cookie attribute for a new session.

    Order of authority:
    1. ``SHORTS_COOKIE_SECURE`` explicit override.
    2. The request is https, or a fronting proxy reports https through
       ``X-Forwarded-Proto``.
    3. Otherwise no ``Secure`` attribute.

    The attribute follows the scheme the browser actually used, never the bind
    host.  A container published over plain http on a LAN address (the default
    ``docker-compose`` shape) is a legitimate deployment, and a ``Secure``
    cookie makes browsers silently discard it: the login call returns 200 and
    every later request stays unauthenticated.  Deployments that terminate TLS
    in front of the app report https through ``X-Forwarded-Proto`` and keep a
    Secure cookie; honouring that header can only add the attribute, never
    remove it, so it needs no trusted-proxy gate.
    """
    override = os.getenv("SHORTS_COOKIE_SECURE", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    if request is None:
        return False
    if request.url.scheme == "https":
        return True
    forwarded = str(request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return forwarded == "https"


def host_is_loopback(host: str) -> bool:
    """Return True only for unambiguous loopback bind addresses."""
    cleaned = str(host or "").strip().strip("[]")
    if not cleaned:
        return False
    try:
        return ipaddress.ip_address(cleaned).is_loopback
    except ValueError:
        return False


def is_safe_open_url(url: str, *, allowed_schemes: Tuple[str, ...] = ("https",)) -> bool:
    """Validate a server-provided URL before a browser is asked to open it.

    Release notes and OAuth authorization URLs originate from upstream
    responses.  Before handing one to ``window.open`` or a redirect, confirm
    it is an absolute http(s) URL without embedded newlines or credential
    components, so a compromised or hostile upstream cannot pivot the
    browser onto ``file:``, ``javascript:``, or intranet schemes.
    """
    value = str(url or "").strip()
    if not value or any(character in value for character in "\r\n\t") or "\\" in value:
        return False
    if any(character in value for character in "\x00\x1f") or any(ord(character) < 32 for character in value):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme.lower() not in allowed_schemes or not parsed.netloc:
        return False
    if "@" in parsed.netloc:
        return False
    return True


def configured_bind_host() -> str:
    """Return the address this server is configured to listen on."""
    return os.getenv("SHORTS_BIND_HOST", "127.0.0.1").strip().lower()


def binds_to_loopback() -> bool:
    """True when the configured bind is the one-click loopback desktop build.

    That build intentionally runs without a token, so it must also refuse the
    browser-driven request shapes a hostile page can produce; a deployment bound
    to a network address is authenticated instead and keeps its endpoints.
    """
    host = configured_bind_host().strip().strip("[]")
    return host in {"", "localhost"} or host_is_loopback(host)


def unauthenticated_loopback_build() -> bool:
    """True only for the configuration with no other boundary at all.

    The desktop build binds loopback and ships without a token, so a rebound
    name is same-origin, cookie-less, and unauthenticated at the same time; the
    ``Host`` rule below is the only thing left.  Once a token is configured,
    every non-public route requires it and the session cookie is host-scoped, so
    a rebound page gains nothing and the name in ``Host`` stops being a
    boundary -- which matters because the documented way to put TLS or a proxy
    in front of the app is to forward to a loopback bind under the public name.
    """
    return binds_to_loopback() and not auth_enabled()


def _request_host_name(request: Request) -> str:
    """Return the ``Host`` header's hostname without its port."""
    host = str(request.headers.get("host") or "").strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        closing = host.find("]")
        name = host[1:closing] if closing != -1 else host[1:]
    elif host.count(":") == 1:
        name = host.rsplit(":", 1)[0]
    else:
        name = host
    return name.rstrip(".").strip("[]")


def is_allowed_request_host(request: Request) -> bool:
    """Refuse a foreign ``Host`` when this server is loopback-bound.

    A page on an attacker-controlled name that resolves to 127.0.0.1 makes the
    browser treat the app as same-origin (DNS rebinding), which defeats the
    same-origin rule below and ``SameSite`` cookies, and lets the page read
    project data.  A loopback-bound server only ever answers a loopback name for
    a real client, so any other name is refused; a deployment bound to a network
    address is unchanged because its clients legitimately use another name.

    Only :func:`unauthenticated_loopback_build` is constrained: an
    authenticated deployment may legitimately be reached under another name, and
    its token plus host-scoped cookies already cover what this rule covers here.

    ``X-Forwarded-Host`` is deliberately not consulted: a browser cannot set it
    without a preflight, and the proxy that legitimately sets it reaches the app
    behind its own authentication.
    """
    if not unauthenticated_loopback_build():
        return True
    name = _request_host_name(request)
    if not name:
        return True
    return name == "localhost" or host_is_loopback(name)


def is_safe_request_origin(request: Request) -> bool:
    """Decide whether a mutation may proceed when session-cookie authenticated.

    SameSite=Strict already blocks cookies on most cross-site posts; this
    second check covers proxies and older browsers.  A missing or ``null``
    Origin with a cookie present is refused because such requests cannot be
    distinguished from a sandboxed cross-site attack.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return False
    if str(origin).strip().casefold() in {"null", "\"null\""}:
        return False
    parsed = urlparse(origin)
    return bool(parsed.netloc) and parsed.netloc == request.url.netloc


def _candidate_tokens(request: Request) -> Tuple[str, ...]:
    """Collect credential candidates for bearer authentication.

    Only header-based credentials are accepted here.  The session cookie is
    validated separately by :func:`session_cookie_valid` so the raw configured
    token never has to live in browser storage.
    """
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    return tuple(
        token
        for token in (
            bearer,
            request.headers.get("x-shorts-token", "").strip(),
        )
        if token
    )


def session_cookie_valid(request: Request) -> bool:
    """True when the request carries a live session cookie (CSRF-aware)."""
    return verify_session_token(
        request.cookies.get("shorts_token", ""),
        request.cookies.get("shorts_csrf"),
    )


def header_credential_valid(request: Request) -> bool:
    """True only when the request presents the configured token in a header.

    Distinct from :func:`bearer_authorized`, which treats a server with no token
    configured as authorized: here an unconfigured server has nothing to
    present, so no request is exempt.  Used to keep non-browser API clients out
    of the browser-focused same-origin rule, because a page cannot read the
    token and therefore cannot forge such a request.
    """
    expected = configured_token()
    if not expected:
        return False
    candidates = _candidate_tokens(request)
    if not candidates:
        return False
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return any(
        hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8")).digest(), expected_digest)
        for candidate in candidates
    )


def bearer_authorized(request: Request) -> bool:
    """True when a header credential matches the configured token.

    A malformed credential fails closed: when auth is configured but the
    request carries no header credential at all, this returns False so the
    caller can fall back to session-cookie validation rather than granting
    bearer privileges to credential-less requests.
    """
    expected = configured_token()
    if not expected:
        return True
    candidates = _candidate_tokens(request)
    if not candidates:
        return False
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return any(
        hmac.compare_digest(hashlib.sha256(candidate.encode("utf-8")).digest(), expected_digest)
        for candidate in candidates
    )


def authorized(request: Request) -> bool:
    # Header credentials are compared using a constant-time SHA-256 digest; the
    # token itself is never persisted, which is the appropriate boundary for a
    # high-entropy bearer credential rather than a password.  Session cookies
    # are validated through their own digest chain and additionally require a
    # safe same-origin context for mutations (checked in the middleware).
    if not configured_token():
        return True
    if bearer_authorized(request):
        return True
    return session_cookie_valid(request)


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

    def remaining(self, key: str, limit: Optional[int] = None) -> int:
        """Hits the caller may still make in the current window (read-only)."""
        now = time.monotonic()
        maximum = max(1, int(limit or self.limit))
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return maximum
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            return max(0, maximum - len(bucket))


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

    def remaining(self, key: str, limit: Optional[int] = None) -> int:
        """Hits the caller may still make in the current window (read-only)."""
        maximum = max(1, int(limit or self.limit))
        now = time.time()
        cutoff = now - self.window_seconds
        try:
            with self._lock:
                with self._connect() as connection:
                    row = connection.execute(
                        "SELECT COUNT(*) FROM rate_limit_hits WHERE key = ? AND hit_at > ?",
                        (str(key), cutoff),
                    ).fetchone()
                    count = int(row[0] or 0) if row else 0
                    return max(0, maximum - count)
        except (OSError, sqlite3.Error):
            # Fail closed: a broken shared store must not expand the budget.
            return 0


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


# ---------------------------------------------------------------------------
# Render (job) rate-limit budget
#
# One owner for the policy: which requests spend the render budget and how they
# are keyed.  Batch accounting deliberately spends the canonical per-render
# bucket, so a batch of N consumes N single-job slots, while the middleware
# charges one slot per submission route.  Every bucket is a route *shape*
# (:func:`rate_limit_shape`) rather than a concrete URL, because a key that
# carries a project id hands every project its own quota and lets one minute of
# limit be multiplied by however many projects exist.  Keeping the
# classification and the key construction together means a change lands in
# exactly one place.
# ---------------------------------------------------------------------------

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Canonical bucket for one render submission; batch and retry accounting spend
#: the same slots a plain job create would.
JOB_SUBMISSION_PATH = "/api/jobs"

#: Routes the middleware charges one submission slot for.
_JOB_SUBMISSION_PATHS = frozenset({JOB_SUBMISSION_PATH, "/api/factory/jobs"})
#: ``/api/jobs/batch`` spends one slot per URL inside its handler, which is the
#: only place that knows how many URLs a request carries, so the middleware must
#: not charge the canonical bucket for it as well.
_JOB_SELF_ACCOUNTED_PATHS = frozenset({"/api/jobs/batch"})
_JOB_BUDGET_PATH_PREFIX = f"{JOB_SUBMISSION_PATH}/"
_JOB_BUCKET_PROJECT = "{job_id}"
_JOB_BUCKET_INDEX = "{index}"
#: The per-project action that starts a render rather than editing one.
_JOB_RENDER_ACTION = "/retry"


def _job_bucket_action(action: str) -> str:
    """Replace the per-project identifiers in an action path with placeholders."""
    return "/".join(_JOB_BUCKET_INDEX if segment.isdigit() else segment for segment in action.split("/"))


def rate_limit_shape(path: str) -> str:
    """Return the limiter bucket for a path: its route shape, never its ids.

    Two projects hitting one route are the same action on different records, so
    they share one quota.  Keying on the concrete URL instead gave every project
    - and every clip index - a private one, so work that is expensive per
    request scaled with how many of them existed: a retry started as many
    renders as there were failed projects, and the ffmpeg behind the waveform
    and clip routes did the same.  Paths with no per-project id are their own
    shape.
    """
    if not path.startswith(_JOB_BUDGET_PATH_PREFIX):
        return path
    _project, separator, action = path[len(_JOB_BUDGET_PATH_PREFIX) :].partition("/")
    if not separator or not action:
        # ``/api/jobs/<project>``: one project record, with no second id to
        # fold away beyond the one the placeholder replaces.
        return f"{_JOB_BUDGET_PATH_PREFIX}{_JOB_BUCKET_PROJECT}"
    return f"{_JOB_BUDGET_PATH_PREFIX}{_JOB_BUCKET_PROJECT}/{_job_bucket_action(action)}"


def job_budget_bucket(method: str, path: str) -> Optional[str]:
    """Return the canonical render-budget bucket for a request, or ``None``.

    Only mutations spend the budget; the reads under these paths are the
    progress poll, the SSE stream and the project list, so charging them would
    throttle ordinary browsing against the much smaller job limit.  The routes
    handled here are the ones the routers actually register, so a wildcard rule
    can no longer describe a route that does not exist.  A retry starts a
    render, so it spends the shared submission slot instead of a private one.
    """
    if str(method).upper() not in MUTATING_METHODS:
        return None
    if path in _JOB_SUBMISSION_PATHS:
        return JOB_SUBMISSION_PATH
    if path in _JOB_SELF_ACCOUNTED_PATHS:
        return path
    if not path.startswith(_JOB_BUDGET_PATH_PREFIX):
        return None
    shape = rate_limit_shape(path)
    return JOB_SUBMISSION_PATH if shape.endswith(_JOB_RENDER_ACTION) else shape


def rate_limit_key(client: str, path: str) -> str:
    """Build a limiter bucket key; the only place keys are constructed."""
    return f"{client}:{path}"


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
