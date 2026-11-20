"""Local audio transcription via faster-whisper with word-level precision.

Transcribes audio/video files, captures microsecond word timestamps, and
caches results in both .json (structured metadata + words) and .srt formats.
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from ..config import LOCAL_OUTPUT_DIR, LOCAL_WHISPER_DEVICE, LOCAL_WHISPER_MODEL, RAW_CAPTIONS_DIR


def _transcript_json_cache_path(media_path: str) -> Path:
    """Return the structured .json cache path for a media file.

    Args:
        media_path: Path to source media.

    Returns:
        Path to JSON cache file.
    """
    cache_dir = Path(RAW_CAPTIONS_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / (Path(media_path).stem + ".json")


def _transcript_cache_path(media_path: str) -> Path:
    """Return the .srt cache path for a media file.

    Args:
        media_path: Path to source media.

    Returns:
        Path to SRT cache file.
    """
    cache_dir = Path(RAW_CAPTIONS_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / (Path(media_path).stem + ".srt")


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds into standard SRT timestamp format (HH:MM:SS,mmm).

    Args:
        seconds: Time in seconds.

    Returns:
        SRT formatted timestamp string.
    """
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_caches(media_path: str, transcript: Dict) -> tuple[Path, Path]:
    """Write transcript data to both JSON and SRT cache files.

    Args:
        media_path: Source media file path.
        transcript: Dictionary with duration, segments, and word details.

    Returns:
        Tuple of (json_cache_path, srt_cache_path).
    """
    json_path = _transcript_json_cache_path(media_path)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)

    srt_path = _transcript_cache_path(media_path)
    lines: List[str] = []
    for idx, seg in enumerate(transcript.get("segments", []), start=1):
        start = _format_srt_timestamp(float(seg["start"]))
        end = _format_srt_timestamp(float(seg["end"]))
        txt = str(seg.get("text", "")).strip().replace("\r", "").replace("\n", " ")
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(txt)
        lines.append("")

    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, srt_path


def _load_json_cache(cache_path: Path) -> Dict:
    """Load cached transcript from JSON format.

    Args:
        cache_path: Path to JSON cache file.

    Returns:
        Parsed transcript dictionary.
    """
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_device() -> str:
    """Determine whether CUDA GPU or CPU should be used for Whisper.

    Returns:
        Device string ('cuda' or 'cpu').
    """
    if LOCAL_WHISPER_DEVICE != "auto":
        return LOCAL_WHISPER_DEVICE
    try:
        import torch
        if torch.cuda.is_available():
            torch.zeros(1, device="cuda")
            return "cuda"
    except (ImportError, OSError, RuntimeError):
        pass
    return "cpu"


def transcribe_local(media_path: str, language: Optional[str] = None) -> Dict:
    """Run faster-whisper with word-level timestamps and disk caching.

    Args:
        media_path: Local media file to transcribe.
        language: Language code hint.

    Returns:
        Dictionary containing duration, segments, and detailed word timestamps.
    """
    json_path = _transcript_json_cache_path(media_path)
    if json_path.exists():
        source_mtime = os.path.getmtime(media_path)
        cache_mtime = json_path.stat().st_mtime
        if cache_mtime >= source_mtime:
            cached = _load_json_cache(json_path)
            if cached.get("segments") and cached.get("duration", 0.0) > 0.0:
                return cached

    from faster_whisper import WhisperModel
    from ..config import LOCAL_WHISPER_VAD_FILTER, LOCAL_WHISPER_VAD_PARAMETERS

    device = _resolve_device()
    compute_type = "float16" if device == "cuda" else "int8"
    model = WhisperModel(LOCAL_WHISPER_MODEL, device=device, compute_type=compute_type)

    transcribe_kwargs = {
        "audio": media_path,
        "language": language,
        "beam_size": 5,
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "vad_filter": bool(LOCAL_WHISPER_VAD_FILTER),
    }
    if LOCAL_WHISPER_VAD_FILTER and LOCAL_WHISPER_VAD_PARAMETERS:
        transcribe_kwargs["vad_parameters"] = LOCAL_WHISPER_VAD_PARAMETERS

    segments_iter, info = model.transcribe(**transcribe_kwargs)

    segments: List[Dict] = []
    all_words: List[Dict] = []

    for s in segments_iter:
        seg_words = []
        if s.words:
            for w in s.words:
                item = {
                    "word": (w.word or "").strip(),
                    "start": float(w.start),
                    "end": float(w.end),
                    "probability": float(getattr(w, "probability", 1.0)),
                }
                seg_words.append(item)
                all_words.append(item)

        segments.append({
            "start": float(s.start),
            "end": float(s.end),
            "text": (s.text or "").strip(),
            "words": seg_words,
        })

    duration = float(getattr(info, "duration", 0.0)) or (segments[-1]["end"] if segments else 0.0)
    transcript = {
        "duration": duration,
        "segments": segments,
        "words": all_words,
    }
    _write_caches(media_path, transcript)
    return transcript
