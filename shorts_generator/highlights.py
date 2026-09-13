"""Find the most viral-worthy highlights in a transcript.

Logic ported from ViralVadoo's transcript_analysis/highlight_generator.py:
  - content-type / density detection
  - chunking for long videos with overlap
  - virality-criteria prompt
  - score-based dedupe with overlap suppression

The LLM call is pluggable via the `llm_fn` argument so the same prompts can
drive either MuAPI (default, --mode api) or a direct local LLM client
(--mode local).
"""

import json
import math
import re
from typing import Callable, Dict, List, Optional

from . import muapi


LLMFn = Callable[[str], str]


CONTENT_TYPE_PROMPT = """Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low (mostly filler/chit-chat), medium, or high (dense info/stories).
Respond with JSON only: {"content_type": "...", "density": "..."}"""


VIRALITY_CRITERIA = """
Virality signals to prioritize (ranked by impact):
1. HOOK MOMENTS — statements that create immediate curiosity ("The secret is...", "Nobody talks about...", "I was completely wrong about...")
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reactions
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements that trigger agree/disagree
4. REVELATION MOMENTS — surprising facts, stats, or confessions that reframe how the viewer thinks
5. CONFLICT/TENSION — disagreement, pushback, or a problem being confronted head-on
6. QUOTABLE ONE-LINERS — a sentence that works as a standalone quote card
7. STORY PEAKS — the climax or twist of an anecdote; the payoff moment
8. PRACTICAL VALUE — a concrete tip, hack, or insight the viewer can immediately apply
"""


HIGHLIGHT_SYSTEM_PROMPT = """You are an elite short-form video editor who has studied thousands of viral clips on TikTok, Instagram Reels, and YouTube Shorts. You know exactly what makes viewers stop scrolling, watch to the end, and share.

{virality_criteria}

Content type: {content_type} | Density: {density}
Selection focus: {focus_instruction}

Your task: identify the most viral-worthy highlights from the transcript.

Rules:
- Every highlight must open with a strong HOOK — a line that grabs attention within the first 3 seconds
- Duration sweet spot: 45-90 seconds. Go shorter (20-44s) only for a perfect standalone one-liner. Go longer (91-180s) only when a story arc needs full context to land
- Never cut mid-sentence or mid-thought — each clip must feel complete and self-contained
- Clips must not overlap significantly with each other
- Score 0-100 on viral potential (not general quality)
- {num_clips_instruction}
- For each highlight, identify the single best "hook_sentence" — the opening line that would make someone stop scrolling
- Explain in one sentence why this clip is viral ("virality_reason")

Respond ONLY with valid JSON (no markdown, no explanation):
{{"highlights":[{{"title":"string","start_time":float,"end_time":float,"score":int,"hook_sentence":"string","virality_reason":"string"}}]}}"""


CHUNK_SIZE_SECONDS = 1200  # 20-min chunks for long videos
LONG_VIDEO_THRESHOLD = 1800  # chunk videos longer than 30 min
CHUNK_OVERLAP_SECONDS = 60
GPT_CALL_TIMEOUT_SECONDS = 300  # cap LLM polls at 5 min — a wedged call should fail fast
MAX_HIGHLIGHT_API_ATTEMPTS = 3


def call_muapi_llm(prompt: str) -> str:
    """Default LLM backend: MuAPI gpt-5-mini."""
    result = muapi.run(
        "gpt-5-mini",
        {"prompt": prompt},
        label="gpt-5-mini",
        timeout=GPT_CALL_TIMEOUT_SECONDS,
    )

    outputs = result.get("outputs")
    if isinstance(outputs, list) and outputs and isinstance(outputs[0], str) and outputs[0].strip():
        return outputs[0]

    for key in ("output", "text", "response", "result", "content"):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):
            inner = v.get("text") or v.get("content")
            if isinstance(inner, str) and inner.strip():
                return inner
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[0]

    raise RuntimeError(f"Could not extract gpt-5-mini text from response: {result}")


def _parse_json_loose(raw: str) -> Dict:
    """gpt-5-4 sometimes wraps JSON in markdown fences — strip and parse."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return converted if math.isfinite(converted) else default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _items(value: object) -> List:
    """Return list-like model data, treating malformed containers as empty."""
    return list(value) if isinstance(value, (list, tuple)) else []


def _sanitize_highlights(raw_highlights: object, duration: float) -> List[Dict]:
    """Normalize model output into the expected shape; skip invalid entries."""
    if not isinstance(raw_highlights, list):
        return []

    max_end = duration if duration > 0 else float("inf")
    cleaned: List[Dict] = []
    for item in raw_highlights:
        if not isinstance(item, dict):
            continue

        start = _coerce_float(item.get("start_time"), default=-1.0)
        end = _coerce_float(item.get("end_time"), default=-1.0)
        if start < 0 or end <= start:
            continue

        if max_end != float("inf"):
            start = min(start, max_end)
            end = min(end, max_end)
            if end <= start:
                continue

        cleaned.append(
            {
                "title": str(item.get("title") or "Untitled Highlight").strip(),
                "start_time": start,
                "end_time": end,
                "score": max(0, min(100, _coerce_int(item.get("score"), default=0))),
                "hook_sentence": str(item.get("hook_sentence") or "").strip(),
                "virality_reason": str(item.get("virality_reason") or "").strip(),
            }
        )

    return cleaned


def detect_content_type(transcript: Dict, llm_fn: LLMFn = call_muapi_llm) -> Dict[str, str]:
    segments = _items(transcript.get("segments", []) if isinstance(transcript, dict) else [])
    sample = " ".join(str(segment.get("text") or "").strip() for segment in segments[:25] if isinstance(segment, dict))[
        :3000
    ]
    prompt = f"{CONTENT_TYPE_PROMPT}\n\nTranscript sample:\n{sample}"
    try:
        raw = llm_fn(prompt)
        parsed = _parse_json_loose(raw)
        if not isinstance(parsed, dict):
            raise ValueError("content classifier returned a non-object JSON value")
        content_type = str(parsed.get("content_type") or "other").strip().lower()
        density = str(parsed.get("density") or "medium").strip().lower()
        return {
            "content_type": content_type[:40] or "other",
            "density": density[:20] or "medium",
        }
    except Exception:
        return {"content_type": "other", "density": "medium"}


def build_transcript_text(transcript: Dict) -> str:
    segments = _items(transcript.get("segments", []) if isinstance(transcript, dict) else [])
    lines = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _coerce_float(segment.get("start"), default=-1.0)
        if start < 0:
            continue
        text_value = str(segment.get("text") or "").strip()
        if text_value:
            lines.append(f"[{start:.1f}s] {text_value}")
    text = "\n".join(lines)
    visual_events = _items(transcript.get("visual_events") if isinstance(transcript, dict) else [])
    if visual_events:
        text += "\n\nVisual signals (use as supporting evidence, not as guaranteed context):\n"
        visual_lines = []
        for event in visual_events[:400]:
            if not isinstance(event, dict):
                continue
            timestamp = _coerce_float(event.get("time"), default=0.0)
            event_type = str(event.get("type") or "visual_event").strip() or "visual_event"
            visual_lines.append(f"[{timestamp:.1f}s] {event_type}")
        text += "\n".join(visual_lines)
    return text


def chunk_transcript(transcript: Dict) -> List[Dict]:
    raw_segments = _items(transcript.get("segments", []) if isinstance(transcript, dict) else [])
    segments = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        start = _coerce_float(raw.get("start"), default=-1.0)
        end = _coerce_float(raw.get("end"), default=-1.0)
        if start < 0 or end <= start:
            continue
        segment = dict(raw)
        segment["start"] = start
        segment["end"] = end
        segments.append(segment)
    duration = _coerce_float(
        transcript.get("duration") if isinstance(transcript, dict) else None,
        default=0.0,
    )
    if duration <= 0:
        duration = max((s["end"] for s in segments), default=0.0)
    if duration <= 0:
        return []
    chunks = []
    start = 0
    while start < duration:
        end = min(start + CHUNK_SIZE_SECONDS, duration)
        chunk_segs = [s for s in segments if s["start"] >= start and s["end"] <= end + CHUNK_OVERLAP_SECONDS]
        if chunk_segs:
            chunk = dict(transcript) if isinstance(transcript, dict) else {}
            chunk["segments"] = chunk_segs
            chunk["duration"] = end - start
            chunk["_offset"] = start
            chunks.append(chunk)
        start += CHUNK_SIZE_SECONDS - CHUNK_OVERLAP_SECONDS
    return chunks


def call_highlight_api(
    transcript_text: str,
    content_info: Dict,
    duration: float,
    num_clips: int,
    is_chunk: bool = False,
    llm_fn: LLMFn = call_muapi_llm,
    focus: str = "balanced",
) -> Dict:
    duration = max(0.0, _coerce_float(duration, default=0.0))
    num_clips = max(1, min(12, _coerce_int(num_clips, default=3)))
    content_info = content_info if isinstance(content_info, dict) else {}
    # Ask for ~2× the user's target so dedupe has headroom, but cap so the model
    # doesn't have to generate a huge JSON payload (which times out gpt-5-mini).
    target = max(num_clips * 2, 5)
    natural_max = max(2 if is_chunk else 3, int(duration / 90))
    min_clips = min(target, natural_max, 8)
    focus_instructions = {
        "balanced": "balance hooks, emotion, novelty, conflict, and practical value",
        "educational": "favor clear teachable insights, steps, facts, and useful takeaways",
        "funny": "favor laughter, surprise, reactions, witty lines, and comedic timing",
        "story": "favor vulnerability, narrative build-up, emotional turns, and satisfying payoffs",
        "controversial": "favor strong opinions, disagreement, debate, and counter-intuitive claims",
        "visual": "favor energetic moments, expressive reactions, reveals, and visually motivated beats",
    }
    normalized_focus = str(focus or "balanced").strip().lower()
    system = HIGHLIGHT_SYSTEM_PROMPT.format(
        virality_criteria=VIRALITY_CRITERIA,
        content_type=content_info.get("content_type", "other"),
        density=content_info.get("density", "medium"),
        num_clips_instruction=f"Generate at least {min_clips} highlights",
        focus_instruction=focus_instructions.get(normalized_focus, focus_instructions["balanced"]),
    )
    base_prompt = f"{system}\n\nTranscript:\n{transcript_text}"
    prompt = base_prompt
    last_error = "unknown"

    for attempt in range(1, MAX_HIGHLIGHT_API_ATTEMPTS + 1):
        raw = llm_fn(prompt)
        try:
            parsed = _parse_json_loose(raw)
            highlights = _sanitize_highlights(parsed.get("highlights"), duration=duration)
            if highlights:
                return {"highlights": highlights}
            last_error = "no valid highlights in response"
        except Exception as e:
            last_error = str(e)

        if attempt < MAX_HIGHLIGHT_API_ATTEMPTS:
            print(
                f"[highlights] invalid model output on attempt {attempt}/{MAX_HIGHLIGHT_API_ATTEMPTS}; retrying",
                flush=True,
            )
            prompt = (
                base_prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON with a top-level 'highlights' array."
                + " Each item must include: title, start_time, end_time, score, hook_sentence, virality_reason."
                + " No markdown fences, no commentary."
            )

    raise RuntimeError(
        f"Highlight generator produced invalid output after {MAX_HIGHLIGHT_API_ATTEMPTS} attempts: {last_error}"
    )


def dedupe_highlights(highlights: List[Dict]) -> List[Dict]:
    """Drop a highlight if it overlaps >50% with a higher-scoring one already kept."""
    highlights = sorted(
        (item for item in (highlights or []) if isinstance(item, dict)),
        key=lambda x: _coerce_int(x.get("score"), default=0),
        reverse=True,
    )
    kept: List[Dict] = []
    for h in highlights:
        if not isinstance(h, dict):
            continue
        h_start = _coerce_float(h.get("start_time"), default=-1.0)
        h_end = _coerce_float(h.get("end_time"), default=-1.0)
        h_dur = h_end - h_start
        if h_start < 0 or h_end <= h_start:
            continue
        overlapping = False
        for k in kept:
            latest_start = max(h_start, _coerce_float(k.get("start_time"), default=-1.0))
            earliest_end = min(h_end, _coerce_float(k.get("end_time"), default=-1.0))
            overlap = earliest_end - latest_start
            if overlap > 0 and overlap > 0.5 * h_dur:
                overlapping = True
                break
        if not overlapping:
            kept.append(h)
    return kept


def snap_highlight_boundaries(highlights: List[Dict], transcript: Dict) -> List[Dict]:
    """Snap model timestamps to the nearest Whisper segment boundaries.

    LLM timestamps are useful estimates, but they frequently land in the
    middle of a spoken sentence.  Whisper already gives us stable segment
    boundaries, so use the nearest segment start for a clip start and the
    nearest segment end for a clip end.  If a malformed/very short candidate
    would invert after snapping, retain its original timestamps instead of
    dropping an otherwise useful highlight.
    """
    segments = _items(transcript.get("segments") if isinstance(transcript, dict) else [])
    starts: List[float] = []
    ends: List[float] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _coerce_float(segment.get("start"), default=-1.0)
        end = _coerce_float(segment.get("end"), default=-1.0)
        if start < end:
            starts.append(start)
            ends.append(end)

    if not starts or not ends:
        return [dict(h) for h in (highlights or []) if isinstance(h, dict)]

    starts.sort()
    ends.sort()

    def nearest(value: float, choices: List[float]) -> float:
        return min(choices, key=lambda candidate: (abs(candidate - value), candidate))

    snapped: List[Dict] = []
    for highlight in highlights:
        if not isinstance(highlight, dict):
            continue
        original_start = _coerce_float(highlight.get("start_time"), default=-1.0)
        original_end = _coerce_float(highlight.get("end_time"), default=-1.0)
        if original_start < 0 or original_end <= original_start:
            snapped.append(dict(highlight))
            continue

        start = nearest(original_start, starts)
        end = nearest(original_end, ends)
        if end <= start:
            # Keep the candidate valid if a short highlight has crossed after
            # independent nearest-boundary snapping.
            valid_ends = [candidate for candidate in ends if candidate > start]
            if valid_ends:
                end = nearest(original_end, valid_ends)
            else:
                start = original_start
                end = original_end

        item = dict(highlight)
        item["start_time"] = start
        item["end_time"] = end
        snapped.append(item)

    return snapped


def get_highlights(
    transcript: Dict,
    num_clips: int = 3,
    llm_fn: Optional[LLMFn] = None,
    focus: str = "balanced",
) -> Dict:
    """Main entry point — returns {highlights: [...]} sorted by score.

    `llm_fn` swaps the underlying LLM. Defaults to MuAPI gpt-5-mini; local
    mode passes in a local LLM-backed callable.
    """
    llm_fn = llm_fn or call_muapi_llm
    duration = _coerce_float(
        transcript.get("duration") if isinstance(transcript, dict) else None,
        default=0.0,
    )
    if duration <= 0 and isinstance(transcript, dict):
        duration = max(
            (
                _coerce_float(segment.get("end"), default=0.0)
                for segment in _items(transcript.get("segments", []))
                if isinstance(segment, dict)
            ),
            default=0.0,
        )
    content_info = detect_content_type(transcript, llm_fn=llm_fn)
    print(
        f"[highlights] content={content_info.get('content_type')} density={content_info.get('density')} duration={duration:.0f}s",
        flush=True,
    )

    if duration >= LONG_VIDEO_THRESHOLD:
        chunks = chunk_transcript(transcript)
        print(f"[highlights] long video - splitting into {len(chunks)} chunks", flush=True)
        all_highlights: List[Dict] = []
        for i, chunk in enumerate(chunks):
            offset = float(chunk.get("_offset", 0))
            chunk_duration = float(chunk.get("duration", 0))
            text = build_transcript_text(chunk)
            print(f"[highlights] chunk {i + 1}/{len(chunks)} (offset {offset:.0f}s)", flush=True)
            # Segment timestamps embedded in the transcript text are absolute
            # (relative to the full video). Validate against the FULL video
            # duration so later-chunk absolute times are not discarded.
            try:
                result = call_highlight_api(
                    text,
                    content_info,
                    duration,
                    num_clips=num_clips,
                    is_chunk=True,
                    llm_fn=llm_fn,
                    focus=focus,
                )
            except RuntimeError as e:
                # One bad chunk shouldn't kill the whole run if others worked.
                print(f"[highlights] chunk {i + 1}/{len(chunks)} failed: {e}", flush=True)
                continue

            chunk_highlights = result.get("highlights", [])
            # Models sometimes return chunk-relative times (0-based) and
            # sometimes absolute times matching the transcript. Detect and
            # normalize so either shape lands on the correct absolute window.
            if offset > 0 and chunk_highlights:
                max_end = max(float(h["end_time"]) for h in chunk_highlights)
                looks_relative = max_end <= chunk_duration + 5.0
                if looks_relative:
                    for h in chunk_highlights:
                        h["start_time"] = float(h["start_time"]) + offset
                        h["end_time"] = float(h["end_time"]) + offset

            all_highlights.extend(chunk_highlights)

        if not all_highlights:
            raise RuntimeError("Highlight generator returned zero clips across all chunks.")
        highlights = dedupe_highlights(all_highlights)
    else:
        text = build_transcript_text(transcript)
        result = call_highlight_api(
            text,
            content_info,
            duration,
            num_clips=num_clips,
            llm_fn=llm_fn,
            focus=focus,
        )
        highlights = dedupe_highlights(result.get("highlights", []))

    # Snap only after dedupe so overlap suppression is based on the model's
    # intended windows, then dedupe once more in case adjacent candidates land
    # on the same Whisper boundaries.
    highlights = snap_highlight_boundaries(highlights, transcript)
    return {"highlights": dedupe_highlights(highlights)}
