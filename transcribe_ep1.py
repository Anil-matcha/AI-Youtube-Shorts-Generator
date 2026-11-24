"""Module for extracting audio and transcribing Episode 1 with faster-whisper.

Uses vad_filter=True and beam_size=1 for high-speed transcription of speech regions.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List
from faster_whisper import WhisperModel

VIDEO_PATH = Path(r"C:\Users\techd\Videos\DO NOT MISS THIS IN GTA 6! Jason's House Repair Guide (Ep. 1).mkv")
OUTPUT_DIR = Path("ai-shorts-generator/output")
RAW_AUDIO_DIR = OUTPUT_DIR / "raw" / "audio"
RAW_CAPTIONS_DIR = OUTPUT_DIR / "raw" / "captions"


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    """Extract 16kHz mono audio from input video using ffmpeg.

    Args:
        video_path: Source video path.
        audio_path: Target wav path.

    Returns:
        Path to extracted audio.
    """
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_path.exists() and audio_path.stat().st_size > 1000000:
        print(f"[*] Audio already present at {audio_path}", flush=True)
        return audio_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]
    print(f"[*] Extracting audio from {video_path}...", flush=True)
    subprocess.run(cmd, check=True)
    return audio_path


def transcribe_audio(audio_path: Path, output_json: Path) -> Dict[str, Any]:
    """Transcribe audio with faster-whisper and write word-level JSON.

    Args:
        audio_path: Input audio file.
        output_json: Destination transcript path.

    Returns:
        Dictionary containing transcript segments and metadata.
    """
    output_json.parent.mkdir(parents=True, exist_ok=True)
    if output_json.exists():
        print(f"[*] Transcript already exists at {output_json}", flush=True)
        with open(output_json, "r", encoding="utf-8") as f:
            return json.load(f)

    print("[*] Loading faster-whisper base.en model with vad_filter...", flush=True)
    model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=8)

    print("[*] Transcribing audio with word timestamps and VAD...", flush=True)
    start_time = time.time()
    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=250),
    )

    results: List[Dict[str, Any]] = []
    seg_count = 0
    for s in segments:
        words_list = []
        if s.words:
            for w in s.words:
                words_list.append({
                    "word": w.word,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "probability": round(w.probability, 3),
                })
        results.append({
            "id": s.id,
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "text": s.text.strip(),
            "words": words_list,
        })
        seg_count += 1
        if seg_count % 10 == 0:
            print(f"[*] Transcribed {seg_count} segments (at {s.end:.1f}s)...", flush=True)

    payload = {
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "duration": round(info.duration, 3),
        "total_segments": len(results),
        "segments": results,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    elapsed = round(time.time() - start_time, 2)
    print(f"[+] Transcription complete in {elapsed}s: {len(results)} segments saved to {output_json}", flush=True)
    return payload


def main() -> None:
    """Execute audio extraction and transcription."""
    RAW_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    RAW_CAPTIONS_DIR.mkdir(parents=True, exist_ok=True)

    audio_file = RAW_AUDIO_DIR / "ep1_audio_16k.wav"
    transcript_file = RAW_CAPTIONS_DIR / "ep1_transcript.json"

    extract_audio(VIDEO_PATH, audio_file)
    transcribe_audio(audio_file, transcript_file)


if __name__ == "__main__":
    main()
