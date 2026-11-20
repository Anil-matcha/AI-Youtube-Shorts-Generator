"""Find the most viral-worthy highlights in a transcript with diversity and boundary snapping.

Features:
- 5-Tier Canonical Archetypes: SATIRE_COMMERCIAL, DIALOGUE_BANTER, ACTION_HEIST, LORE_BACKSTORY, STUNT_FAIL.
- Guarded Temporal Non-Maximum Suppression (T-NMS >= 45s guard band, strict 0% overlap).
- Whisper microsecond audio & sentence boundary snapping (no phoneme truncation or mid-syllable cuts).
- Cross-run stateful persistence via ClipRegistry (prevents collision across repeated runs).
"""

import json
import re
from typing import Callable, Dict, List, Optional, Tuple

from . import muapi
from .boundary_snapper import AudioBoundarySnapper
from .clip_registry import ClipRegistry
from .diversity_types import CandidateHighlight, HighlightArchetype, WhisperWord
from .tnms_engine import GuardedTNMSDiversityEngine

LLMFn = Callable[[str], str]

CONTENT_TYPE_PROMPT = """Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low (mostly filler/chit-chat), medium, or high (dense info/stories).
Respond with JSON only: {"content_type": "...", "density": "..."}"""

VIRALITY_CRITERIA = """
Virality signals to prioritize (ranked by impact):
1. HOOK MOMENTS — statements that create immediate curiosity ("The secret is...", "Nobody talks about...")
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reactions
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements that trigger agree/disagree
4. REVELATION MOMENTS — surprising facts, stats, or confessions that reframe how the viewer thinks
5. CONFLICT/TENSION — disagreement, pushback, or a problem being confronted head-on
6. QUOTABLE ONE-LINERS — a sentence that works as a standalone quote card
7. STORY PEAKS — the climax or twist of an anecdote; the payoff moment
8. PRACTICAL VALUE — a concrete tip, hack, or insight the viewer can immediately apply
"""

ARCHETYPE_SPECIFICATION = """
Mandatory Diversity Archetypes (You MUST assign exactly ONE archetype to each highlight):
1. SATIRE_COMMERCIAL: Parody ad, dry sarcastic commentary, faux commercial, deadpan irony.
2. DIALOGUE_BANTER: Witty insults, playful roast, rapid conversational ping-pong, chemistry.
3. ACTION_HEIST: High adrenaline, police chase, combat, tense heist, mission climax.
4. LORE_BACKSTORY: Character origin secret, philosophical breakdown, deep easter-egg insight.
5. STUNT_FAIL: Unexpected blooper, sudden physics catastrophe, shock reaction, chaotic moment.

Ensure highlights span across different archetypes to provide maximum viewing variety.
"""

HIGHLIGHT_SYSTEM_PROMPT = """You are an elite short-form video architect who understands what hooks viewers and keeps retention high.

{virality_criteria}

{archetype_specification}

Content type: {content_type} | Density: {density}

Your task: identify the most viral-worthy highlights from the transcript.

Rules:
- Every highlight must open with a strong HOOK — a line that grabs attention within the first 3 seconds
- Duration sweet spot: 25-75 seconds. Go shorter (20-24s) only for a perfect standalone one-liner
- Never cut mid-sentence or mid-thought — each clip must feel complete and self-contained
- Clips must NOT overlap with each other
- Classify each highlight into the specified Archetypes
- Score 0-100 on viral potential (not general quality)
- {num_clips_instruction}
- For each highlight, identify the single best "hook_sentence" — opening line that makes someone stop scrolling
- Explain in one sentence why this clip is viral ("virality_reason")

Respond ONLY with valid JSON (no markdown fences, no explanation):
{{"highlights":[{{"title":"string","start_time":float,"end_time":float,"score":int,"archetype":"SATIRE_COMMERCIAL|DIALOGUE_BANTER|ACTION_HEIST|LORE_BACKSTORY|STUNT_FAIL","hook_sentence":"string","virality_reason":"string"}}]}}"""

CHUNK_SIZE_SECONDS = 1200
LONG_VIDEO_THRESHOLD = 1800
CHUNK_OVERLAP_SECONDS = 60
GPT_CALL_TIMEOUT_SECONDS = 300
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
    """Strip markdown code fences and loosely parse JSON."""
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
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sanitize_highlights(raw_highlights: object, duration: float) -> List[Dict]:
    """Normalize model output into expected shape; validate archetypes and bounds."""
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

        archetype = HighlightArchetype.from_string(str(item.get("archetype", "")))

        cleaned.append(
            {
                "title": str(item.get("title") or "Untitled Highlight").strip(),
                "start_time": start,
                "end_time": end,
                "score": max(0, min(100, _coerce_int(item.get("score"), default=0))),
                "archetype": archetype.value,
                "hook_sentence": str(item.get("hook_sentence") or "").strip(),
                "virality_reason": str(item.get("virality_reason") or "").strip(),
            }
        )

    return cleaned


def detect_content_type(transcript: Dict, llm_fn: LLMFn = call_muapi_llm) -> Dict[str, str]:
    """Classify video content type and density from opening segments."""
    segments = transcript.get("segments", [])
    sample = " ".join(s["text"] for s in segments[:25])[:3000]
    prompt = f"{CONTENT_TYPE_PROMPT}\n\nTranscript sample:\n{sample}"
    try:
        raw = llm_fn(prompt)
        return _parse_json_loose(raw)
    except Exception:
        return {"content_type": "other", "density": "medium"}


def build_transcript_text(transcript: Dict) -> str:
    """Format segments into timestamped transcript text."""
    segments = transcript.get("segments", [])
    return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segments)


def chunk_transcript(transcript: Dict) -> List[Dict]:
    """Split long transcripts into overlapping chunks for LLM processing."""
    segments = transcript.get("segments", [])
    duration = transcript.get("duration", segments[-1]["end"] if segments else 0)
    chunks = []
    start = 0
    while start < duration:
        end = min(start + CHUNK_SIZE_SECONDS, duration)
        chunk_segs = [
            s for s in segments
            if s["start"] >= start and s["end"] <= end + CHUNK_OVERLAP_SECONDS
        ]
        if chunk_segs:
            chunk = dict(transcript)
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
) -> Dict:
    """Call LLM to extract candidate highlights using virality and archetype criteria."""
    target = max(num_clips * 2, 5)
    natural_max = max(2 if is_chunk else 3, int(duration / 90))
    min_clips = min(target, natural_max, 8)
    system = HIGHLIGHT_SYSTEM_PROMPT.format(
        virality_criteria=VIRALITY_CRITERIA,
        archetype_specification=ARCHETYPE_SPECIFICATION,
        content_type=content_info.get("content_type", "other"),
        density=content_info.get("density", "medium"),
        num_clips_instruction=f"Generate at least {min_clips} highlights spanning different archetypes",
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
            prompt = (
                base_prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON with a top-level 'highlights' array."
                + " Each item must include: title, start_time, end_time, score, archetype, hook_sentence, virality_reason."
                + " No markdown fences, no commentary."
            )

    raise RuntimeError(
        f"Highlight generator produced invalid output after {MAX_HIGHLIGHT_API_ATTEMPTS} attempts: {last_error}"
    )


def _extract_whisper_words(transcript: Dict) -> List[WhisperWord]:
    """Extract ordered WhisperWord objects from transcript structured payload."""
    words: List[WhisperWord] = []
    raw_words = transcript.get("words", [])
    if raw_words and isinstance(raw_words, list):
        for w in raw_words:
            if isinstance(w, dict) and "word" in w and "start" in w and "end" in w:
                words.append(
                    WhisperWord(
                        word=str(w.get("word", "")),
                        start=float(w.get("start", 0.0)),
                        end=float(w.get("end", 0.0)),
                        probability=float(w.get("probability", 1.0)),
                    )
                )
    if not words:
        for seg in transcript.get("segments", []):
            for w in seg.get("words", []):
                if isinstance(w, dict) and "word" in w and "start" in w and "end" in w:
                    words.append(
                        WhisperWord(
                            word=str(w.get("word", "")),
                            start=float(w.get("start", 0.0)),
                            end=float(w.get("end", 0.0)),
                            probability=float(w.get("probability", 1.0)),
                        )
                    )
    return words


def dedupe_highlights(
    highlights: List[Dict],
    target_count: Optional[int] = None,
    guard_band: float = 45.0,
    historical_intervals: Optional[List[Tuple[float, float]]] = None,
) -> List[Dict]:
    """Filter highlights with strict Guarded T-NMS and archetype quotas.

    Args:
        highlights: List of raw highlight dictionaries.
        target_count: Number of desired highlights.
        guard_band: Minimum temporal clearance buffer in seconds.
        historical_intervals: Prior intervals to exclude.

    Returns:
        List of deduplicated, diverse highlight dictionaries.
    """
    if not highlights:
        return []

    cands = [
        CandidateHighlight(
            title=str(h.get("title", "Untitled")),
            raw_start=float(h.get("start_time", 0.0)),
            raw_end=float(h.get("end_time", 0.0)),
            score=int(h.get("score", 0)),
            archetype=HighlightArchetype.from_string(str(h.get("archetype", ""))),
            hook_sentence=str(h.get("hook_sentence", "")),
            virality_reason=str(h.get("virality_reason", "")),
        )
        for h in highlights
    ]

    target = target_count or len(cands)
    engine = GuardedTNMSDiversityEngine(guard_band=guard_band)
    selected = engine.select_diverse_highlights(
        cands, target_count=target, historical_intervals=historical_intervals
    )

    return [
        {
            "title": c.title,
            "start_time": c.raw_start,
            "end_time": c.raw_end,
            "score": c.score,
            "archetype": c.archetype.value,
            "hook_sentence": c.hook_sentence,
            "virality_reason": c.virality_reason,
        }
        for c in selected
    ]


def get_highlights(
    transcript: Dict,
    num_clips: int = 3,
    llm_fn: Optional[LLMFn] = None,
    video_id: Optional[str] = None,
    guard_band: float = 45.0,
) -> Dict:
    """Extract, acoustically snap, and diversely select top video highlights.

    Args:
        transcript: Whisper transcript dictionary.
        num_clips: Target count of shorts.
        llm_fn: Pluggable LLM invocation callable.
        video_id: Optional video identifier for stateful cross-run deduplication.
        guard_band: Minimum temporal separation between clips in seconds.

    Returns:
        Dictionary containing non-overlapping, archetype-diverse highlights.
    """
    llm_fn = llm_fn or call_muapi_llm
    duration = transcript.get("duration", 0)
    content_info = detect_content_type(transcript, llm_fn=llm_fn)
    print(f"[highlights] content={content_info.get('content_type')} density={content_info.get('density')} duration={duration:.0f}s", flush=True)

    raw_candidates: List[Dict] = []
    if duration >= LONG_VIDEO_THRESHOLD:
        chunks = chunk_transcript(transcript)
        print(f"[highlights] long video — splitting into {len(chunks)} chunks", flush=True)
        for i, chunk in enumerate(chunks):
            offset = chunk.get("_offset", 0)
            text = build_transcript_text(chunk)
            print(f"[highlights] chunk {i + 1}/{len(chunks)} (offset {offset:.0f}s)", flush=True)
            result = call_highlight_api(text, content_info, chunk["duration"], num_clips=num_clips, is_chunk=True, llm_fn=llm_fn)
            for h in result.get("highlights", []):
                h["start_time"] = float(h["start_time"]) + offset
                h["end_time"] = float(h["end_time"]) + offset
                raw_candidates.append(h)
    else:
        text = build_transcript_text(transcript)
        result = call_highlight_api(text, content_info, duration, num_clips=num_clips, llm_fn=llm_fn)
        raw_candidates = result.get("highlights", [])

    words = _extract_whisper_words(transcript)
    snapper = AudioBoundarySnapper(words)

    candidate_objects: List[CandidateHighlight] = []
    for h in raw_candidates:
        cand = CandidateHighlight(
            title=h["title"],
            raw_start=float(h["start_time"]),
            raw_end=float(h["end_time"]),
            score=int(h["score"]),
            archetype=HighlightArchetype.from_string(h.get("archetype", "")),
            hook_sentence=h.get("hook_sentence", ""),
            virality_reason=h.get("virality_reason", ""),
        )
        if words:
            cand = snapper.snap_highlight(cand)
        candidate_objects.append(cand)

    registry = ClipRegistry()
    hist_intervals = registry.get_existing_intervals(video_id, guard_band=guard_band) if video_id else []

    engine = GuardedTNMSDiversityEngine(guard_band=guard_band)
    selected = engine.select_diverse_highlights(
        candidate_objects, target_count=num_clips, historical_intervals=hist_intervals
    )

    final_highlights = [
        {
            "title": c.title,
            "start_time": c.snapped_start if c.is_snapped else c.raw_start,
            "end_time": c.snapped_end if c.is_snapped else c.raw_end,
            "score": c.score,
            "archetype": c.archetype.value,
            "hook_sentence": c.hook_sentence,
            "virality_reason": c.virality_reason,
        }
        for c in selected
    ]

    return {"highlights": final_highlights}
