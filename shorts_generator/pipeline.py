"""End-to-end orchestrator.

Two modes:
  * mode="api"   (default) — MuAPI does download / transcribe / LLM / autocrop.
                              Fast, no local deps, pay-per-call.
  * mode="local"            — yt-dlp + faster-whisper + OpenAI or Gemini + ffmpeg/opencv.
                              Self-hosted, LLM_PROVIDER selects OpenAI or Gemini.
"""

from typing import Callable, Dict, List, Optional

ProgressFn = Optional[Callable[[str, str], None]]

from .clipper import crop_highlights
from .config import (
    current_api_key,
    current_llm_provider,
    LOCAL_BURN_CAPTIONS,
    LOCAL_HEURISTIC_FALLBACK,
    runtime_credentials,
)
from .downloader import download_youtube
from .highlights import call_muapi_llm, get_highlights
from .transcriber import transcribe


def _emit(progress: ProgressFn, stage: str, message: str) -> None:
    print(f"[{stage}] {message}", flush=True)
    if progress:
        progress(stage, message)


def _run_local(
    youtube_url: str,
    num_clips: int,
    aspect_ratio: str,
    download_format: str,
    language: Optional[str],
    progress: ProgressFn = None,
    output_dir: Optional[str] = None,
    caption_style: str = "bold",
    remove_silence: bool = False,
    normalize_audio: bool = False,
    denoise_audio: bool = False,
    remove_filler_words: bool = False,
    caption_position: str = "bottom",
    caption_font: str = "Arial",
    caption_size: int = 0,
    caption_color: Optional[str] = None,
    focus: str = "balanced",
    background_music: Optional[str] = None,
    watermark: Optional[str] = None,
    auto_reframe: bool = True,
    crop_position: float = 0.5,
    fit_mode: str = "crop",
    zoom: float = 1.0,
    intro: Optional[str] = None,
    outro: Optional[str] = None,
    jump_cuts: bool = False,
    layout: str = "single",
    whisper_model: Optional[str] = None,
    whisper_device: Optional[str] = None,
    output_height: int = 1920,
    llm_provider: Optional[str] = None,
) -> Dict:
    from .local.clipper import crop_highlights_local
    from .local.downloader import download_youtube_local
    from .local.llm import call_local_llm
    from .local.fallback import rank_highlights_offline
    from .local.transcriber import transcribe_local
    from .local.visual import analyze_video

    _emit(progress, "download", "Fetching source video...")
    source_path = download_youtube_local(
        youtube_url,
        fmt=download_format,
        out_dir=output_dir,
    )

    _emit(progress, "analyze", "Scanning scenes, faces, and visual changes...")
    try:
        visual_events = analyze_video(source_path)
    except Exception as exc:
        print(f"[visual/local] analysis skipped: {exc}", flush=True)
        visual_events = []

    _emit(progress, "transcribe", "Transcribing with Whisper...")
    transcript = transcribe_local(
        source_path,
        language=language,
        cache_dir=output_dir,
        model_name=whisper_model,
        device=whisper_device,
    )
    transcript["visual_events"] = visual_events
    if not transcript["segments"]:
        raise RuntimeError("Whisper produced no segments. The video may have no detectable speech.")

    _emit(progress, "rank", "Ranking viral highlights...")
    provider = str(llm_provider or current_llm_provider() or "openai").strip().lower()
    llm_configured = (provider == "openai" and bool(current_api_key("openai"))) or (
        provider == "gemini" and bool(current_api_key("gemini"))
    )
    if LOCAL_HEURISTIC_FALLBACK and not llm_configured:
        _emit(
            progress,
            "rank",
            "No OpenAI/Gemini key configured; using offline transcript ranking.",
        )
        highlights_result = {"highlights": rank_highlights_offline(transcript, num_clips=num_clips)}
    else:
        # Keep the dispatcher aligned with the explicit function argument even
        # when callers invoke ``generate_shorts`` outside the web worker.
        with runtime_credentials(llm_provider=provider):
            highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_local_llm, focus=focus)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    _emit(progress, "crop", f"Cropping {len(top)} of {len(all_highlights)} candidates...")

    shorts = crop_highlights_local(
        source_path,
        top,
        aspect_ratio=aspect_ratio,
        out_dir=output_dir,
        caption_segments=transcript.get("segments") or [],
        burn_captions=LOCAL_BURN_CAPTIONS,
        caption_style=caption_style,
        remove_silence=remove_silence,
        normalize_audio=normalize_audio,
        denoise_audio=denoise_audio,
        remove_filler_words=remove_filler_words,
        caption_position=caption_position,
        caption_font=caption_font,
        caption_size=caption_size,
        caption_color=caption_color,
        background_music=background_music,
        watermark=watermark,
        auto_reframe=auto_reframe,
        crop_position=crop_position,
        fit_mode=fit_mode,
        zoom=zoom,
        intro=intro,
        outro=outro,
        jump_cuts=jump_cuts,
        layout=layout,
        output_height=output_height,
    )

    return {
        "mode": "local",
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
    progress: ProgressFn = None,
    focus: str = "balanced",
) -> Dict:
    _emit(progress, "download", "Fetching source video via MuAPI...")
    source_url = download_youtube(youtube_url, fmt=download_format)

    _emit(progress, "transcribe", "Transcribing with Whisper...")
    transcript = transcribe(source_url, language=language)
    if not transcript["segments"]:
        raise RuntimeError("Whisper produced no segments. The video may have no detectable speech.")

    _emit(progress, "rank", "Ranking viral highlights...")
    highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_muapi_llm, focus=focus)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    _emit(progress, "crop", f"Cropping {len(top)} of {len(all_highlights)} candidates...")

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
    download_format: str = "720",
    language: Optional[str] = None,
    mode: str = "api",
    progress: ProgressFn = None,
    output_dir: Optional[str] = None,
    caption_style: str = "bold",
    remove_silence: bool = False,
    normalize_audio: bool = False,
    denoise_audio: bool = False,
    remove_filler_words: bool = False,
    caption_position: str = "bottom",
    caption_font: str = "Arial",
    caption_size: int = 0,
    caption_color: Optional[str] = None,
    focus: str = "balanced",
    background_music: Optional[str] = None,
    watermark: Optional[str] = None,
    auto_reframe: bool = True,
    crop_position: float = 0.5,
    fit_mode: str = "crop",
    zoom: float = 1.0,
    intro: Optional[str] = None,
    outro: Optional[str] = None,
    jump_cuts: bool = False,
    layout: str = "single",
    whisper_model: Optional[str] = None,
    whisper_device: Optional[str] = None,
    output_height: int = 1920,
    llm_provider: Optional[str] = None,
) -> Dict:
    """Run the full pipeline and return a structured result.

    Args:
        youtube_url: source URL.
        num_clips: how many shorts to render.
        aspect_ratio: e.g. "9:16", "1:1".
        download_format: source resolution ("360" / "480" / "720" / "1080").
        language: ISO-639-1 to force Whisper language detection.
        mode: "api" (default, MuAPI) or "local" (yt-dlp + faster-whisper +
            OpenAI or Gemini + ffmpeg).
        output_dir: optional per-job directory for local downloads, transcript
            caches, and rendered clips. Defaults to ``LOCAL_OUTPUT_DIR``.
        caption_style: local caption preset (clean, bold, boxed, karaoke).
        remove_silence: trim long silent tails from local clip audio.
        normalize_audio: loudness-normalize local clip audio.
        remove_filler_words: remove common filler words from burned captions.
        focus: highlight selection focus (balanced, educational, funny, story,
            controversial, or visual).
        background_music: optional local audio path mixed under local clips.
        watermark: optional local image path overlaid on local clips.
        auto_reframe: track faces automatically in local mode.
        crop_position: manual horizontal crop position from 0 (left) to 1 (right).
        fit_mode: crop to fill, or fit the full frame over a blurred background.
        zoom: fit-mode foreground scale from 0.5 (out) to 1.5 (in).
        output_height: local output canvas height in pixels (0 keeps 1920).
        llm_provider: local ranking provider (`openai` or `gemini`); defaults to
            ``LLM_PROVIDER`` from the environment.

    Returns:
        {
          "mode": "api" | "local",
          "source_video_url": str,   # hosted URL (api) or local path (local)
          "transcript": {...},
          "highlights": [...],       # all candidates ranked
          "shorts": [...],           # top `num_clips` with clip_url / local path
        }
    """
    try:
        num_clips = int(num_clips)
    except (TypeError, ValueError, OverflowError):
        num_clips = 3
    num_clips = max(1, min(12, num_clips))
    mode = str(mode or "api").strip().lower()
    if mode == "local":
        return _run_local(
            youtube_url,
            num_clips,
            aspect_ratio,
            download_format,
            language,
            progress,
            output_dir,
            caption_style,
            remove_silence,
            normalize_audio,
            denoise_audio,
            remove_filler_words,
            caption_position,
            caption_font,
            caption_size,
            caption_color,
            focus,
            background_music,
            watermark,
            auto_reframe,
            crop_position,
            fit_mode,
            zoom,
            intro,
            outro,
            jump_cuts,
            layout,
            whisper_model,
            whisper_device,
            output_height,
            llm_provider,
        )
    if mode == "api":
        return _run_api(
            youtube_url,
            num_clips,
            aspect_ratio,
            download_format,
            language,
            progress,
            focus,
        )
    raise ValueError(f"Unknown mode: {mode!r}. Use 'api' or 'local'.")
