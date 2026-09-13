"""YouTube source video download via MuAPI /youtube-download."""

from typing import Dict

from . import muapi


def _extract_video_url(result: Dict) -> str:
    """MuAPI result shapes vary by endpoint — try common keys."""
    if not isinstance(result, dict):
        raise RuntimeError(f"Could not find downloaded video URL in MuAPI response: {result!r}")
    for key in ("video_url", "url", "output_url", "result_url"):
        v = result.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v

    output = result.get("outputs") or result.get("output") or result.get("result") or {}
    if isinstance(output, dict):
        for key in ("video_url", "url", "output_url"):
            v = output.get(key)
            if isinstance(v, str) and v.startswith("http"):
                return v
    if isinstance(output, list) and output and isinstance(output[0], str) and output[0].startswith("http"):
        return output[0]

    raise RuntimeError(f"Could not find downloaded video URL in MuAPI response: {result}")


def download_youtube(video_url: str, fmt: str = "720") -> str:
    """Hand a YouTube URL to MuAPI; return a hosted mp4 URL we can read from."""
    if not video_url or not str(video_url).strip():
        raise ValueError("A YouTube URL is required.")
    video_url = str(video_url).strip()
    print(f"[download] requesting {video_url} @ {fmt}p", flush=True)
    result = muapi.run(
        "youtube-download",
        {"video_url": video_url, "format": fmt},
        label="youtube-download",
    )
    out = _extract_video_url(result)
    print(f"[download] ready: {out}", flush=True)
    return out
