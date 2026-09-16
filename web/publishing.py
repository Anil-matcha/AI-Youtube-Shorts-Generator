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
from urllib.parse import urlencode, urlparse

import requests


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    upload_url: str
    authorization_url: str
    title_limit: int
    description_limit: int
    direct_api: bool = False
    requires_public_media: bool = False


PLATFORMS: Dict[str, PlatformSpec] = {
    "youtube_shorts": PlatformSpec(
        "youtube_shorts",
        "YouTube Shorts",
        "https://studio.youtube.com/channel/UC/videos/upload",
        "https://myaccount.google.com/permissions",
        100,
        5000,
        True,
        False,
    ),
    "tiktok": PlatformSpec(
        "tiktok",
        "TikTok",
        "https://www.tiktok.com/tiktokstudio/upload",
        "https://www.tiktok.com/setting",
        150,
        2200,
        True,
        False,
    ),
    "instagram_reels": PlatformSpec(
        "instagram_reels",
        "Instagram Reels",
        "https://www.instagram.com/create/select/",
        "https://accountscenter.instagram.com/password_and_security/",
        125,
        2200,
        True,
        True,
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
    if path.stat().st_size <= 0:
        raise ValueError("clip media is empty")
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


# ---------------------------------------------------------------------------
# Direct publishing adapters
# ---------------------------------------------------------------------------

_TIKTOK_INIT_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/video/init/"
_TIKTOK_STATUS_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
_TIKTOK_CHUNK_SIZE = 10 * 1024 * 1024
_TIKTOK_MAX_SINGLE_CHUNK = 64 * 1024 * 1024


def _configured_or_memory(name: str, memory: Dict[str, Any]) -> str:
    configured = os.getenv(name, "").strip()
    if configured:
        return configured
    with _oauth_lock:
        key = "access_token" if name.endswith("_ACCESS_TOKEN") else name.lower()
        return str(memory.get(key) or "").strip()


def _safe_response_payload(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _social_request_with_retry(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Perform a provider request with bounded retry handling."""
    body = kwargs.get("data")
    body_position: Optional[int] = None
    if hasattr(body, "tell") and hasattr(body, "seek"):
        try:
            body_position = int(body.tell())
        except (OSError, TypeError, ValueError):
            body_position = None
    last: Optional[requests.Response] = None
    for attempt in range(4):
        if body_position is not None:
            try:
                body.seek(body_position)
            except (OSError, TypeError, ValueError):
                body_position = None
        response = requests.request(method, url, **kwargs)
        last = response
        if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
            return response
        time.sleep(min(4.0, 0.4 * (2**attempt)))
    if last is None:
        raise RuntimeError("publishing request did not return a response")
    return last


def tiktok_oauth_config() -> Dict[str, str]:
    return {
        "client_key": os.getenv("TIKTOK_CLIENT_KEY", "").strip(),
        "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("TIKTOK_OAUTH_REDIRECT_URI", "http://127.0.0.1:7860/api/tiktok/oauth/callback").strip(),
    }


def tiktok_oauth_status() -> Dict[str, Any]:
    config = tiktok_oauth_config()
    token = _configured_or_memory("TIKTOK_ACCESS_TOKEN", _tiktok_tokens)
    return {
        "configured": bool(token or (config["client_key"] and config["client_secret"])),
        "authorized": bool(token),
        "token_storage": "process_memory_only",
        "approval_required": True,
        "privacy_default": "private",
    }


def instagram_oauth_config() -> Dict[str, str]:
    return {
        "app_id": os.getenv("INSTAGRAM_APP_ID", "").strip(),
        "app_secret": os.getenv("INSTAGRAM_APP_SECRET", "").strip(),
        "user_id": os.getenv("INSTAGRAM_USER_ID", "").strip(),
        "graph_version": os.getenv("INSTAGRAM_GRAPH_VERSION", "v25.0").strip() or "v25.0",
    }


def instagram_oauth_status() -> Dict[str, Any]:
    config = instagram_oauth_config()
    token = _configured_or_memory("INSTAGRAM_ACCESS_TOKEN", _instagram_tokens)
    credentials_configured = bool(config["app_id"] and config["app_secret"] and config["user_id"])
    authorized = bool(token and config["user_id"])
    return {
        "configured": bool(authorized or credentials_configured),
        "authorized": authorized,
        "token_storage": "process_memory_only",
        "approval_required": True,
        "privacy_default": "private",
        "requires_public_media_url": True,
    }


_tiktok_tokens: Dict[str, Any] = {}
_instagram_tokens: Dict[str, Any] = {}
_social_oauth_states: Dict[str, Dict[str, Any]] = {}
_SOCIAL_OAUTH_TTL = 600.0


def direct_platform_status() -> Dict[str, Dict[str, Any]]:
    return {
        "youtube_shorts": youtube_oauth_status(),
        "tiktok": tiktok_oauth_status(),
        "instagram_reels": instagram_oauth_status(),
    }


def _social_oauth_state(state: str, provider: str) -> Dict[str, Any]:
    with _oauth_lock:
        session = _social_oauth_states.pop(str(state or ""), None)
    if not session or session.get("provider") != provider or time.time() - float(session.get("created_at") or 0) > _SOCIAL_OAUTH_TTL:
        raise ValueError(f"{provider.title()} OAuth state is missing or expired; start again")
    return session


def start_tiktok_oauth() -> Dict[str, Any]:
    config = tiktok_oauth_config()
    if not config["client_key"] or not config["client_secret"]:
        raise ValueError("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET before connecting TikTok")
    state = secrets.token_urlsafe(32)
    with _oauth_lock:
        now = time.time()
        _social_oauth_states[state] = {"provider": "tiktok", "created_at": now}
        for key, value in list(_social_oauth_states.items()):
            if now - float(value.get("created_at") or 0) > _SOCIAL_OAUTH_TTL:
                _social_oauth_states.pop(key, None)
    query = urlencode(
        {
            "client_key": config["client_key"],
            "scope": "user.info.basic,video.publish",
            "response_type": "code",
            "redirect_uri": config["redirect_uri"],
            "state": state,
        }
    )
    return {"authorization_url": f"https://www.tiktok.com/v2/auth/authorize/?{query}", "state": state, "expires_in": int(_SOCIAL_OAUTH_TTL)}


def complete_tiktok_oauth(code: str, state: str) -> Dict[str, Any]:
    config = tiktok_oauth_config()
    if not config["client_key"] or not config["client_secret"]:
        raise ValueError("TikTok OAuth is not configured")
    _social_oauth_state(state, "tiktok")
    response = _social_request_with_retry(
        "POST",
        "https://open.tiktokapis.com/v2/oauth/token/",
        data={
            "client_key": config["client_key"],
            "client_secret": config["client_secret"],
            "code": str(code or ""),
            "grant_type": "authorization_code",
            "redirect_uri": config["redirect_uri"],
        },
        timeout=(15, 30),
    )
    response.raise_for_status()
    payload = _safe_response_payload(response)
    token = str(payload.get("access_token") or "")
    if not token:
        raise ValueError("TikTok did not return an access token")
    with _oauth_lock:
        _tiktok_tokens.clear()
        _tiktok_tokens.update({"access_token": token, "open_id": str(payload.get("open_id") or "")})
    return tiktok_oauth_status()


def start_instagram_oauth() -> Dict[str, Any]:
    config = instagram_oauth_config()
    redirect_uri = os.getenv("INSTAGRAM_OAUTH_REDIRECT_URI", "http://127.0.0.1:7860/api/instagram/oauth/callback").strip()
    if not config["app_id"] or not os.getenv("INSTAGRAM_APP_SECRET", "").strip():
        raise ValueError("Set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET before connecting Instagram")
    state = secrets.token_urlsafe(32)
    with _oauth_lock:
        now = time.time()
        _social_oauth_states[state] = {"provider": "instagram", "created_at": now}
        for key, value in list(_social_oauth_states.items()):
            if now - float(value.get("created_at") or 0) > _SOCIAL_OAUTH_TTL:
                _social_oauth_states.pop(key, None)
    query = urlencode(
        {
            "client_id": config["app_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "instagram_basic,instagram_content_publish",
            "state": state,
        }
    )
    return {"authorization_url": f"https://www.facebook.com/{config['graph_version']}/dialog/oauth?{query}", "state": state, "expires_in": int(_SOCIAL_OAUTH_TTL)}


def complete_instagram_oauth(code: str, state: str) -> Dict[str, Any]:
    config = instagram_oauth_config()
    app_secret = os.getenv("INSTAGRAM_APP_SECRET", "").strip()
    redirect_uri = os.getenv("INSTAGRAM_OAUTH_REDIRECT_URI", "http://127.0.0.1:7860/api/instagram/oauth/callback").strip()
    if not config["app_id"] or not app_secret:
        raise ValueError("Instagram OAuth is not configured")
    _social_oauth_state(state, "instagram")
    response = _social_request_with_retry(
        "GET",
        f"https://graph.facebook.com/{config['graph_version']}/oauth/access_token",
        params={
            "client_id": config["app_id"],
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": str(code or ""),
        },
        timeout=(15, 30),
    )
    response.raise_for_status()
    payload = _safe_response_payload(response)
    token = str(payload.get("access_token") or "")
    if not token:
        raise ValueError("Instagram did not return an access token")
    with _oauth_lock:
        _instagram_tokens.clear()
        _instagram_tokens.update({"access_token": token})
    return instagram_oauth_status()


def _tiktok_access_token() -> str:
    token = _configured_or_memory("TIKTOK_ACCESS_TOKEN", _tiktok_tokens)
    if not token:
        raise ValueError("Connect TikTok before approving an upload")
    return token


def _instagram_access_token() -> str:
    token = _configured_or_memory("INSTAGRAM_ACCESS_TOKEN", _instagram_tokens)
    config = instagram_oauth_config()
    if not token or not config["user_id"]:
        raise ValueError("Configure INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID before approving an upload")
    return token


def publish_tiktok_video(
    media_path: str | Path,
    *,
    title: str,
    privacy_status: str = "private",
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish one local MP4 through TikTok Content Posting API."""
    path = Path(media_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("clip media is unavailable")
    privacy = str(privacy_status or "private").strip().lower()
    privacy_levels = {"private": "SELF_ONLY", "unlisted": "MUTUAL_FOLLOW_FRIENDS", "public": "PUBLIC_TO_EVERYONE"}
    if privacy not in privacy_levels:
        raise ValueError("privacy_status must be private, unlisted, or public")
    request_key = str(idempotency_key or "").strip()[:160]
    if request_key:
        with _oauth_lock:
            previous = _upload_results.get(f"tiktok:{request_key}")
        if previous:
            return dict(previous)
    token = _tiktok_access_token()
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("clip media is empty")
    body = {
        "post_info": {
            "title": str(title or "Untitled highlight")[:150],
            "privacy_level": privacy_levels[privacy],
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size if size <= _TIKTOK_MAX_SINGLE_CHUNK else _TIKTOK_CHUNK_SIZE,
            "total_chunk_count": 1 if size <= _TIKTOK_MAX_SINGLE_CHUNK else (size + _TIKTOK_CHUNK_SIZE - 1) // _TIKTOK_CHUNK_SIZE,
        },
    }
    response = _social_request_with_retry(
        "POST",
        _TIKTOK_INIT_ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=(15, 30),
    )
    response.raise_for_status()
    payload = _safe_response_payload(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    upload_url = str(data.get("upload_url") or "") if isinstance(data, dict) else ""
    publish_id = str(data.get("publish_id") or "") if isinstance(data, dict) else ""
    if not upload_url or not publish_id:
        raise RuntimeError("TikTok did not return an upload URL and publish id")
    chunk_size = int(body["source_info"]["chunk_size"])
    with path.open("rb") as stream:
        offset = 0
        while offset < size:
            chunk = stream.read(chunk_size)
            if not chunk:
                raise RuntimeError("TikTok upload ended before all bytes were sent")
            end = offset + len(chunk) - 1
            upload = _social_request_with_retry(
                "PUT",
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                },
                data=chunk,
                timeout=(15, 180),
            )
            if upload.status_code not in {200, 201, 206}:
                upload.raise_for_status()
            offset = end + 1
    result = {"platform": "tiktok", "publish_id": publish_id, "status": "uploaded"}
    with _oauth_lock:
        _upload_results[f"tiktok:{path}"] = result
        if request_key:
            _upload_results[f"tiktok:{request_key}"] = result
    return result


def publish_instagram_reel(
    media_url: str,
    *,
    caption: str,
    privacy_status: str = "private",
    idempotency_key: Optional[str] = None,
    poll_interval: float = 2.0,
    max_polls: int = 30,
) -> Dict[str, Any]:
    """Publish a Reel through Meta's container API.

    Instagram requires a publicly reachable video URL; the local clip path is
    deliberately rejected by the route instead of being leaked to Meta.
    """
    url = str(media_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Instagram Reels publishing requires a public http(s) media_url")
    privacy = str(privacy_status or "private").strip().lower()
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy_status must be private, unlisted, or public")
    request_key = str(idempotency_key or "").strip()[:160]
    if request_key:
        with _oauth_lock:
            previous = _upload_results.get(f"instagram:{request_key}")
        if previous:
            return dict(previous)
    token = _instagram_access_token()
    config = instagram_oauth_config()
    base = f"https://graph.facebook.com/{config['graph_version']}"
    container_response = _social_request_with_retry(
        "POST",
        f"{base}/{config['user_id']}/media",
        params={"media_type": "REELS", "video_url": url, "caption": str(caption or "")[:2200], "access_token": token},
        timeout=(15, 30),
    )
    container_response.raise_for_status()
    container_payload = _safe_response_payload(container_response)
    container_id = str(container_payload.get("id") or "")
    if not container_id:
        raise RuntimeError("Instagram did not return a media container id")
    status = "IN_PROGRESS"
    for _ in range(max(1, int(max_polls))):
        status_response = _social_request_with_retry(
            "GET",
            f"{base}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=(15, 30),
        )
        status_response.raise_for_status()
        status_payload = _safe_response_payload(status_response)
        status = str(status_payload.get("status_code") or "IN_PROGRESS").upper()
        if status in {"FINISHED", "PUBLISHED"}:
            break
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media container failed with status {status.lower()}")
        if poll_interval > 0:
            time.sleep(min(10.0, max(0.0, float(poll_interval))))
    if status not in {"FINISHED", "PUBLISHED"}:
        raise RuntimeError("Instagram media container did not finish before the polling deadline")
    publish_response = _social_request_with_retry(
        "POST",
        f"{base}/{config['user_id']}/media_publish",
        params={"creation_id": container_id, "access_token": token},
        timeout=(15, 30),
    )
    publish_response.raise_for_status()
    publish_payload = _safe_response_payload(publish_response)
    media_id = str(publish_payload.get("id") or "")
    if not media_id:
        raise RuntimeError("Instagram did not return a published media id")
    result = {"platform": "instagram_reels", "container_id": container_id, "media_id": media_id, "status": "uploaded"}
    with _oauth_lock:
        _upload_results[f"instagram:{url}"] = result
        if request_key:
            _upload_results[f"instagram:{request_key}"] = result
    return result


def publish_direct(
    platform: str,
    media_path: str | Path,
    *,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    privacy_status: str = "private",
    publish_at: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    media_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch an approval-approved upload to a supported direct adapter."""
    key = str(platform or "").strip().lower()
    if publish_at:
        raise ValueError(f"{key} does not support scheduled direct publishing yet; schedule it in the platform studio")
    if key == "youtube_shorts":
        return upload_youtube_video(
            media_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy_status,
            idempotency_key=idempotency_key,
        )
    if key == "tiktok":
        return publish_tiktok_video(media_path, title=title, privacy_status=privacy_status, idempotency_key=idempotency_key)
    if key == "instagram_reels":
        if not media_url:
            raise ValueError("Instagram Reels publishing requires a public media_url")
        return publish_instagram_reel(
            media_url,
            caption=(description or title),
            privacy_status=privacy_status,
            idempotency_key=idempotency_key,
        )
    raise ValueError("platform must be youtube_shorts, tiktok, or instagram_reels")
