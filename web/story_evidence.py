"""Opt-in local OCR and speech evidence; no media or model downloads."""

from __future__ import annotations

import csv
import importlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import tempfile
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from web.security import redact_text

MAX_DURATION = 120
MAX_FRAMES = 8
TIMEOUT_SECONDS = 90
SAMPLE_RATE = 16000
MAX_OUTPUT_BYTES = MAX_DURATION * SAMPLE_RATE * 4 + 65536


def clean_evidence_text(value: object) -> str:
    text = redact_text(" ".join(str(value or "").replace("\x00", "").split()), max_length=2000)
    text = re.sub(r"(?:https?://|file://)\S+", "[URL redacted]", text, flags=re.I)
    text = re.sub(r"(?<!\w)(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp|var|mnt)/)[^\s]+", "[local path redacted]", text)
    return text[:500]


def tesseract_command() -> Optional[str]:
    configured = os.getenv("LOCAL_TESSERACT_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate) if candidate.is_file() else None
    return shutil.which("tesseract")


def model_catalog() -> Dict[str, Any]:
    # Discovery must not load inference runtimes or fetch missing assets.
    try:
        package = importlib.util.find_spec("faster_whisper")
        vad_available = bool(
            package and package.origin
            and (Path(package.origin).parent / "assets" / "silero_vad_v6.onnx").is_file()
            and importlib.util.find_spec("onnxruntime")
            and importlib.util.find_spec("numpy")
        )
    except (ImportError, ValueError, OSError):
        vad_available = False
    return {
        "models": [
            {"id": "tesseract", "kind": "ocr", "label": "Tesseract on-screen text", "available": bool(tesseract_command()),
             "notice": "Uses your local Tesseract installation and selected language data. Nothing is downloaded."},
            {"id": "silero-vad", "kind": "audio", "label": "Silero speech activity", "available": vad_available,
             "notice": "Detects speech activity locally; it does not classify laughter, music, or emotion."},
        ],
        "budgets": {"max_duration_seconds": MAX_DURATION, "max_frames": MAX_FRAMES, "timeout_seconds": TIMEOUT_SECONDS},
    }


def parse_ocr_tsv(payload: bytes, timestamp: float) -> List[Dict[str, Any]]:
    """Keep confidence-filtered lines, not raw OCR documents or image paths."""
    if len(payload) > 1024 * 1024:
        raise RuntimeError("OCR output exceeded its budget")
    lines: Dict[tuple[str, ...], List[tuple[str, float]]] = {}
    for row in list(csv.DictReader(io.StringIO(payload.decode("utf-8", errors="replace")), delimiter="\t"))[:10000]:
        try:
            confidence = float(row.get("conf") or -1)
        except (TypeError, ValueError):
            continue
        text = str(row.get("text") or "").strip()
        if not text or not math.isfinite(confidence) or not 40 <= confidence <= 100:
            continue
        key = tuple(str(row.get(field) or "") for field in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append((text, confidence))
    evidence: List[Dict[str, Any]] = []
    for words in list(lines.values())[:24]:
        text = clean_evidence_text(" ".join(word for word, _confidence in words))
        if text:
            evidence.append({"start_time": round(timestamp, 3), "end_time": round(timestamp, 3), "text": text,
                             "confidence": round(sum(conf for _word, conf in words) / len(words) / 100, 3), "model": "tesseract"})
    return evidence


def speech_evidence(payload: bytes, start: float) -> List[Dict[str, Any]]:
    if len(payload) > MAX_OUTPUT_BYTES or len(payload) % 4:
        raise RuntimeError("Audio output exceeded its budget or is invalid")
    numpy = importlib.import_module("numpy")
    vad = importlib.import_module("faster_whisper.vad")
    audio = numpy.frombuffer(payload, dtype="<f4").copy()
    if not len(audio):
        return []
    if not numpy.isfinite(audio).all():
        raise RuntimeError("Audio contains invalid samples")
    regions = vad.get_speech_timestamps(audio, vad_options=vad.VadOptions(
        threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=500,
        max_speech_duration_s=30, speech_pad_ms=100), sampling_rate=SAMPLE_RATE)
    output: List[Dict[str, Any]] = []
    for region in regions[:240]:
        begin = max(0, min(len(audio), int(region["start"])))
        end = max(begin, min(len(audio), int(region["end"])))
        if end > begin:
            output.append({"start_time": round(start + begin / SAMPLE_RATE, 3), "end_time": round(start + end / SAMPLE_RATE, 3),
                           "text": "Speech activity", "type": "speech", "model": "silero-vad"})
    return output


def analyze_local(
    source: Path, values: Dict[str, Any],
    run: Callable[[List[str]], bytes], check: Callable[[], None],
) -> Dict[str, Any]:
    from shorts_generator.local.clipper import _find_ffmpeg

    check()
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is unavailable")
    start = float(values["start_time"])
    duration = float(values["duration_seconds"])
    result: Dict[str, Any] = {"schema": "shorts-studio-evidence-1", "start_time": start, "duration_seconds": duration,
                              "models": [values[key] for key in ("ocr_model", "audio_model") if values.get(key)], "ocr": [], "audio": []}
    with tempfile.TemporaryDirectory(prefix="shorts-evidence-") as directory:
        if values.get("ocr_model"):
            engine = tesseract_command()
            if not engine:
                raise RuntimeError("Tesseract is unavailable; install it locally and select its language data")
            frames = int(values["max_frames"])
            for index in range(frames):
                check()
                timestamp = start + duration * index / frames
                frame = Path(directory) / f"frame-{index}.png"
                run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe",
                     "-ss", str(timestamp), "-i", str(source), "-frames:v", "1", "-vf",
                     "scale=960:540:force_original_aspect_ratio=decrease", str(frame)])
                if not frame.is_file():
                    break  # Requested window extends past the source duration.
                payload = run([engine, str(frame), "stdout", "-l", values["language"], "--psm", "11", "tsv"])
                result["ocr"].extend(parse_ocr_tsv(payload, timestamp))
        if values.get("audio_model"):
            check()
            payload = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                           "-ss", str(start), "-i", str(source), "-t", str(duration), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                           "-f", "f32le", "pipe:1"])
            check()
            pcm = Path(directory) / "speech.f32"
            pcm.write_bytes(payload)
            output = Path(directory) / "speech.json"
            command = ([sys.executable, "--story-vad-worker"] if getattr(sys, "frozen", False)
                       else [sys.executable, str(Path(__file__).with_name("story_evidence_worker.py"))])
            run([*command, str(pcm), str(start), str(output)])
            with output.open("rb") as stream:
                encoded = stream.read(256 * 1024 + 1)
            if len(encoded) > 256 * 1024:
                raise RuntimeError("Audio evidence exceeded its budget")
            result["audio"] = json.loads(encoded)
    check()
    return result
