"""End-to-end orchestrator.

Two modes:
  * mode="api"   (default) — MuAPI does download / transcribe / LLM / autocrop.
                              Fast, no local deps, pay-per-call.
  * mode="local"            — yt-dlp + faster-whisper + OpenAI / Gemini / Ollama + ffmpeg/opencv.
                              Self-hosted, LLM_PROVIDER selects OpenAI, Gemini, or Ollama.
"""
import os
from typing import Dict, List, Optional

from .clipper import crop_highlights
from .downloader import download_youtube
from .highlights import call_muapi_llm, get_highlights
from .metadata import generate_all_metadata, write_metadata_file
from .transcriber import transcribe


def _run_local(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    crop_mode: str = "face",
    captions: bool = False,
    clip_length: Optional[int] = None,
    generate_metadata: bool = False,
) -> Dict:
    from .local.clipper import crop_highlights_local
    from .local.downloader import download_youtube_local
    from .local.llm import call_local_llm
    from .local.transcriber import transcribe_local

    source_path = download_youtube_local(youtube_url, fmt=download_format)

    transcript = transcribe_local(source_path, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(transcript, num_clips=num_clips, clip_length=clip_length, llm_fn=call_local_llm)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline/local] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights_local(
        source_path, top, aspect_ratio=aspect_ratio, crop_mode=crop_mode,
        captions=captions, transcript_segments=transcript.get("segments"),
    )

    if generate_metadata:
        shorts = generate_all_metadata(
            shorts, transcript.get("segments", []), llm_fn=call_local_llm
        )
        meta_path = os.path.join(
            os.path.dirname(source_path) if os.path.dirname(source_path) else ".",
            "shorts_metadata.txt"
        )
        write_metadata_file(shorts, meta_path, source_url=youtube_url)

    return {
        "mode": "local",
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "metadata_file": meta_path if generate_metadata else None,
    }


def _run_api(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    clip_length: Optional[int] = None,
    generate_metadata: bool = False,
) -> Dict:
    source_url = download_youtube(youtube_url, fmt=download_format)

    transcript = transcribe(source_url, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(transcript, num_clips=num_clips, clip_length=clip_length, llm_fn=call_muapi_llm)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights(source_url, top, aspect_ratio=aspect_ratio)

    if generate_metadata:
        shorts = generate_all_metadata(
            shorts, transcript.get("segments", []), llm_fn=call_muapi_llm
        )
        meta_path = os.path.join(
            os.path.dirname(source_url) if os.path.dirname(source_url) else ".",
            "shorts_metadata.txt"
        )
        write_metadata_file(shorts, meta_path, source_url=youtube_url)

    return {
        "mode": "api",
        "source_video_url": source_url,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "metadata_file": meta_path if generate_metadata else None,
    }


def generate_shorts(
    youtube_url: str,
    num_clips: int = 3,
    clip_length: Optional[int] = None,
    aspect_ratio: str = "9:16",
    download_format: str = "720",
    language: Optional[str] = None,
    mode: str = "api",
    crop_mode: str = "face",
    captions: bool = False,
    generate_metadata: bool = False,
) -> Dict:
    """Run the full pipeline and return a structured result.

    Args:
        youtube_url: source URL.
        num_clips: how many shorts to render.
        clip_length: target clip length in seconds (±5s tolerance). Default 45.
        aspect_ratio: e.g. "9:16", "1:1".
        download_format: source resolution ("360" / "480" / "720" / "1080").
        language: ISO-639-1 to force Whisper language detection.
        mode: "api" (default, MuAPI) or "local" (yt-dlp + faster-whisper +
            OpenAI or Gemini + ffmpeg).
        crop_mode: "face" (default) or "shot". Only used in local mode.
            "shot" detects shot boundaries and locks the crop center per shot
            using maximum action area (optical flow). Prevents mid-shot drift.
        captions: Burn transcript captions into the output clips. Default False.
            Only supported in local mode.
        generate_metadata: Generate YouTube + TikTok titles, descriptions, and
            hashtags for each short. Default False.

    Returns:
        {
          "mode": "api" | "local",
          "source_video_url": str,   # hosted URL (api) or local path (local)
          "transcript": {...},
          "highlights": [...],       # all candidates ranked
          "shorts": [...],           # top `num_clips` with clip_url / local path
        }
    """
    mode = (mode or "api").lower()
    if mode == "local":
        return _run_local(youtube_url, num_clips, aspect_ratio, download_format, language, crop_mode=crop_mode, captions=captions, clip_length=clip_length, generate_metadata=generate_metadata)
    if mode == "api":
        return _run_api(youtube_url, num_clips, aspect_ratio, download_format, language, clip_length=clip_length, generate_metadata=generate_metadata)
    raise ValueError(f"Unknown mode: {mode!r}. Use 'api' or 'local'.")
