"""Local transcription via faster-whisper.

Reads a local media file and returns the same shape the highlight generator
expects: {duration, segments[start, end, text]}.
"""

import json
import math
import re
import hashlib
import threading
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Optional

from ..config import (
    LOCAL_AUTO_SELECT_WHISPER_MODEL,
    LOCAL_OUTPUT_DIR,
    LOCAL_WHISPER_DEVICE,
    LOCAL_WHISPER_MODEL,
    cancellation_requested,
)

_MODEL_LOCK = threading.Lock()


def _cuda_ready() -> bool:
    """Check CUDA through PyTorch or CTranslate2, whichever is installed."""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.zeros(1, device="cuda")
            return True
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        pass
    try:
        import ctranslate2  # type: ignore

        return int(ctranslate2.get_cuda_device_count()) > 0
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def _transcript_cache_path(
    media_path: str,
    cache_dir: Optional[str] = None,
    *,
    cache_key: Optional[str] = None,
) -> Path:
    """Return a collision-resistant .srt cache path for a media file.

    ``cache_key`` is the content/settings signature used by normal
    transcription.  Omitting it preserves the v0.9 stem-based helper for
    callers that only need a predictable legacy path.
    """
    target_dir = Path(cache_dir or LOCAL_OUTPUT_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(media_path).stem
    key = str(cache_key or "").strip()
    if key and re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
        stem = f"transcript_{key}"
    return target_dir / (stem + ".srt")


def _word_cache_path(
    media_path: str,
    cache_dir: Optional[str] = None,
    *,
    cache_key: Optional[str] = None,
) -> Path:
    return _transcript_cache_path(media_path, cache_dir=cache_dir, cache_key=cache_key).with_suffix(".words.json")


def _cache_metadata_path(
    media_path: str,
    cache_dir: Optional[str] = None,
    *,
    cache_key: Optional[str] = None,
) -> Path:
    return _transcript_cache_path(media_path, cache_dir=cache_dir, cache_key=cache_key).with_suffix(".meta.json")


def _cache_signature(media_path: str, language: Optional[str], model_name: str, device: str) -> str:
    """Fingerprint source bytes plus every input that changes Whisper output."""
    source_hash = hashlib.sha256()
    with Path(media_path).open("rb") as source:
        while True:
            if cancellation_requested():
                raise RuntimeError("Job cancelled")
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            source_hash.update(chunk)
    payload = f"{source_hash.hexdigest()}:{language or 'auto'}:{model_name}:{device}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_srt_timestamp(seconds: float) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError, OverflowError):
        value = 0.0
    if not math.isfinite(value):
        value = 0.0
    total_ms = max(0, int(round(value * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, millis = map(int, match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    return hours * 3600 + minutes * 60 + seconds + (millis / 1000.0)


def _write_srt_cache(
    media_path: str,
    transcript: Dict,
    cache_dir: Optional[str] = None,
    *,
    signature: Optional[str] = None,
    cache_key: Optional[str] = None,
) -> Path:
    cache_path = _transcript_cache_path(media_path, cache_dir=cache_dir, cache_key=cache_key)
    lines = []
    valid_segments = []
    raw_segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    segment_items = raw_segments if isinstance(raw_segments, (list, tuple)) else []
    for segment in segment_items:
        if not isinstance(segment, dict):
            continue
        try:
            start_value = float(segment.get("start"))
            end_value = float(segment.get("end"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(start_value) or not math.isfinite(end_value) or end_value <= start_value:
            continue
        text = str(segment.get("text", "")).strip().replace("\r", "").replace("\n", " ")
        if not text:
            continue
        valid_segments.append(segment)

    for idx, segment in enumerate(valid_segments, start=1):
        start = _format_srt_timestamp(segment.get("start"))
        end = _format_srt_timestamp(segment.get("end"))
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(str(segment.get("text", "")).strip().replace("\r", "").replace("\n", " "))
        lines.append("")

    cache_path.write_text("\n".join(lines), encoding="utf-8")
    words = [segment.get("words") for segment in valid_segments]
    _word_cache_path(media_path, cache_dir=cache_dir, cache_key=cache_key).write_text(
        json.dumps(words, ensure_ascii=False), encoding="utf-8"
    )
    if signature:
        _cache_metadata_path(media_path, cache_dir=cache_dir, cache_key=cache_key).write_text(
            json.dumps({"signature": signature, "version": 1}, ensure_ascii=False), encoding="utf-8"
        )
    return cache_path


def _load_srt_cache(cache_path: Path) -> Dict:
    content = cache_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return {"duration": 0.0, "segments": []}

    segments = []
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
        text = "\n".join(lines[1:]).strip()
        try:
            start = _parse_srt_timestamp(start_raw)
            end = _parse_srt_timestamp(end_raw)
        except ValueError:
            continue
        if end <= start or not text:
            continue
        segments.append({"start": start, "end": end, "text": text})

    duration = max((segment["end"] for segment in segments), default=0.0)
    return {"duration": duration, "segments": segments}


def _resolve_device(requested: Optional[str] = None) -> str:
    requested = str(requested or LOCAL_WHISPER_DEVICE).strip().lower()
    if requested not in {"auto", "cpu", "cuda", "mps", "directml", "rocm"}:
        raise ValueError("Whisper device must be auto, cpu, cuda, mps, directml, or rocm")
    if requested in {"mps", "directml", "rocm"}:
        raise RuntimeError(
            f"{requested.upper()} is detected as a host accelerator, but faster-whisper currently supports CPU/CUDA here; choose cpu or cuda."
        )
    if requested == "cuda":
        if not _cuda_ready():
            raise RuntimeError(
                "CUDA was selected, but no usable CUDA device was detected. Install a current NVIDIA driver or run install_gpu_windows.bat"
            )
        return "cuda"
    if requested != "auto":
        return requested
    if _cuda_ready():
        return "cuda"
    return "cpu"


def _resolve_model_name(requested: Optional[str], device: str) -> str:
    """Select a model conservatively from available accelerator memory."""
    selected = str(requested or LOCAL_WHISPER_MODEL).strip().lower() or "base"
    if selected not in {"auto", "tiny", "base", "small", "medium", "large-v3"}:
        raise ValueError("Whisper model must be tiny, base, small, medium, large-v3, or auto")
    if selected != "auto" and (requested is not None or not LOCAL_AUTO_SELECT_WHISPER_MODEL):
        return selected
    memory_gb = 0.0
    if device == "cuda":
        try:
            import torch  # type: ignore

            memory_gb = float(torch.cuda.get_device_properties(0).total_memory) / (1024**3)
        except Exception:
            memory_gb = 0.0
    if memory_gb >= 12:
        return "large-v3"
    if memory_gb >= 8:
        return "medium"
    if memory_gb >= 4:
        return "small"
    return "base" if device == "cpu" else "tiny"


@lru_cache(maxsize=3)
def _load_whisper_model(model_name: str, device: str):
    """Reuse loaded Whisper models across jobs in the same worker process."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is required for --mode local. Install it with:\n    pip install -r requirements-local.txt"
        ) from e
    compute_type = "float16" if device == "cuda" else "int8"
    with _MODEL_LOCK:
        return WhisperModel(model_name, device=device, compute_type=compute_type)


def transcribe_local(
    media_path: str,
    language: Optional[str] = None,
    cache_dir: Optional[str] = None,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict:
    """Run faster-whisper on a local file path, caching the result as .srt."""
    media_path = str(media_path) if media_path is not None else ""
    if cancel_check and cancel_check():
        raise RuntimeError("Job cancelled")
    if not media_path or not Path(media_path).is_file():
        raise RuntimeError(f"Local media file does not exist: {media_path}")
    selected_device = _resolve_device(device)
    selected_model = _resolve_model_name(model_name, selected_device)
    signature = _cache_signature(media_path, language, selected_model, selected_device)
    cache_key = signature[:32]
    cache_path = _transcript_cache_path(media_path, cache_dir=cache_dir, cache_key=cache_key)
    if cache_path.exists():
        cache_valid = False
        try:
            metadata = json.loads(
                _cache_metadata_path(media_path, cache_dir=cache_dir, cache_key=cache_key).read_text(encoding="utf-8")
            )
            cache_valid = isinstance(metadata, dict) and metadata.get("signature") == signature
        except (OSError, ValueError, TypeError):
            cache_valid = False
        if cache_valid:
            print(f"[transcribe/local] reusing cached transcript: {cache_path}", flush=True)
            try:
                cached = _load_srt_cache(cache_path)
            except (OSError, ValueError, TypeError):
                cached = {"duration": 0.0, "segments": []}
            words_path = _word_cache_path(media_path, cache_dir=cache_dir, cache_key=cache_key)
            if words_path.exists():
                try:
                    cached_words = json.loads(words_path.read_text(encoding="utf-8"))
                    if isinstance(cached_words, list):
                        for segment, words in zip(cached.get("segments", []), cached_words):
                            if isinstance(words, list):
                                segment["words"] = [word for word in words if isinstance(word, dict)]
                except (OSError, ValueError, TypeError):
                    pass
            # Treat empty cache as invalid (likely from a failed/partial run) — delete and re-transcribe
            if not cached["segments"] or cached["duration"] <= 0.0:
                print(f"[transcribe/local] cache is empty/invalid, deleting: {cache_path}", flush=True)
                cache_path.unlink(missing_ok=True)
                _cache_metadata_path(media_path, cache_dir=cache_dir, cache_key=cache_key).unlink(missing_ok=True)
            else:
                print(
                    f"[transcribe/local] {len(cached['segments'])} cached segments, {cached['duration']:.0f}s of audio",
                    flush=True,
                )
                return cached

    print(f"[transcribe/local] faster-whisper model={selected_model} device={selected_device}", flush=True)

    from ..config import LOCAL_WHISPER_VAD_FILTER, LOCAL_WHISPER_VAD_PARAMETERS

    if cancellation_requested() or (cancel_check and cancel_check()):
        raise RuntimeError("Job cancelled")
    model = _load_whisper_model(selected_model, selected_device)

    transcribe_kwargs = {
        "audio": media_path,
        "language": language,
        "beam_size": 5,
        "condition_on_previous_text": False,
        "word_timestamps": True,
    }
    if LOCAL_WHISPER_VAD_FILTER:
        transcribe_kwargs["vad_filter"] = True
        transcribe_kwargs["vad_parameters"] = LOCAL_WHISPER_VAD_PARAMETERS
    else:
        transcribe_kwargs["vad_filter"] = False

    segments_iter, info = model.transcribe(**transcribe_kwargs)

    segments = []
    try:
        segment_items = iter(segments_iter or [])
    except TypeError:
        segment_items = iter(())
    for s in segment_items:
        if cancellation_requested() or (cancel_check and cancel_check()):
            raise RuntimeError("Job cancelled")
        try:
            segment_start = float(s.start)
            segment_end = float(s.end)
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(segment_start) or not math.isfinite(segment_end) or segment_end <= segment_start:
            continue
        text = str(getattr(s, "text", "") or "").strip()
        if not text:
            continue
        segment = {
            "start": segment_start,
            "end": segment_end,
            "text": text,
        }
        words = []
        raw_words = getattr(s, "words", None)
        word_items = raw_words if isinstance(raw_words, (list, tuple)) else []
        for word in word_items:
            if getattr(word, "start", None) is None or getattr(word, "end", None) is None:
                continue
            try:
                word_start = float(word.start)
                word_end = float(word.end)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(word_start) or not math.isfinite(word_end) or word_end <= word_start:
                continue
            words.append(
                {
                    "start": word_start,
                    "end": word_end,
                    "word": str(getattr(word, "word", "") or "").strip(),
                }
            )
        if words:
            segment["words"] = words
        segments.append(segment)

    try:
        duration = float(getattr(info, "duration", 0.0))
    except (TypeError, ValueError, OverflowError):
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        duration = segments[-1]["end"] if segments else 0.0
    print(f"[transcribe/local] {len(segments)} segments, {duration:.0f}s of audio", flush=True)
    transcript = {"duration": duration, "segments": segments}
    cache_path = _write_srt_cache(
        media_path,
        transcript,
        cache_dir=cache_dir,
        signature=signature,
        cache_key=cache_key,
    )
    print(f"[transcribe/local] wrote cache: {cache_path}", flush=True)
    return transcript
