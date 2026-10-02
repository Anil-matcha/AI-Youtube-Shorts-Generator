"""Bounded, local-first story search across project evidence."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Sequence

from web.security import redact_text
from web.story_evidence import clean_evidence_text


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]{1,48}")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "with",
        "you",
    }
)
_VISUAL_ALIASES = {
    "scene": {"scene_change"},
    "scenes": {"scene_change"},
    "change": {"scene_change"},
    "cut": {"scene_change"},
    "cuts": {"scene_change"},
    "face": {"speaker_visible", "multiple_speakers"},
    "faces": {"speaker_visible", "multiple_speakers"},
    "speaker": {"speaker_visible", "multiple_speakers"},
    "speakers": {"speaker_visible", "multiple_speakers"},
    "reaction": {"speaker_visible", "multiple_speakers"},
}


def _tokens(value: object) -> List[str]:
    words = [item.casefold() for item in _TOKEN_PATTERN.findall(str(value or ""))]
    return [item for item in words if item not in _STOP_WORDS]


def _number(value: object, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return converted if math.isfinite(converted) else default


def _bounded_text(value: object, limit: int = 320) -> str:
    text = redact_text(" ".join(str(value or "").replace("\x00", "").split()), max_length=limit)
    # Search is a metadata surface, not a media locator. Older project records
    # may contain a Windows path in a project name or transcript, so remove
    # drive/UNC-shaped values before returning snippets to a client.
    return re.sub(r"(?<!\w)(?:[A-Za-z]:[\\/]|\\\\)[^\s]+", "[local path redacted]", text)[:limit]


def _matching_terms(query_terms: Sequence[str], text: str) -> List[str]:
    haystack = set(_tokens(text))
    return [term for term in query_terms if term in haystack]


def _lexical_score(query: str, query_terms: Sequence[str], text: str, *, boost: float = 1.0) -> float:
    haystack = " ".join(_tokens(text))
    if not haystack:
        return 0.0
    matches = _matching_terms(query_terms, text)
    if not matches:
        return 0.0
    score = len(set(matches)) / max(1, len(set(query_terms)))
    if query.casefold() in haystack:
        score += 0.35
    return round(score * boost, 6)


def _visual_context(events: Iterable[Dict[str, Any]], start: float, end: float) -> List[Dict[str, Any]]:
    context: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        timestamp = _number(event.get("time"), -1.0)
        if timestamp < 0 or timestamp > end + 2.0 or timestamp < start - 2.0:
            continue
        context.append(
            {
                "time": round(timestamp, 2),
                "type": str(event.get("type") or "visual_signal")[:48],
                "score": round(max(0.0, min(1.0, _number(event.get("score"), 0.0))), 3),
            }
        )
    return context[:12]


def _search_one_job(job: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
    job_id = str(job.get("id") or "")
    project_name = _bounded_text(job.get("name") or "Untitled project", 100)
    query_terms = _tokens(query)
    if not query_terms:
        return []
    transcript = job.get("raw_transcript") if isinstance(job.get("raw_transcript"), dict) else {}
    visual_events = transcript.get("visual_events") if isinstance(transcript.get("visual_events"), list) else []
    chapters = transcript.get("chapters") if isinstance(transcript.get("chapters"), list) else []
    hits: List[Dict[str, Any]] = []
    for segment in (transcript.get("segments") if isinstance(transcript.get("segments"), list) else [])[:2000]:
        if not isinstance(segment, dict):
            continue
        text = _bounded_text(segment.get("text"), 500)
        score = _lexical_score(query, query_terms, text, boost=1.0)
        if score <= 0:
            continue
        start = max(0.0, _number(segment.get("start")))
        end = max(start, _number(segment.get("end"), start))
        hits.append(
            {
                "job_id": job_id,
                "project_name": project_name,
                "kind": "transcript",
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "title": "Transcript match",
                "snippet": text,
                "matched_terms": _matching_terms(query_terms, text),
                "visual_signals": _visual_context(visual_events, start, end),
                "score": score,
            }
        )

    for chapter in chapters[:500]:
        if not isinstance(chapter, dict):
            continue
        title = _bounded_text(chapter.get("title"), 200)
        score = _lexical_score(query, query_terms, title, boost=0.9)
        if score <= 0:
            continue
        start = max(0.0, _number(chapter.get("start_time")))
        end = max(start, _number(chapter.get("end_time"), start))
        hits.append(
            {
                "job_id": job_id,
                "project_name": project_name,
                "kind": "chapter",
                "start_time": round(start, 3),
                "end_time": round(end, 3) if end else None,
                "title": title or "Chapter",
                "snippet": title,
                "matched_terms": _matching_terms(query_terms, title),
                "visual_signals": _visual_context(visual_events, start, end or start + 1.0),
                "score": score,
            }
        )

    shorts = job.get("raw_shorts") if isinstance(job.get("raw_shorts"), list) else []
    for index, short in enumerate(shorts[:100]):
        if not isinstance(short, dict):
            continue
        title = _bounded_text(short.get("title"), 180)
        hook = _bounded_text(short.get("hook_sentence"), 320)
        reason = _bounded_text(short.get("virality_reason"), 320)
        searchable = f"{title} {hook} {reason}"
        score = _lexical_score(query, query_terms, searchable, boost=1.15)
        if score <= 0:
            continue
        start = max(0.0, _number(short.get("start_time")))
        end = max(start, _number(short.get("end_time"), start))
        hits.append(
            {
                "job_id": job_id,
                "project_name": project_name,
                "kind": "highlight",
                "clip_index": index,
                "start_time": round(start, 3),
                "end_time": round(end, 3) if end else None,
                "title": title or "Highlight",
                "snippet": hook or reason or title,
                "matched_terms": _matching_terms(query_terms, searchable),
                "visual_signals": _visual_context(visual_events, start, end or start + 1.0),
                "score": score,
            }
        )

    for event in visual_events[:500]:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "visual_signal").casefold()
        aliases = {term for query_term in query_terms for term in _VISUAL_ALIASES.get(query_term, set())}
        if event_type not in aliases:
            continue
        timestamp = max(0.0, _number(event.get("time")))
        hits.append(
            {
                "job_id": job_id,
                "project_name": project_name,
                "kind": "visual",
                "start_time": round(timestamp, 3),
                "end_time": round(timestamp, 3),
                "title": event_type.replace("_", " ").title(),
                "snippet": f"Local visual signal: {event_type.replace('_', ' ')}",
                "matched_terms": [term for term in query_terms if term in _VISUAL_ALIASES and event_type in _VISUAL_ALIASES[term]],
                "visual_signals": _visual_context([event], timestamp, timestamp),
                "score": 0.8,
            }
        )
    evidence = job.get("story_evidence") if isinstance(job.get("story_evidence"), dict) else {}
    for kind in ("ocr", "audio"):
        items = evidence.get(kind) if isinstance(evidence.get(kind), list) else []
        for item in items[:240]:
            if not isinstance(item, dict):
                continue
            text = clean_evidence_text(item.get("text"))
            score = _lexical_score(query, query_terms, text, boost=0.85)
            if score <= 0:
                continue
            start = max(0.0, _number(item.get("start_time")))
            end = max(start, _number(item.get("end_time"), start))
            hits.append({"job_id": job_id, "project_name": project_name, "kind": kind,
                         "start_time": round(start, 3), "end_time": round(end, 3),
                         "title": "On-screen text" if kind == "ocr" else "Speech activity",
                         "snippet": text, "matched_terms": _matching_terms(query_terms, text),
                         "visual_signals": _visual_context(visual_events, start, end), "score": score})
    return hits


def search_jobs(jobs: Iterable[Dict[str, Any]], query: str, *, limit: int = 25) -> Dict[str, Any]:
    """Search persisted project evidence without exposing source URLs or media paths."""
    cleaned_query = " ".join(str(query or "").replace("\x00", "").split())[:200]
    bounded_limit = max(1, min(50, int(limit)))
    all_hits: List[Dict[str, Any]] = []
    searched_projects = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        searched_projects += 1
        all_hits.extend(_search_one_job(job, cleaned_query))
    all_hits.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            float(item.get("start_time") or 0.0),
            str(item.get("job_id") or ""),
        ),
        reverse=True,
    )
    return {
        "query": cleaned_query,
        "searched_projects": searched_projects,
        "result_count": min(len(all_hits), bounded_limit),
        "results": all_hits[:bounded_limit],
    }
