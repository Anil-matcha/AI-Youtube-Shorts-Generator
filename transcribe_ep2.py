"""Extract and transcribe Episode 2 audio track using faster-whisper.

Converts audio to 16kHz mono WAV, generates word-level timestamps, and
persists structured JSON transcript to output/ep2_transcript.json.
"""

import json
import os
import subprocess
from typing import Dict, Any
from faster_whisper import WhisperModel


def convert_to_wav(m4a_path: str, wav_path: str) -> str:
    """Convert source audio to 16kHz mono PCM WAV for optimal Whisper ingestion.

    Args:
        m4a_path: Path to source m4a file.
        wav_path: Target destination path for WAV audio.

    Returns:
        Path to output WAV file.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", m4a_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        wav_path
    ]
    subprocess.run(cmd, check=True)
    return wav_path


def run_transcription(wav_path: str, output_json: str, model_size: str = "base.en") -> Dict[str, Any]:
    """Transcribe audio track and persist word-level timestamps.

    Args:
        wav_path: Input 16kHz WAV file.
        output_json: Path to save the output JSON transcript.
        model_size: Faster-whisper model identifier.

    Returns:
        Dictionary containing duration, segments, and words.
    """
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(wav_path, word_timestamps=True, beam_size=5)

    segments = []
    all_words = []

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
    data = {
        "duration": duration,
        "segments": segments,
        "words": all_words,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_json)), exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return data


if __name__ == "__main__":
    m4a = r"output\ep2_audio.m4a"
    wav = r"output\ep2_audio.wav"
    out_json = r"output\ep2_transcript.json"

    print("Converting audio to 16kHz WAV...")
    convert_to_wav(m4a, wav)
    print("Transcribing with faster-whisper...")
    res = run_transcription(wav, out_json)
    print(f"Transcribed {len(res['segments'])} segments ({len(res['words'])} words). Saved to {out_json}")
