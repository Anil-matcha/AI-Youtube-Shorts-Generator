"""End-to-end orchestrator for video shorts generation.

Two execution modes:
- mode="local": yt-dlp + faster-whisper + OpenAI/Gemini + Intel Arc QSV / FFmpeg hardware pipeline.
- mode="api": MuAPI cloud proxy.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional

from .clipper import crop_highlights
from .downloader import download_youtube
from .highlights import call_muapi_llm, get_highlights
from .transcriber import transcribe


def _extract_video_id(url_or_path: str) -> str:
    """Extract YouTube video identifier or fallback to path stem.

    Args:
        url_or_path: YouTube URL string or filesystem path.

    Returns:
        Extracted identifier string.
    """
    m = re.search(r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url_or_path)
    if m:
        return m.group(1)
    return Path(url_or_path).stem


def _run_local(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    framing: str = "split_stack",
    burn_subtitles: bool = True,
    master_audio: bool = True,
    video_id: Optional[str] = None,
    guard_band: float = 45.0,
    resolution: str = "4k",
) -> Dict:
    """Execute full local processing pipeline on the current machine.

    Args:
        youtube_url: YouTube URL or local video path.
        num_clips: Number of top highlights to render.
        aspect_ratio: Target aspect ratio string.
        download_format: Video quality shorthand.
        language: Language code hint for Whisper.
        framing: Framing strategy (split_stack, left_focus, right_focus, smart_focus, center).
        burn_subtitles: Whether to burn dynamic karaoke subtitles.
        master_audio: Whether to apply EBU R128 audio mastering.
        video_id: Optional video identifier for persistent exclusion.
        guard_band: Minimum temporal separation between clips in seconds.
        resolution: Output resolution profile ('4k' for 2160x3840 or '1080p' for 1080x1920).

    Returns:
        Structured pipeline result dictionary.
    """
    from .local.clipper import crop_highlights_local
    from .local.downloader import download_youtube_local
    from .local.llm import call_local_llm
    from .local.transcriber import transcribe_local

    vid = video_id or _extract_video_id(youtube_url)
    source_path = download_youtube_local(youtube_url, fmt=download_format)

    transcript = transcribe_local(source_path, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(
        transcript,
        num_clips=num_clips,
        llm_fn=call_local_llm,
        video_id=vid,
        guard_band=guard_band
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline/local] cropping {len(top)} of {len(all_highlights)} candidates [{framing}] ({resolution})", flush=True)

    shorts = crop_highlights_local(
        source_path,
        top,
        aspect_ratio=aspect_ratio,
        framing=framing,
        burn_subtitles=burn_subtitles,
        master_audio=master_audio,
        video_id=vid,
        resolution=resolution,
        transcript_segments=transcript.get("segments"),
        auto_framing=(framing in ("auto", "smart", "split_stack")),
        auto_zoom=True,
    )

    return {
        "mode": "local",
        "video_id": vid,
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
    }


def _run_api(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
) -> Dict:
    """Execute pipeline via remote MuAPI cloud endpoints.

    Args:
        youtube_url: YouTube video URL.
        num_clips: Target count of shorts.
        aspect_ratio: Aspect ratio specification.
        download_format: Target format string.
        language: Language code hint.

    Returns:
        Structured result dictionary.
    """
    source_url = download_youtube(youtube_url, fmt=download_format)

    transcript = transcribe(source_url, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_muapi_llm)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights(source_url, top, aspect_ratio=aspect_ratio)

    return {
        "mode": "api",
        "source_video_url": source_url,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
    }


def generate_shorts(
    youtube_url: str,
    num_clips: int = 3,
    aspect_ratio: str = "9:16",
    download_format: str = "2160",
    language: Optional[str] = None,
    mode: str = "local",
    framing: str = "split_stack",
    burn_subtitles: bool = True,
    master_audio: bool = True,
    video_id: Optional[str] = None,
    guard_band: float = 45.0,
    resolution: str = "4k",
) -> Dict:
    """Execute end-to-end shorts generation workflow.

    Args:
        youtube_url: Source YouTube URL or local file path.
        num_clips: Number of candidate shorts to produce.
        aspect_ratio: Aspect ratio ('9:16', '1:1').
        download_format: Ingest resolution ('720', '1080', '2160', '4k').
        language: Language hint code.
        mode: Execution backend ('local' or 'api').
        framing: Layout framing strategy.
        burn_subtitles: Whether to burn dynamic karaoke subtitles.
        master_audio: Whether to apply broadcast loudness normalization.
        video_id: Optional video identifier for persistent exclusion.
        guard_band: Minimum temporal separation between clips in seconds.
        resolution: Output resolution profile ('4k' for 2160x3840 or '1080p' for 1080x1920).

    Returns:
        Dictionary containing transcript, ranked highlights, and rendered shorts metadata.
    """
    mode = (mode or "local").lower()
    if mode == "local":
        return _run_local(
            youtube_url,
            num_clips,
            aspect_ratio,
            download_format,
            language,
            framing=framing,
            burn_subtitles=burn_subtitles,
            master_audio=master_audio,
            video_id=video_id,
            guard_band=guard_band,
            resolution=resolution,
        )
    if mode == "api":
        return _run_api(youtube_url, num_clips, aspect_ratio, download_format, language)
    raise ValueError(f"Unknown mode: {mode!r}. Use 'api' or 'local'.")
