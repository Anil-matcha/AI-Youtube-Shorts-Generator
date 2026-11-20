"""Dynamic animated subtitle generator for viral vertical YouTube Shorts.

Extracts speech with word-level microsecond timestamps via faster-whisper,
formats words into punchy high-contrast karaoke chunks, and compiles
Advanced SubStation Alpha (.ass) subtitle files with active-word highlight.
"""

import os
import re
from typing import List, Dict, Any
from faster_whisper import WhisperModel


def format_ass_timestamp(seconds: float) -> str:
    """Format floating point seconds into an ASS timestamp string (H:MM:SS.cs).

    Args:
        seconds: Time position in seconds.

    Returns:
        String formatted in H:MM:SS.cs for ASS event dialogue entries.
    """
    total_centis = int(round(max(0.0, seconds) * 100))
    hours = total_centis // 360000
    remainder = total_centis % 360000
    minutes = remainder // 6000
    remainder %= 6000
    secs = remainder // 100
    centis = remainder % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def sanitize_text(text: str) -> str:
    """Sanitize subtitle text by escaping ASS control characters and normalizing quotes.

    Args:
        text: Raw text string from transcription.

    Returns:
        Sanitized uppercase text string safe for ASS embedding.
    """
    clean = text.replace("{", "(").replace("}", ")").replace("\\", "/")
    clean = clean.replace("â€™", "'").replace("â€œ", '"').replace("â€", '"')
    return clean.strip().upper()


def extract_word_timestamps(media_path: str, model_size: str = "base.en") -> List[Dict[str, Any]]:
    """Transcribe an audio or video file to extract detailed word-level timestamps.

    Args:
        media_path: Absolute or relative path to the media file.
        model_size: Faster-whisper model identifier to load.

    Returns:
        List of dictionaries containing sanitized word, start timestamp, and end timestamp.
    """
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(media_path, word_timestamps=True, beam_size=5)

    all_words: List[Dict[str, Any]] = []
    for segment in segments:
        if not segment.words:
            continue
        for word_info in segment.words:
            clean_word = sanitize_text(word_info.word)
            if not clean_word:
                continue
            all_words.append({
                "word": clean_word,
                "start": max(0.0, word_info.start),
                "end": max(word_info.start + 0.05, word_info.end)
            })

    return all_words


def chunk_words(words: List[Dict[str, Any]], max_words_per_chunk: int = 3, max_pause_sec: float = 0.45) -> List[List[Dict[str, Any]]]:
    """Segment a sequence of words into short readable chunks for mobile video viewing.

    Args:
        words: List of word timing dictionaries.
        max_words_per_chunk: Maximum number of words in a single subtitle line.
        max_pause_sec: Maximum duration of silence between words before forcing a new chunk.

    Returns:
        List of chunks, where each chunk is a list of word dictionaries.
    """
    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []

    for word in words:
        if not current_chunk:
            current_chunk.append(word)
            continue

        prev_word = current_chunk[-1]
        pause = word["start"] - prev_word["end"]
        has_punctuation = any(prev_word["word"].endswith(p) for p in [".", "!", "?", ","])

        if len(current_chunk) >= max_words_per_chunk or pause > max_pause_sec or has_punctuation:
            chunks.append(current_chunk)
            current_chunk = [word]
        else:
            current_chunk.append(word)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def build_ass_content(chunks: List[List[Dict[str, Any]]]) -> str:
    """Generate complete ASS subtitle document content with dynamic word highlighting.

    Args:
        chunks: List of word chunks with start and end timestamps.

    Returns:
        Complete UTF-8 ASS formatted text content.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Impact,80,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,-1,0,0,0,100,100,2,0,1,7,3,2,60,60,520,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: List[str] = []

    for chunk in chunks:
        if not chunk:
            continue

        chunk_end = chunk[-1]["end"] + 0.20

        for i, active_word in enumerate(chunk):
            start_time = active_word["start"]
            if i < len(chunk) - 1:
                end_time = max(start_time + 0.08, chunk[i + 1]["start"])
            else:
                end_time = max(start_time + 0.15, chunk_end)

            start_str = format_ass_timestamp(start_time)
            end_str = format_ass_timestamp(end_time)

            line_parts: List[str] = []
            for j, word_item in enumerate(chunk):
                w_text = word_item["word"]
                if j == i:
                    line_parts.append(f"{{\\c&H0000FFFF&\\fscx115\\fscy115}}{w_text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                else:
                    line_parts.append(w_text)

            dialogue_text = " ".join(line_parts)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{dialogue_text}")

    return header + "\n".join(events) + "\n"


def generate_subtitles_for_file(input_media: str, output_ass: str, model_size: str = "base.en") -> str:
    """Execute complete workflow from media transcription to generated ASS subtitle file.

    Args:
        input_media: Path to video or audio source.
        output_ass: Destination path for .ass file.
        model_size: Faster-whisper model identifier.

    Returns:
        Path to the generated ASS file.
    """
    words = extract_word_timestamps(input_media, model_size=model_size)
    chunks = chunk_words(words)
    ass_text = build_ass_content(chunks)

    os.makedirs(os.path.dirname(os.path.abspath(output_ass)), exist_ok=True)
    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(ass_text)

    return output_ass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python generate_animated_captions.py <input_media> <output_ass>")
        sys.exit(1)
    out = generate_subtitles_for_file(sys.argv[1], sys.argv[2])
    print(f"Generated ASS: {out}")
