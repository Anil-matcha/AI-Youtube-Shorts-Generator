"""Transcription via MuAPI /openai-whisper.

Sends a hosted media URL to MuAPI's Whisper endpoint and returns the segment
shape expected by the highlight generator: {duration, segments[start,end,text]}.
The API runs verbose_json server-side, so we get per-segment timestamps for free.
"""

import json
import math
from typing import Dict, Optional

from . import muapi


def _coerce_verbose(raw) -> Dict:
    """The /openai-whisper result can land as a dict or a JSON string depending on
    how the worker stored it. Normalise to a dict with `duration` and `segments`."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _extract_verbose_payload(result: Dict) -> Dict:
    """MuAPI wraps results inconsistently across endpoints. Hunt for the
    verbose_json blob (which has `segments` + `duration`)."""
    if not isinstance(result, dict):
        raise RuntimeError(f"Could not find Whisper segments in MuAPI response: {result!r}")
    for key in ("output", "result", "outputs"):
        v = result.get(key)
        if isinstance(v, dict) and "segments" in v:
            return v
        if isinstance(v, list) and v:
            first = v[0]
            decoded = _coerce_verbose(first)
            if "segments" in decoded:
                return decoded
        if isinstance(v, str):
            decoded = _coerce_verbose(v)
            if "segments" in decoded:
                return decoded

    if "segments" in result:
        return result

    raise RuntimeError(f"Could not find Whisper segments in MuAPI response: {result}")


def transcribe(media_url: str, language: Optional[str] = None) -> Dict:
    """Run MuAPI /openai-whisper on a hosted media URL.

    Returns {duration: float, segments: [{start, end, text}, ...]} so it slots
    straight into the highlight generator.
    """
    print(f"[transcribe] muapi /openai-whisper on {media_url}", flush=True)
    payload = {
        "audio_url": media_url,
        "response_format": "verbose_json",
    }
    if language:
        payload["language"] = language

    result = muapi.run("openai-whisper", payload, label="openai-whisper")
    verbose = _extract_verbose_payload(result)

    segments = []
    raw_segments = verbose.get("segments")
    segment_items = raw_segments if isinstance(raw_segments, (list, tuple)) else []
    for s in segment_items:
        if not isinstance(s, dict):
            continue
        try:
            start = float(s.get("start", 0.0))
            end = float(s.get("end", 0.0))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        segments.append({"start": start, "end": end, "text": text})

    try:
        duration = float(verbose.get("duration") or 0.0)
    except (TypeError, ValueError, OverflowError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        duration = max((segment["end"] for segment in segments), default=0.0)
    print(f"[transcribe] {len(segments)} segments, {duration:.0f}s of audio", flush=True)
    return {"duration": duration, "segments": segments}
