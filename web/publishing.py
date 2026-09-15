"""Provider-neutral handoffs plus an approval-first YouTube OAuth foundation.

OAuth material is deliberately process-memory only. Refresh tokens are never
written to project metadata, logs, disk, or the browser. The upload adapter
uses YouTube's resumable protocol and requires an explicit confirmation from
the API caller before it is invoked.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

import requests


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    upload_url: str
    authorization_url: str
    title_limit: int
    description_limit: int


PLATFORMS: Dict[str, PlatformSpec] = {
    "youtube_shorts": PlatformSpec(
        "youtube_shorts",
        "YouTube Shorts",
        "https://studio.youtube.com/channel/UC/videos/upload",
        "https://myaccount.google.com/permissions",
        100,
        5000,
    ),
    "tiktok": PlatformSpec(
        "tiktok",
        "TikTok",
        "https://www.tiktok.com/tiktokstudio/upload",
        "https://www.tiktok.com/setting",
        150,
        2200,
    ),
    "instagram_reels": PlatformSpec(
        "instagram_reels",
        "Instagram Reels",
        "https://www.instagram.com/create/select/",
        "https://accountscenter.instagram.com/password_and_security/",
        125,
        2200,
    ),
}


def platform_specs() -> List[Dict[str, Any]]:
    return [asdict(spec) for spec in PLATFORMS.values()]


def build_publish_plan(platform: str, items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a reviewable manual-upload plan for one supported platform."""
    key = str(platform or "").strip().lower()
    spec = PLATFORMS.get(key)
    if spec is None:
        raise ValueError("platform must be youtube_shorts, tiktok, or instagram_reels")
    normalized: List[Dict[str, Any]] = []
    for item in items:
        metadata = item.get("creator_metadata") if isinstance(item, dict) else None
        metadata = metadata if isinstance(metadata, dict) else item if isinstance(item, dict) else {}
        normalized.append(
            {
                "title": str(metadata.get("title") or "Untitled highlight")[: spec.title_limit],
                "description": str(metadata.get("description") or "")[: spec.description_limit],
                "hashtags": str(metadata.get("hashtags") or ""),
                "thumbnail_text": str(metadata.get("thumbnail_text") or "")[:70],
                "clip_start": item.get("start_time") if isinstance(item, dict) else None,
                "clip_end": item.get("end_time") if isinstance(item, dict) else None,
                "clip_url": item.get("play_url") or item.get("clip_url") if isinstance(item, dict) else None,
            }
        )
    return {
        "platform": spec.key,
        "label": spec.label,
        "upload_url": spec.upload_url,
        "authorization_url": spec.authorization_url,
        "items": normalized,
        "requires_manual_upload": True,
        "oauth_status": "not_configured",
        "token_storage": "disabled",
    }


@dataclass(frozen=True)
class YouTubeOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str = "https://www.googleapis.com/auth/youtube.upload"

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


_oauth_lock = threading.RLock()
_oauth_states: Dict[str, Dict[str, Any]] = {}
_youtube_tokens: Dict[str, Any] = {}
_upload_results: Dict[str, Dict[str, Any]] = {}
_OAUTH_STATE_TTL = 600.0
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
_CHUNK_SIZE = 8 * 1024 * 1024


def youtube_oauth_config() -> YouTubeOAuthConfig:
    return YouTubeOAuthConfig(
        client_id=os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
        redirect_uri=os.getenv(
            "YOUTUBE_OAUTH_REDIRECT_URI", "http://127.0.0.1:7860/api/youtube/oauth/callback"
        ).strip(),
        scopes=os.getenv("YOUTUBE_OAUTH_SCOPES", "https://www.googleapis.com/auth/youtube.upload").strip()
        or "https://www.googleapis.com/auth/youtube.upload",
    )


def youtube_oauth_status() -> Dict[str, Any]:
    config = youtube_oauth_config()
    with _oauth_lock:
        token = dict(_youtube_tokens)
    expires_at = float(token.get("expires_at") or 0.0)
    return {
        "configured": config.configured,
        "authorized": bool(token.get("access_token") or token.get("refresh_token")),
        "access_token_valid": bool(token.get("access_token") and expires_at > time.time() + 30),
        "expires_at": expires_at or None,
        "token_storage": "process_memory_only",
        "approval_required": True,
        "privacy_default": "private",
    }


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(48)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def start_youtube_oauth() -> Dict[str, Any]:
    config = youtube_oauth_config()
    if not config.configured:
        raise ValueError("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET before connecting YouTube")
    state = secrets.token_urlsafe(32)
    verifier = _pkce_verifier()
    with _oauth_lock:
        now = time.time()
        _oauth_states[state] = {"verifier": verifier, "created_at": now}
        for key, value in list(_oauth_states.items()):
            if now - float(value.get("created_at") or 0) > _OAUTH_STATE_TTL:
                _oauth_states.pop(key, None)
    query = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": config.scopes,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return {"authorization_url": f"{_AUTH_ENDPOINT}?{query}", "state": state, "expires_in": int(_OAUTH_STATE_TTL)}


def complete_youtube_oauth(code: str, state: str) -> Dict[str, Any]:
    config = youtube_oauth_config()
    if not config.configured:
        raise ValueError("YouTube OAuth is not configured")
    with _oauth_lock:
        session = _oauth_states.pop(str(state or ""), None)
    if not session or time.time() - float(session.get("created_at") or 0) > _OAUTH_STATE_TTL:
        raise ValueError("YouTube OAuth state is missing or expired; start again")
    response = requests.post(
        _TOKEN_ENDPOINT,
        data={
            "code": str(code or ""),
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": session["verifier"],
        },
        timeout=(10, 30),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ValueError("Google did not return an access token")
    with _oauth_lock:
        _youtube_tokens.clear()
        _youtube_tokens.update(
            {
                "access_token": str(payload["access_token"]),
                "refresh_token": str(payload.get("refresh_token") or ""),
                "expires_at": time.time() + float(payload.get("expires_in") or 3600),
            }
        )
    return youtube_oauth_status()


def _youtube_access_token() -> str:
    config = youtube_oauth_config()
    with _oauth_lock:
        token = dict(_youtube_tokens)
    if token.get("access_token") and float(token.get("expires_at") or 0) > time.time() + 30:
        return str(token["access_token"])
    refresh = str(token.get("refresh_token") or "")
    if not refresh or not config.configured:
        raise ValueError("Connect YouTube before approving an upload")
    response = requests.post(
        _TOKEN_ENDPOINT,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
        timeout=(10, 30),
    )
    response.raise_for_status()
    payload = response.json()
    access = str(payload.get("access_token") or "") if isinstance(payload, dict) else ""
    if not access:
        raise ValueError("Google did not return a refreshed access token")
    with _oauth_lock:
        _youtube_tokens["access_token"] = access
        _youtube_tokens["expires_at"] = time.time() + float(payload.get("expires_in") or 3600)
    return access


def _upload_request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    last: Optional[requests.Response] = None
    for attempt in range(5):
        response = requests.request(method, url, **kwargs)
        last = response
        if response.status_code not in {429, 500, 502, 503, 504}:
            return response
        time.sleep(min(8.0, 0.5 * (2**attempt)))
    if last is None:
        raise RuntimeError("YouTube upload request did not return a response")
    return last


def upload_youtube_video(
    media_path: str | Path,
    *,
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    privacy_status: str = "private",
    publish_at: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload one clip through YouTube's resumable upload protocol."""
    path = Path(media_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("clip media is unavailable")
    privacy = str(privacy_status or "private").strip().lower()
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy_status must be private, unlisted, or public")
    if publish_at and privacy != "private":
        raise ValueError("scheduled uploads must remain private")
    request_key = str(idempotency_key or "").strip()[:160]
    if request_key:
        with _oauth_lock:
            previous = _upload_results.get(f"key:{request_key}")
        if previous:
            return dict(previous)
    token = _youtube_access_token()
    body: Dict[str, Any] = {
        "snippet": {
            "title": str(title or "Untitled highlight")[:100],
            "description": str(description or "")[:5000],
            "tags": [str(tag)[:100] for tag in (tags or [])[:30]],
            "categoryId": "22",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = str(publish_at)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Upload-Content-Length": str(path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
        "Content-Type": "application/json; charset=UTF-8",
    }
    session = _upload_request_with_retry(
        "POST",
        f"{_UPLOAD_ENDPOINT}?uploadType=resumable&part=snippet,status",
        headers=headers,
        json=body,
        timeout=(15, 30),
    )
    session.raise_for_status()
    location = str(session.headers.get("Location") or "")
    if not location:
        raise RuntimeError("YouTube did not return a resumable upload URL")
    offset = 0
    total = path.stat().st_size
    with path.open("rb") as stream:
        while offset < total:
            stream.seek(offset)
            chunk = stream.read(_CHUNK_SIZE)
            if not chunk:
                break
            end = offset + len(chunk) - 1
            response = _upload_request_with_retry(
                "PUT",
                location,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{total}",
                    "Content-Type": "video/mp4",
                },
                data=chunk,
                timeout=(15, 120),
            )
            if response.status_code == 308:
                range_header = str(response.headers.get("Range") or "")
                try:
                    offset = int(range_header.rsplit("-", 1)[-1]) + 1 if range_header else end + 1
                except ValueError:
                    offset = end + 1
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not payload.get("id"):
                raise RuntimeError("YouTube returned an invalid upload response")
            result = {"video_id": str(payload["id"]), "url": f"https://youtu.be/{payload['id']}", "privacy_status": privacy}
            with _oauth_lock:
                _upload_results[str(path)] = result
                if request_key:
                    _upload_results[f"key:{request_key}"] = result
            return result
    raise RuntimeError("YouTube resumable upload ended before all bytes were sent")
