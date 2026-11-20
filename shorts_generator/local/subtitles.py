"""Dynamic animated subtitle engine for short-form vertical video.

Generates Advanced SubStation Alpha (.ass) subtitles with karaoke-style
active word pop and high-contrast styling for YouTube Shorts and TikTok.
"""

import os
from typing import List, Dict, Any
from faster_whisper import WhisperModel


def format_ass_timestamp(seconds: float) -> str:
    """Convert a timestamp in seconds to standard ASS format (H:MM:SS.cs).

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        Formatted timestamp string.
    """
    total_centis = int(round(max(0.0, seconds) * 100))
    hours = total_centis // 360000
    remainder = total_centis % 360000
    minutes = remainder // 6000
    remainder %= 6000
    secs = remainder // 100
    centis = remainder % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def sanitize_dialogue(text: str) -> str:
    """Sanitize subtitle text by escaping ASS control symbols and uppercase normalization.

    Args:
        text: Raw transcribed string.

    Returns:
        Safe uppercase subtitle string.
    """
    clean = text.replace("{", "(").replace("}", ")").replace("\\", "/")
    clean = clean.replace("â€™", "'").replace("â€œ", '"').replace("â€", '"')
    return clean.strip().upper()


def extract_word_timings(media_path: str, model_size: str = "base.en") -> List[Dict[str, Any]]:
    """Transcribe media to retrieve word-level boundaries and probabilities.

    Args:
        media_path: Local media path.
        model_size: Faster-whisper model identifier.

    Returns:
        List of dictionaries with sanitized word, start timestamp, and end timestamp.
    """
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(media_path, word_timestamps=True, beam_size=5)

    words: List[Dict[str, Any]] = []
    for segment in segments:
        if not segment.words:
            continue
        for item in segment.words:
            w_text = sanitize_dialogue(item.word)
            if not w_text:
                continue
            words.append({
                "word": w_text,
                "start": max(0.0, item.start),
                "end": max(item.start + 0.05, item.end)
            })
    return words


def group_into_chunks(words: List[Dict[str, Any]], max_words: int = 3, max_gap_sec: float = 0.45) -> List[List[Dict[str, Any]]]:
    """Group words into short conversational chunks for fast-paced mobile viewing.

    Args:
        words: List of word timing dictionaries.
        max_words: Maximum words per displayed subtitle line.
        max_gap_sec: Maximum pause duration before splitting into a new chunk.

    Returns:
        List of word chunks.
    """
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []

    for word in words:
        if not current:
            current.append(word)
            continue

        prev = current[-1]
        gap = word["start"] - prev["end"]
        punct = any(prev["word"].endswith(p) for p in [".", "!", "?", ","])

        if len(current) >= max_words or gap > max_gap_sec or punct:
            chunks.append(current)
            current = [word]
        else:
            current.append(word)

    if current:
        chunks.append(current)

    return chunks


def build_ass_script(
    chunks: List[List[Dict[str, Any]]],
    margin_v: int = 520,
    font_name: str = "Impact",
    font_size: int = 78,
    active_color: str = "&H0000FFFF",
    inactive_color: str = "&H00FFFFFF",
    outline_color: str = "&H00000000",
    outline_width: int = 7
) -> str:
    """Build complete ASS document with active-word karaoke styling.

    Args:
        chunks: List of word chunks.
        margin_v: Vertical margin from bottom edge in 1080x1920 coordinates.
        font_name: Font face name.
        font_size: Point size of the subtitle text.
        active_color: ASS color code for currently spoken word.
        inactive_color: ASS color code for surrounding chunk words.
        outline_color: ASS color code for text stroke outline.
        outline_width: Pixel width of the stroke outline.

    Returns:
        Full UTF-8 ASS file content string.
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},{inactive_color},{active_color},{outline_color},&H90000000,-1,0,0,0,100,100,2,0,1,{outline_width},3,2,60,60,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue

        chunk_end = chunk[-1]["end"] + 0.20
        for i, word_item in enumerate(chunk):
            start_t = word_item["start"]
            if i < len(chunk) - 1:
                end_t = max(start_t + 0.08, chunk[i + 1]["start"])
            else:
                end_t = max(start_t + 0.15, chunk_end)

            start_str = format_ass_timestamp(start_t)
            end_str = format_ass_timestamp(end_t)

            tokens: List[str] = []
            for j, token in enumerate(chunk):
                w = token["word"]
                if j == i:
                    tokens.append(f"{{\\c{active_color}&\\fscx115\\fscy115}}{w}{{\\c{inactive_color}&\\fscx100\\fscy100}}")
                else:
                    tokens.append(w)

            line_text = " ".join(tokens)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{line_text}")

    return header + "\n".join(events) + "\n"


def generate_ass_file(input_media: str, output_ass: str, margin_v: int = 520) -> str:
    """Generate and write an ASS subtitle file from input media.

    Args:
        input_media: Path to video or audio source.
        output_ass: Path to write destination .ass file.
        margin_v: Vertical margin from bottom edge.

    Returns:
        Absolute path to the created ASS file.
    """
    words = extract_word_timings(input_media)
    chunks = group_into_chunks(words)
    content = build_ass_script(chunks, margin_v=margin_v)

    os.makedirs(os.path.dirname(os.path.abspath(output_ass)), exist_ok=True)
    with open(output_ass, "w", encoding="utf-8") as f:
        f.write(content)

    return os.path.abspath(output_ass)
