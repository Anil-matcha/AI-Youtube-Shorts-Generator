"""Thin MuAPI client: submit a job, poll until it finishes, return the result."""

import time
import math
import re
from typing import Any, Dict, Optional

import requests

from .config import (
    MUAPI_BASE_URL,
    POLL_INTERVAL_SECONDS,
    POLL_TIMEOUT_SECONDS,
    require_api_key,
    cancellation_requested,
)


class MuAPIError(RuntimeError):
    pass


def _safe_response_text(response: requests.Response) -> str:
    """Keep provider errors useful without echoing credentials or huge bodies."""
    text = str(response.text or "")[:1000]
    return re.sub(r"(?i)\b(?:api[_ -]?key|token|secret)[=: ]+[^\s,;]+", "[redacted]", text)


def _transient_status(status: int) -> bool:
    return status == 429 or status >= 500


def _headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": require_api_key(),
    }


def submit(endpoint: str, payload: Dict[str, Any], retries: int = 3) -> str:
    """POST to /api/v1/{endpoint} and return the request_id; retry transient errors."""
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise MuAPIError("endpoint must be a non-empty string")
    endpoint = endpoint.strip()
    if not isinstance(payload, dict):
        raise MuAPIError("payload must be a JSON object")
    try:
        retries = int(retries)
    except (TypeError, ValueError, OverflowError):
        retries = 3
    retries = max(1, retries)
    url = f"{MUAPI_BASE_URL}/{endpoint.lstrip('/')}"
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        if cancellation_requested():
            raise MuAPIError("Job cancelled")
        try:
            resp = requests.post(url, json=payload, headers=_headers(), timeout=120)
            if resp.status_code >= 400:
                if not _transient_status(resp.status_code):
                    raise MuAPIError(f"{endpoint} submit failed [{resp.status_code}]: {_safe_response_text(resp)}")
                last_err = MuAPIError(f"transient HTTP {resp.status_code}")
                if attempt + 1 < retries:
                    delay = min(30.0, max(1.0, float(resp.headers.get("Retry-After") or 2.0) * (2**attempt)))
                    time.sleep(delay)
                    continue
                raise last_err
            data = resp.json()
            if not isinstance(data, dict):
                raise MuAPIError(f"{endpoint} response was not a JSON object: {data!r}")
            request_id = data.get("request_id") or data.get("id")
            if not request_id:
                raise MuAPIError(f"{endpoint} response had no request_id: {data}")
            return str(request_id)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(min(30.0, 2.0 * (2**attempt)))
    raise MuAPIError(f"{endpoint} submit failed after {retries} retries: {last_err}")


def fetch_result(request_id: str, retries: int = 3) -> Dict[str, Any]:
    """GET the latest result for a request_id; retry on transient timeouts."""
    request_id = str(request_id).strip() if request_id is not None else ""
    if not request_id:
        raise MuAPIError("request_id must be a non-empty value")
    try:
        retries = int(retries)
    except (TypeError, ValueError, OverflowError):
        retries = 3
    retries = max(1, retries)
    url = f"{MUAPI_BASE_URL}/predictions/{request_id}/result"
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        if cancellation_requested():
            raise MuAPIError("Job cancelled")
        try:
            resp = requests.get(url, headers=_headers(), timeout=90)
            if resp.status_code >= 400:
                if not _transient_status(resp.status_code):
                    raise MuAPIError(f"poll failed [{resp.status_code}]: {_safe_response_text(resp)}")
                last_err = MuAPIError(f"transient HTTP {resp.status_code}")
                if attempt + 1 < retries:
                    time.sleep(min(30.0, 2.0 * (2**attempt)))
                    continue
                raise last_err
            data = resp.json()
            if not isinstance(data, dict):
                raise MuAPIError(f"poll response was not a JSON object: {data!r}")
            return data
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(min(30.0, 2.0 * (2**attempt)))
    raise MuAPIError(f"poll failed after {retries} retries: {last_err}")


def poll(
    request_id: str,
    interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = POLL_TIMEOUT_SECONDS,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Block until the prediction is done; return the final payload."""
    try:
        interval = float(interval)
        timeout = float(timeout)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MuAPIError("poll interval and timeout must be finite numbers") from exc
    if not math.isfinite(interval) or interval < 0:
        raise MuAPIError("poll interval must be a finite number >= 0")
    if not math.isfinite(timeout) or timeout <= 0:
        raise MuAPIError("poll timeout must be a finite number > 0")
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        if cancellation_requested():
            raise MuAPIError("Job cancelled")
        data = fetch_result(request_id)
        if not isinstance(data, dict):
            raise MuAPIError(f"poll response was not a JSON object: {data!r}")
        status = str(data.get("status") or "").strip().lower()
        if status and status != last_status:
            print(f"[muapi] {label or request_id}: {status}", flush=True)
            last_status = status

        if status in ("completed", "succeeded", "success"):
            return data
        if status in ("failed", "error"):
            raise MuAPIError(f"{label or request_id} failed: {data}")

        time.sleep(interval)

    raise MuAPIError(f"{label or request_id} timed out after {timeout}s")


def run(
    endpoint: str,
    payload: Dict[str, Any],
    label: Optional[str] = None,
    interval: float = POLL_INTERVAL_SECONDS,
    timeout: float = POLL_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Submit then poll. Returns the final result payload."""
    request_id = submit(endpoint, payload)
    return poll(request_id, interval=interval, timeout=timeout, label=label or endpoint)
