"""Per-clip cropping via MuAPI /autocrop.

Given the source video URL plus a highlight's start/end and a target aspect
ratio, MuAPI returns a vertically-cropped short ready for posting.
"""

import math
from typing import Dict

from . import muapi
from .downloader import _extract_video_url


def crop_clip(source_video_url: str, start_time: float, end_time: float, aspect_ratio: str = "9:16") -> str:
    """Submit one autocrop job and return the URL of the rendered short."""
    source_video_url = str(source_video_url).strip() if source_video_url is not None else ""
    if not source_video_url:
        raise ValueError("source video URL is required")
    try:
        start_time = float(start_time)
        end_time = float(end_time)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("clip timestamps must be finite numbers") from exc
    if not math.isfinite(start_time) or not math.isfinite(end_time) or end_time <= start_time:
        raise ValueError("end_time must be greater than start_time")
    payload = {
        "video_url": source_video_url,
        "start_time": float(start_time),
        "end_time": float(end_time),
        "aspect_ratio": aspect_ratio,
    }
    print(f"[clip] {start_time:.1f}s -> {end_time:.1f}s @ {aspect_ratio}", flush=True)
    result = muapi.run("autocrop", payload, label=f"autocrop({start_time:.0f}-{end_time:.0f})")
    return _extract_video_url(result)


def crop_highlights(source_video_url: str, highlights: list, aspect_ratio: str = "9:16") -> list:
    """Crop every highlight, attaching the resulting URL back onto the dict."""
    out = []
    items = highlights if isinstance(highlights, (list, tuple)) else []
    for i, h in enumerate(items, 1):
        if not isinstance(h, dict):
            message = "highlight must be a JSON object"
            print(f"[clip] {i} failed: {message}", flush=True)
            out.append({"clip_url": None, "error": message})
            continue
        print(f"[clip] {i}/{len(items)}: {h.get('title', '(untitled)')}", flush=True)
        try:
            url = crop_clip(
                source_video_url,
                h["start_time"],
                h["end_time"],
                aspect_ratio=aspect_ratio,
            )
            out.append({**h, "clip_url": url})
        except Exception as e:
            print(f"[clip] {i} failed: {e}", flush=True)
            out.append({**h, "clip_url": None, "error": str(e)})
    return out
