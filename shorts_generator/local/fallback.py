"""Dependency-free highlight ranking for first-run/offline local mode.

When no OpenAI or Gemini key is configured, Local mode still needs to be
usable.  This module ranks short transcript windows using deterministic
signals (speech density and emphasis punctuation) so a user can render a
first project before configuring an optional LLM provider.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List


def _finite(value: object, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return converted if math.isfinite(converted) else default


def _int(value: object, default: int = 3) -> int:
    converted = _finite(value, float(default))
    return int(converted) if math.isfinite(converted) else default


def rank_highlights_offline(transcript: Dict, num_clips: int = 3) -> List[Dict]:
    """Return usable highlight objects without a network/LLM dependency."""
    raw_segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    if not isinstance(raw_segments, (list, tuple)):
        return []

    segments = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        start = _finite(raw.get("start"), -1.0)
        end = _finite(raw.get("end"), -1.0)
        text = " ".join(str(raw.get("text") or "").split())
        if start < 0 or end <= start or not text:
            continue
        segments.append({"start": start, "end": end, "text": text})
    if not segments:
        return []

    duration = _finite(transcript.get("duration"), 0.0) if isinstance(transcript, dict) else 0.0
    duration = max(duration, max(segment["end"] for segment in segments))
    target = max(1, min(12, _int(num_clips, 3)))
    candidates: List[Dict] = []

    for index, segment in enumerate(segments):
        start = segment["start"]
        # A 15-second window is long enough to be useful but short enough to
        # create several non-overlapping candidates in a normal video.
        end = min(duration, max(segment["end"], start + 15.0))
        if end <= start:
            continue
        words = []
        for following in segments[index:]:
            if following["start"] >= end:
                break
            words.append(following["text"])
        text = " ".join(words).strip() or segment["text"]
        word_count = len(re.findall(r"\b\w+\b", text))
        emphasis = text.count("!") + text.count("?")
        score = max(1, min(100, 35 + min(45, word_count * 2) + min(20, emphasis * 5)))
        hook = segment["text"][:180].strip()
        title_words = hook.split()
        title = " ".join(title_words[:9]).strip() or "Offline highlight"
        if len(title_words) > 9:
            title += "..."
        candidates.append(
            {
                "title": title[:120],
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "score": score,
                "hook_sentence": hook,
                "virality_reason": "Offline transcript ranking; configure OpenAI or Gemini for richer AI ranking.",
            }
        )

    # Keep the strongest windows while avoiding a list of near-duplicates.
    candidates.sort(key=lambda item: (item["score"], item["end_time"] - item["start_time"]), reverse=True)
    selected: List[Dict] = []
    for candidate in candidates:
        overlap = False
        candidate_duration = candidate["end_time"] - candidate["start_time"]
        for previous in selected:
            shared = min(candidate["end_time"], previous["end_time"]) - max(
                candidate["start_time"], previous["start_time"]
            )
            if shared > 0 and shared > 0.5 * candidate_duration:
                overlap = True
                break
        if not overlap:
            selected.append(candidate)
        if len(selected) >= target:
            break
    return sorted(selected, key=lambda item: item["start_time"])
