"""Download Episode 3 audio stream and transcribe with faster-whisper word events.

Extracts audio only (~50MB) from Episode 3 (https://youtu.be/Lvfc2eYMRHU),
caches full manifest to output/raw/video/ep3_video_info.json,
and generates microsecond word-level transcript at output/raw/captions/ep3_transcript.json.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

import yt_dlp
from faster_whisper import WhisperModel

VIDEO_URL = "https://youtu.be/Lvfc2eYMRHU"
VIDEO_ID = "Lvfc2eYMRHU"
OUTPUT_DIR = Path("output")
RAW_AUDIO_DIR = OUTPUT_DIR / "raw" / "audio"
RAW_VIDEO_DIR = OUTPUT_DIR / "raw" / "video"
RAW_CAPTIONS_DIR = OUTPUT_DIR / "raw" / "captions"


def ensure_directories() -> None:
    """Create all required raw output directories if not present."""
    RAW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    RAW_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    RAW_CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)


def download_audio_and_manifest() -> Path:
    """Download audio stream and full video manifest JSON.

    Returns:
        Path to downloaded audio file.
    """
    ensure_directories()
    manifest_path = RAW_VIDEO_DIR / "ep3_video_info.json"
    audio_path = RAW_AUDIO_DIR / "ep3_audio.m4a"

    if audio_path.exists() and manifest_path.exists():
        print(f"[*] Audio and manifest already present at {audio_path}", flush=True)
        return audio_path

    ydl_opts = {
        "format": "140/ba[ext=m4a]/ba",
        "outtmpl": str(audio_path),
        "overwrites": True,
        "quiet": False,
        "no_warnings": True,
    }

    print(f"[*] Extracting manifest and downloading audio for {VIDEO_ID}...", flush=True)
    t0 = time.time()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if not audio_path.exists():
            info = ydl.extract_info(VIDEO_URL, download=True)
        else:
            info = ydl.extract_info(VIDEO_URL, download=False)
        clean_info = ydl.sanitize_info(info)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(clean_info, f, indent=2, ensure_ascii=False)

    print(f"[+] Download and manifest saved in {time.time() - t0:.2f}s -> {audio_path}", flush=True)
    return audio_path


def transcribe_audio(audio_path: Path, model_size: str = "base.en") -> Path:
    """Transcribe audio file into word-level JSON transcript.

    Args:
        audio_path: Local media path to transcribe.
        model_size: Faster-whisper model size name.

    Returns:
        Path to output transcript JSON.
    """
    transcript_path = RAW_CAPTIONS_DIR / "ep3_transcript.json"
    if transcript_path.exists():
        print(f"[*] Transcript already exists at {transcript_path}", flush=True)
        return transcript_path

    print(f"[*] Loading Faster-Whisper model ({model_size})...", flush=True)
    t0 = time.time()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    print(f"[*] Transcribing {audio_path.name} with word-level timestamps...", flush=True)
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=250),
    )

    segment_list: List[Dict] = []
    total_words = 0
    for seg in segments:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "probability": round(w.probability, 3),
                })
                total_words += 1

        segment_list.append({
            "id": seg.id,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })

    payload = {
        "video_id": VIDEO_ID,
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
        "total_words": total_words,
        "segments": segment_list,
    }

    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"[+] Transcription finished in {time.time() - t0:.2f}s ({total_words} words, {len(segment_list)} segments) -> {transcript_path}", flush=True)
    return transcript_path


def main() -> None:
    """Entry point for audio download and transcription pipeline."""
    audio_file = download_audio_and_manifest()
    transcribe_audio(audio_file)


if __name__ == "__main__":
    main()
