"""Provider-neutral publishing handoffs.

Shorts Studio deliberately does not retain OAuth refresh tokens or upload
silently.  These adapters provide official destination links and normalized
metadata so a creator can review and publish in the platform's own UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List


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
