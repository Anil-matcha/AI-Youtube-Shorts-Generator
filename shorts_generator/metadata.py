"""Generate platform-specific titles and descriptions for each short.

Uses the same LLM backend as highlight ranking (OpenAI / Gemini / Ollama in local
mode, MuAPI in API mode) to produce:
  - YouTube title + description
  - TikTok caption + hashtags

The prompt includes the short's transcript text, hook sentence, and virality
reason so the metadata is grounded in the actual content.
"""
import json
import re
from typing import Callable, Dict, List, Optional

from .config import CLIP_LENGTH
from .highlights import LLMFn, call_muapi_llm


METADATA_SYSTEM_PROMPT = """You are a viral social-media copywriter who writes scroll-stopping titles and descriptions for short-form video clips.

Given a short video clip's transcript, hook, and virality reason, write:
1. A YouTube Shorts title (max 60 chars, punchy, includes keywords)
2. A YouTube Shorts description (2-3 sentences, engaging, includes relevant hashtags)
3. A TikTok caption (max 100 chars, trendy, emoji-friendly)
4. TikTok hashtags (5-8 hashtags, mix of broad and niche)

Rules:
- Titles must be attention-grabbing and accurate to the content
- Descriptions should tease the content without giving everything away
- TikTok captions should feel native to the platform (casual, emoji, trends)
- Hashtags must be relevant to the actual content, not generic spam
- NEVER use clickbait that misrepresents the content

Respond ONLY with valid JSON (no markdown, no explanation):
{"youtube_title":"string","youtube_description":"string","tiktok_caption":"string","tiktok_hashtags":"#tag1 #tag2 ..."}"""


def _parse_json_loose(raw: str) -> Dict:
    """Strip markdown fences and parse JSON."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        raise


def generate_short_metadata(
    highlight: Dict,
    transcript_segments: List[Dict],
    llm_fn: Optional[LLMFn] = None,
) -> Dict:
    """Generate YouTube + TikTok metadata for a single short.

    Args:
        highlight: dict with title, start_time, end_time, hook_sentence, virality_reason
        transcript_segments: list of {start, end, text} for the full video
        llm_fn: LLM callable (defaults to MuAPI gpt-5-mini)

    Returns:
        {
            "youtube_title": str,
            "youtube_description": str,
            "tiktok_caption": str,
            "tiktok_hashtags": str,
        }
    """
    llm_fn = llm_fn or call_muapi_llm

    start = float(highlight.get("start_time", 0))
    end = float(highlight.get("end_time", 0))

    # Extract transcript text within the clip's time window
    clip_texts = [
        s["text"] for s in transcript_segments
        if float(s.get("start", 0)) >= start and float(s.get("end", 0)) <= end
    ]
    clip_transcript = " ".join(clip_texts).strip()
    if not clip_transcript:
        # Fallback: grab segments that overlap the window
        clip_texts = [
            s["text"] for s in transcript_segments
            if float(s.get("start", 0)) < end and float(s.get("end", 0)) > start
        ]
        clip_transcript = " ".join(clip_texts).strip()

    hook = highlight.get("hook_sentence", "")
    reason = highlight.get("virality_reason", "")
    title = highlight.get("title", "")

    prompt = (
        f"{METADATA_SYSTEM_PROMPT}\n\n"
        f"Clip title: {title}\n"
        f"Hook: {hook}\n"
        f"Why it's viral: {reason}\n"
        f"Transcript: {clip_transcript}\n\n"
        f"Generate metadata:"
    )

    raw = llm_fn(prompt)
    try:
        parsed = _parse_json_loose(raw)
        return {
            "youtube_title": str(parsed.get("youtube_title", "")).strip(),
            "youtube_description": str(parsed.get("youtube_description", "")).strip(),
            "tiktok_caption": str(parsed.get("tiktok_caption", "")).strip(),
            "tiktok_hashtags": str(parsed.get("tiktok_hashtags", "")).strip(),
        }
    except Exception as e:
        print(f"[metadata] failed to parse LLM response: {e}", flush=True)
        return {
            "youtube_title": title,
            "youtube_description": f"{hook}\n\n{reason}",
            "tiktok_caption": hook,
            "tiktok_hashtags": "#shorts #viral #trending",
        }


def generate_all_metadata(
    highlights: List[Dict],
    transcript_segments: List[Dict],
    llm_fn: Optional[LLMFn] = None,
) -> List[Dict]:
    """Generate metadata for every highlight and attach it back.

    Returns a new list of highlight dicts with added keys:
        youtube_title, youtube_description, tiktok_caption, tiktok_hashtags
    """
    results = []
    for i, h in enumerate(highlights, 1):
        print(f"[metadata] {i}/{len(highlights)}: {h.get('title', '(untitled)')}", flush=True)
        meta = generate_short_metadata(h, transcript_segments, llm_fn=llm_fn)
        results.append({**h, **meta})
    return results


def write_metadata_file(
    shorts: List[Dict],
    out_path: str,
    source_url: str = "",
) -> str:
    """Write a human-readable metadata file alongside the shorts.

    Args:
        shorts: list of short dicts with metadata keys
        out_path: path to write the file (e.g. output/shorts_metadata.txt)
        source_url: original source video URL for reference

    Returns:
        The written file path.
    """
    lines = []
    lines.append("=" * 72)
    lines.append("SHORT-FORM VIDEO METADATA")
    lines.append("=" * 72)
    if source_url:
        lines.append(f"Source: {source_url}")
    lines.append("")

    for i, s in enumerate(shorts, 1):
        lines.append("-" * 72)
        lines.append(f"SHORT #{i}")
        lines.append("-" * 72)
        lines.append(f"File: {s.get('clip_url', 'N/A')}")
        lines.append(f"Time: {s.get('start_time', 0):.1f}s → {s.get('end_time', 0):.1f}s")
        lines.append(f"Score: {s.get('score', 'N/A')}")
        lines.append("")
        lines.append("YOUTUBE")
        lines.append(f"  Title:       {s.get('youtube_title', 'N/A')}")
        lines.append(f"  Description: {s.get('youtube_description', 'N/A')}")
        lines.append("")
        lines.append("TIKTOK")
        lines.append(f"  Caption:  {s.get('tiktok_caption', 'N/A')}")
        lines.append(f"  Hashtags: {s.get('tiktok_hashtags', 'N/A')}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("END")
    lines.append("=" * 72)

    content = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[metadata] wrote metadata file: {out_path}", flush=True)
    return out_path
