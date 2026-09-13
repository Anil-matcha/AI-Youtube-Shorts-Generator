"""Local clipping: ffmpeg subclip + OpenCV face-aware vertical crop.

Two stages per highlight:
  1. Cut the source video to [start, end] with ffmpeg (re-encoded, audio kept).
  2. Reframe the cut to the target aspect ratio. For 9:16 we slide a vertical
     window horizontally across the frame to keep faces centred (Haar
     cascade — same approach as the original repo, no external models).
"""

import os
import re
import shutil
import subprocess
import time
import math
from functools import lru_cache
from pathlib import Path
import textwrap
from typing import Dict, List, Optional, Tuple

from ..config import LOCAL_OUTPUT_DIR
from .face_detection import create_face_detector


def _remove_with_retry(path: str, attempts: int = 8, delay: float = 0.5) -> None:
    """os.remove with retries — Windows Defender's real-time scanner can
    briefly hold a lock on a freshly-written file, causing WinError 32."""
    for i in range(attempts):
        try:
            os.remove(path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


@lru_cache(maxsize=1)
def _find_ffmpeg() -> str:
    """Resolve ffmpeg even when winget/scoop installed it off PATH."""
    found = shutil.which("ffmpeg")
    if found:
        return found

    candidates: List[Path] = []
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        winget_root = Path(local_app) / "Microsoft" / "WinGet" / "Packages"
        if winget_root.is_dir():
            candidates.extend(winget_root.glob("**/ffmpeg.exe"))

    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        candidates.extend((Path(user_profile) / "scoop" / "apps" / "ffmpeg").glob("**/ffmpeg.exe"))

    for extra in (
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"),
    ):
        candidates.append(extra)

    for path in candidates:
        if path.is_file():
            return str(path)

    raise RuntimeError(
        "ffmpeg was not found on PATH (or in common install locations). "
        "Install it and ensure `ffmpeg` is available, e.g.:\n"
        "    winget install Gyan.FFmpeg\n"
        "Then restart the terminal so PATH updates take effect."
    )


def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' → 9/16, '1:1' → 1.0."""
    try:
        w, h = str(aspect_ratio or "").split(":")
        ratio = float(w) / float(h)
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError
        return ratio
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return 9.0 / 16.0


def _finite_float(value: object, default: float) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return converted if math.isfinite(converted) else default


def _ass_timestamp(seconds: float) -> str:
    """Format seconds as an ASS timestamp (H:MM:SS.cc)."""
    total_cs = max(0, int(round(_finite_float(seconds, 0.0) * 100)))
    centiseconds = total_cs % 100
    total_seconds = total_cs // 100
    second = total_seconds % 60
    total_minutes = total_seconds // 60
    minute = total_minutes % 60
    hour = total_minutes // 60
    return f"{hour}:{minute:02d}:{second:02d}.{centiseconds:02d}"


def _escape_ass_text(value: object, remove_filler_words: bool = False) -> str:
    """Escape transcript text so it cannot be interpreted as ASS markup."""
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if remove_filler_words:
        text = re.sub(r"\b(?:um+|uh+|erm|you know|basically|literally)\b[,.]?", "", text, flags=re.I)
        text = " ".join(text.split())
    text = text.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")
    wrapped = textwrap.wrap(
        text,
        width=38,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return r"\N".join(wrapped) if wrapped else ""


def _has_audio_stream(media_path: str) -> bool:
    """Return whether FFmpeg can see an audio stream in a media file."""
    ffmpeg = _find_ffmpeg()
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", media_path],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(re.search(r"Stream .*?: Audio:", probe.stderr or ""))


def _has_video_stream(media_path: str) -> bool:
    """Return whether FFmpeg can see a video stream in a media file."""
    ffmpeg = _find_ffmpeg()
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", media_path],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(re.search(r"Stream .*?: Video:", probe.stderr or ""))


def _add_silent_audio(media_path: str, out_path: str) -> str:
    """Add a silent AAC track to a video that has no audio stream."""
    ffmpeg = _find_ffmpeg()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            media_path,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            out_path,
        ],
        check=True,
    )
    return out_path


def _caption_style_values(style: str, position: str = "bottom") -> Tuple[int, str, str, str, int, int, int]:
    """Return font/style values for a named caption preset."""
    presets = {
        "clean": (48, "&H00FFFFFF", "&H00000000", "&H99000000", 3, 1, 2),
        "bold": (56, "&H00FFFFFF", "&H00000000", "&H99000000", 8, 1, 2),
        "boxed": (52, "&H00FFFFFF", "&H00000000", "&HCC000000", 1, 3, 2),
        "karaoke": (54, "&H0000FFFF", "&H0000FFFF", "&H99000000", 7, 1, 2),
    }
    style_key = str(style or "bold").strip().lower()
    position_key = str(position or "bottom").strip().lower()
    values = presets.get(style_key, presets["bold"])
    alignment = {"top": 8, "center": 5, "bottom": 2}.get(position_key, 2)
    return (*values[:6], alignment)


def _write_ass_captions(
    ass_path: str,
    clip_start: float,
    clip_end: float,
    segments: List[Dict],
    caption_style: str = "bold",
    remove_filler_words: bool = False,
    caption_position: str = "bottom",
    caption_font: str = "Arial",
    caption_size: int = 0,
    caption_color: Optional[str] = None,
) -> int:
    """Write an ASS subtitle file containing transcript segments in a clip."""
    clip_start = _finite_float(clip_start, 0.0)
    clip_end = _finite_float(clip_end, clip_start)
    if clip_end <= clip_start:
        return 0
    style_key = str(caption_style or "bold").strip().lower()
    font_size, primary, secondary, back, outline, border_style, alignment = _caption_style_values(
        caption_style, caption_position
    )
    try:
        requested_size = int(caption_size) if caption_size else 0
    except (TypeError, ValueError, OverflowError):
        requested_size = 0
    if requested_size:
        font_size = max(18, min(120, requested_size))
    if caption_color:
        raw = str(caption_color).lstrip("#")
        if re.fullmatch(r"[0-9A-Fa-f]{6}", raw):
            primary = f"&H00{raw[4:6]}{raw[2:4]}{raw[0:2]}"
    safe_font = re.sub(r"[\r\n,]", " ", str(caption_font or "Arial")).strip()[:80] or "Arial"
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{safe_font},{font_size},{primary},{secondary},&H00000000,{back},-1,0,0,0,100,100,0,0,{border_style},{outline},2,{alignment},72,72,170,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines = list(header)
    count = 0
    segment_items = segments if isinstance(segments, (list, tuple)) else []
    for segment in segment_items:
        if not isinstance(segment, dict):
            continue
        try:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or end <= start or end <= clip_start or start >= clip_end:
            continue
        text = _escape_ass_text(segment.get("text", ""), remove_filler_words=remove_filler_words)
        if not text:
            continue
        relative_start = max(0.0, start - clip_start)
        relative_end = min(clip_end, end) - clip_start
        if relative_end <= relative_start:
            continue
        if style_key == "karaoke":
            timed_words = []
            for word in segment.get("words") or []:
                try:
                    word_start = max(relative_start, float(word["start"]) - clip_start)
                    word_end = min(relative_end, float(word["end"]) - clip_start)
                    word_text = _escape_ass_text(word.get("word", ""), remove_filler_words=remove_filler_words)
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if math.isfinite(word_start) and math.isfinite(word_end) and word_end > word_start and word_text:
                    timed_words.append((word_start, word_end, word_text))
            if not timed_words:
                plain_words = " ".join(text.split(r"\N")).split()
                if plain_words:
                    word_duration = (relative_end - relative_start) / len(plain_words)
                    timed_words = [
                        (
                            relative_start + index * word_duration,
                            relative_start + (index + 1) * word_duration,
                            word,
                        )
                        for index, word in enumerate(plain_words)
                    ]
            if timed_words:
                plain_words = [word for _, _, word in timed_words]
                for word_start, word_end, word in timed_words:
                    highlighted = " ".join(
                        (r"{\c&H0000FFFF&}" + candidate + r"{\c&H00FFFFFF&}") if candidate == word else candidate
                        for candidate in plain_words
                    )
                    lines.append(
                        "Dialogue: 0,{},{},Default,,0,0,0,,{}".format(
                            _ass_timestamp(word_start),
                            _ass_timestamp(word_end),
                            highlighted,
                        )
                    )
                    count += 1
        else:
            lines.append(
                "Dialogue: 0,{},{},Default,,0,0,0,,{}".format(
                    _ass_timestamp(relative_start),
                    _ass_timestamp(relative_end),
                    text,
                )
            )
            count += 1

    Path(ass_path).parent.mkdir(parents=True, exist_ok=True)
    Path(ass_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return count


def _has_caption_window(clip_start: float, clip_end: float, segments: Optional[List[Dict]]) -> bool:
    """Return whether at least one non-empty transcript segment overlaps a clip."""
    clip_start = _finite_float(clip_start, 0.0)
    clip_end = _finite_float(clip_end, clip_start)
    if clip_end <= clip_start:
        return False
    segment_items = segments if isinstance(segments, (list, tuple)) else []
    for segment in segment_items:
        if not isinstance(segment, dict):
            continue
        try:
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if end > clip_start and start < clip_end and _escape_ass_text(segment.get("text", "")):
            return True
    return False


def _escape_filter_path(path: str) -> str:
    """Escape a Windows/Unix path for ffmpeg's subtitles filter."""
    # The filter parser wants forward slashes and an escaped drive-letter
    # colon. The surrounding single quotes keep spaces in paths intact.
    return str(Path(path).resolve()).replace("\\", "/").replace(":", r"\:")


def _burn_in_captions(
    video_path: str,
    clip_start: float,
    clip_end: float,
    segments: List[Dict],
    out_path: str,
    caption_style: str = "bold",
    remove_filler_words: bool = False,
    caption_position: str = "bottom",
    caption_font: str = "Arial",
    caption_size: int = 0,
    caption_color: Optional[str] = None,
) -> bool:
    """Render transcript captions onto a reframed video with ffmpeg/libass."""
    ass_path = out_path + ".ass"
    try:
        caption_count = _write_ass_captions(
            ass_path,
            clip_start=clip_start,
            clip_end=clip_end,
            segments=segments,
            caption_style=caption_style,
            remove_filler_words=remove_filler_words,
            caption_position=caption_position,
            caption_font=caption_font,
            caption_size=caption_size,
            caption_color=caption_color,
        )
        if not caption_count:
            shutil.copyfile(video_path, out_path)
            return False

        ffmpeg = _find_ffmpeg()
        subtitle_file = _escape_filter_path(ass_path).replace("'", r"\'")
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-vf",
            f"subtitles=filename='{subtitle_file}'",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            out_path,
        ]
        subprocess.run(cmd, check=True)
        return True
    finally:
        if os.path.exists(ass_path):
            _remove_with_retry(ass_path)


def _cut_subclip(source_path: str, start: float, end: float, out_path: str) -> str:
    """ffmpeg -ss start -to end -> re-encoded mp4 with audio."""
    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        source_path,
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _reframe_vertical(
    in_path: str,
    out_path: str,
    aspect_ratio: str,
    auto_reframe: bool = True,
    crop_position: float = 0.5,
    fit_mode: str = "crop",
    zoom: float = 1.0,
    layout: str = "single",
    output_height: int = 1920,
) -> str:
    """Crop the cut clip to the target aspect ratio, tracking faces if possible."""
    try:
        import cv2  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "opencv-python is required for --mode local. Install it with:\n    pip install -r requirements-local.txt"
        ) from e

    target_ratio = _ratio(aspect_ratio)
    try:
        render_height = int(output_height)
    except (TypeError, ValueError, OverflowError):
        render_height = 1920
    render_height = max(240, min(4320, render_height or 1920))
    layout_name = str(layout or "single").strip().lower()
    if layout_name == "split":
        ffmpeg = _find_ffmpeg()
        out_h = render_height
        out_w = max(2, int(round(out_h * target_ratio)) // 2 * 2)
        half = max(2, out_w // 2)
        split_filter = f"[0:v]crop=iw/2:ih:0:0,scale={half}:{out_h}:force_original_aspect_ratio=decrease,pad={half}:{out_h}:(ow-iw)/2:(oh-ih)/2[left];[0:v]crop=iw/2:ih:iw/2:0,scale={half}:{out_h}:force_original_aspect_ratio=decrease,pad={half}:{out_h}:(ow-iw)/2:(oh-ih)/2[right];[left][right]hstack=inputs=2[v]"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                in_path,
                "-filter_complex",
                split_filter,
                "-map",
                "[v]",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                out_path,
            ],
            check=True,
        )
        return out_path
    fit_name = str(fit_mode or "crop").strip().lower()
    if fit_name == "fit_blur":
        ffmpeg = _find_ffmpeg()
        out_h = render_height
        out_w = max(2, int(round(out_h * target_ratio)) // 2 * 2)
        zoom = max(0.5, min(1.5, _finite_float(zoom, 1.0)))
        filter_complex = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},boxblur=20:10[bg];"
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,scale=iw*{zoom:.3f}:ih*{zoom:.3f}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                in_path,
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-shortest",
                out_path,
            ],
            check=True,
        )
        return out_path
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open {in_path}")

    src_w = int(max(0.0, round(_finite_float(cap.get(cv2.CAP_PROP_FRAME_WIDTH), 0.0))))
    src_h = int(max(0.0, round(_finite_float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT), 0.0))))
    if src_w < 2 or src_h < 2:
        cap.release()
        raise RuntimeError(f"video has invalid dimensions ({src_w}x{src_h})")
    fps = _finite_float(cap.get(cv2.CAP_PROP_FPS), 30.0)
    if fps <= 0:
        fps = 30.0

    # Compute the largest crop that fits inside the frame at the target ratio.
    # A zoom above 1.0 tightens that crop around the selected center; a zoom
    # below 1.0 reveals more of the source while keeping the target canvas.
    if target_ratio < src_w / src_h:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
    # Crop-to-fill cannot reveal pixels outside the source frame.  Treat
    # values below 100% as the largest possible crop rather than stretching a
    # non-matching aspect ratio; zoom-out remains available in fit+blur mode.
    zoom_value = max(1.0, min(1.5, _finite_float(zoom, 1.0)))
    crop_w = int(round(crop_w / zoom_value))
    crop_h = int(round(crop_h / zoom_value))
    crop_w = min(src_w, max(2, crop_w - (crop_w % 2)))
    crop_h = min(src_h, max(2, crop_h - (crop_h % 2)))
    if crop_w % 2:
        crop_w -= 1
    if crop_h % 2:
        crop_h -= 1
    crop_w = max(2, crop_w)
    crop_h = max(2, crop_h)

    face_detector = None
    if auto_reframe:
        face_detector = create_face_detector(cv2)

    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    output_crop_h = render_height
    output_crop_w = max(2, int(round(output_crop_h * target_ratio)) // 2 * 2)
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (output_crop_w, output_crop_h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"could not create temporary video writer for {out_path}")

    last_center: Optional[Tuple[int, int]] = None
    smoothing = 0.15  # how aggressively to chase a new face position
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        faces = face_detector(frame) if face_detector is not None else []
        if len(faces) > 0:
            # Pick the largest face — usually the speaker.
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx = x + w // 2
            cy = y + h // 2
            if last_center is None:
                last_center = (cx, cy)
            else:
                lx, ly = last_center
                last_center = (
                    int(lx + (cx - lx) * smoothing),
                    int(ly + (cy - ly) * smoothing),
                )
        if last_center is None and not auto_reframe:
            position = max(0.0, min(1.0, _finite_float(crop_position, 0.5)))
            last_center = (int(crop_w / 2 + position * (src_w - crop_w)), src_h // 2)
        if last_center is None:
            last_center = (src_w // 2, src_h // 2)

        cx, cy = last_center
        x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
        y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))
        cropped = frame[y0 : y0 + crop_h, x0 : x0 + crop_w]
        if cropped.shape[1] != output_crop_w or cropped.shape[0] != output_crop_h:
            cropped = cv2.resize(cropped, (output_crop_w, output_crop_h), interpolation=cv2.INTER_AREA)
        writer.write(cropped)

    cap.release()
    writer.release()

    # Mux audio from the cut clip back onto the silent reframed video.
    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        silent_path,
        "-i",
        in_path,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-shortest",
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True)
    finally:
        if os.path.exists(silent_path):
            _remove_with_retry(silent_path)
    return out_path


def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    aspect_ratio: str,
    out_path: str,
    caption_segments: Optional[List[Dict]] = None,
    burn_captions: bool = True,
    caption_style: str = "bold",
    remove_silence: bool = False,
    normalize_audio: bool = False,
    denoise_audio: bool = False,
    remove_filler_words: bool = False,
    caption_position: str = "bottom",
    caption_font: str = "Arial",
    caption_size: int = 0,
    caption_color: Optional[str] = None,
    background_music: Optional[str] = None,
    watermark: Optional[str] = None,
    auto_reframe: bool = True,
    crop_position: float = 0.5,
    fit_mode: str = "crop",
    zoom: float = 1.0,
    layout: str = "single",
    intro: Optional[str] = None,
    outro: Optional[str] = None,
    jump_cuts: bool = False,
    output_height: int = 1920,
) -> str:
    """Cut + reframe one highlight, optionally burning Whisper captions."""
    source_path = str(source_path) if source_path is not None else ""
    out_path = str(out_path) if out_path is not None else ""
    start_time = _finite_float(start_time, -1.0)
    end_time = _finite_float(end_time, -1.0)
    if start_time < 0 or end_time <= start_time:
        raise RuntimeError("invalid clip timestamps: end_time must be after start_time")
    if not os.path.isfile(source_path):
        raise RuntimeError(f"source video file not found: {source_path}")
    if not out_path:
        raise RuntimeError("clip output path is required")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    for label, media in (
        ("background music", background_music),
        ("watermark", watermark),
        ("intro", intro),
        ("outro", outro),
    ):
        if media and not os.path.isfile(media):
            raise RuntimeError(f"{label} file not found: {media}")
    if background_music and not _has_audio_stream(background_music):
        raise RuntimeError(f"background music file has no audio stream: {background_music}")
    cut_path = out_path + ".cut.mp4"
    base_path = out_path + ".base.mp4"
    try:
        _cut_subclip(source_path, start_time, end_time, cut_path)
        _reframe_vertical(
            cut_path,
            base_path,
            aspect_ratio,
            auto_reframe=auto_reframe,
            crop_position=crop_position,
            fit_mode=fit_mode,
            zoom=zoom,
            layout=layout,
            output_height=output_height,
        )
        if burn_captions and caption_segments:
            _burn_in_captions(
                base_path,
                clip_start=start_time,
                clip_end=end_time,
                segments=caption_segments,
                out_path=out_path,
                caption_style=caption_style,
                remove_filler_words=remove_filler_words,
                caption_position=caption_position,
                caption_font=caption_font,
                caption_size=caption_size,
                caption_color=caption_color,
            )
        else:
            os.replace(base_path, out_path)
    finally:
        if os.path.exists(cut_path):
            _remove_with_retry(cut_path)
        if os.path.exists(base_path):
            _remove_with_retry(base_path)
    _apply_audio_processing(out_path, remove_silence, normalize_audio, denoise_audio, jump_cuts)
    _apply_media_extras(out_path, background_music, watermark)
    _apply_branding(out_path, aspect_ratio, output_height, intro, outro)
    return out_path


def _apply_audio_processing(
    out_path: str,
    remove_silence: bool,
    normalize_audio: bool,
    denoise_audio: bool,
    jump_cuts: bool,
) -> None:
    """Apply optional audio filters and silent-section removal in sequence."""
    audio_filters: List[str] = []
    if remove_silence:
        audio_filters.append("silenceremove=stop_periods=-1:stop_duration=0.35:stop_threshold=-40dB")
    if normalize_audio:
        audio_filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if denoise_audio:
        audio_filters.append("afftdn=nf=-25")
    if audio_filters and _has_audio_stream(out_path):
        processed_path = out_path + ".audio.mp4"
        try:
            ffmpeg = _find_ffmpeg()
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    out_path,
                    "-af",
                    ",".join(audio_filters),
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    processed_path,
                ],
                check=True,
            )
            os.replace(processed_path, out_path)
        finally:
            if os.path.exists(processed_path):
                _remove_with_retry(processed_path)
    if jump_cuts and _has_audio_stream(out_path):
        jump_path = out_path + ".jump.mp4"
        try:
            _remove_silent_video(out_path, jump_path)
            os.replace(jump_path, out_path)
        finally:
            if os.path.exists(jump_path):
                _remove_with_retry(jump_path)


def _apply_media_extras(out_path: str, background_music: Optional[str], watermark: Optional[str]) -> None:
    """Mix optional background music and/or watermark into a rendered clip."""
    if not background_music and not watermark:
        return
    extra_path = out_path + ".extras.mp4"
    try:
        ffmpeg = _find_ffmpeg()
        inputs = [ffmpeg, "-y", "-loglevel", "error", "-i", out_path]
        filters: List[str] = []
        maps: List[str] = []
        input_index = 1
        if background_music:
            inputs += ["-stream_loop", "-1", "-i", background_music]
            if _has_audio_stream(out_path):
                filters.append(f"[0:a][{input_index}:a]amix=inputs=2:duration=first:dropout_transition=2[a]")
            else:
                # Some screen recordings contain video only. In that case
                # use the supplied music as the complete audio track.
                filters.append(f"[{input_index}:a]anull[a]")
            maps.append("[a]")
            input_index += 1
        if watermark:
            inputs += ["-i", watermark]
            filters.append(f"[0:v][{input_index}:v]overlay=W-w-24:H-h-24[v]")
            maps.insert(0, "[v]")
        if background_music and not watermark:
            maps.insert(0, "0:v:0")
        if watermark and not background_music:
            maps.append("0:a:0?")
        cmd = inputs
        if filters:
            cmd += ["-filter_complex", ";".join(filters)]
        if maps:
            cmd += ["-map", maps[0]]
            if len(maps) > 1:
                cmd += ["-map", maps[1]]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            extra_path,
        ]
        subprocess.run(cmd, check=True)
        os.replace(extra_path, out_path)
    finally:
        if os.path.exists(extra_path):
            _remove_with_retry(extra_path)


def _apply_branding(
    out_path: str,
    aspect_ratio: str,
    output_height: int,
    intro: Optional[str],
    outro: Optional[str],
) -> None:
    """Concatenate optional intro/outro media after normalizing every stream."""
    if not intro and not outro:
        return
    segments = [media for media in (intro, out_path, outro) if media]
    if len(segments) <= 1:
        return
    branded = out_path + ".branded.mp4"
    concat_inputs: List[str] = []
    silent_audio_paths: List[str] = []
    try:
        ffmpeg = _find_ffmpeg()
        args = [ffmpeg, "-y", "-loglevel", "error"]
        for index, media in enumerate(segments):
            if not _has_video_stream(media):
                raise RuntimeError(f"{media} does not contain a video stream")
            concat_media = media
            if not _has_audio_stream(media):
                concat_media = f"{out_path}.concat_{index}.mp4"
                silent_audio_paths.append(concat_media)
                _add_silent_audio(media, concat_media)
            concat_inputs.append(concat_media)
            args += ["-i", concat_media]
        # Intro/outro files commonly have different dimensions from the
        # generated vertical clip. Normalize every video stream to the selected
        # output canvas before concatenating.
        try:
            concat_h = int(output_height)
        except (TypeError, ValueError, OverflowError):
            concat_h = 1920
        concat_h = max(240, min(4320, concat_h or 1920))
        concat_w = max(2, int(round(concat_h * _ratio(aspect_ratio))) // 2 * 2)
        normalized: List[str] = []
        for index in range(len(concat_inputs)):
            normalized.append(
                f"[{index}:v:0]scale={concat_w}:{concat_h}:force_original_aspect_ratio=decrease,"
                f"pad={concat_w}:{concat_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{index}];"
                f"[{index}:a:0]aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{index}]"
            )
        concat = "".join(f"[v{index}][a{index}]" for index in range(len(concat_inputs)))
        filter_complex = ";".join(normalized + [f"{concat}concat=n={len(concat_inputs)}:v=1:a=1[v][a]"])
        args += [
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            branded,
        ]
        subprocess.run(args, check=True)
        os.replace(branded, out_path)
    finally:
        if os.path.exists(branded):
            _remove_with_retry(branded)
        for silent_audio_path in silent_audio_paths:
            if os.path.exists(silent_audio_path):
                _remove_with_retry(silent_audio_path)


def _remove_silent_video(in_path: str, out_path: str, threshold: str = "-40dB", min_silence: float = 0.35) -> bool:
    """Remove silent intervals from both video and audio using FFmpeg concat."""
    ffmpeg = _find_ffmpeg()
    if not _has_audio_stream(in_path):
        shutil.copyfile(in_path, out_path)
        return False
    detect = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            in_path,
            "-af",
            f"silencedetect=noise={threshold}:d={min_silence}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    log = (detect.stdout or "") + "\n" + (detect.stderr or "")
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", log)]
    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", in_path, "-f", "null", "-"], capture_output=True, text=True, check=False
    )
    duration_matches = re.findall(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", probe.stderr or "")
    if not duration_matches:
        shutil.copyfile(in_path, out_path)
        return False
    h, m, s = duration_matches[0]
    duration = int(h) * 3600 + int(m) * 60 + float(s)
    silent = [
        (max(0.0, start), min(duration, ends[i] if i < len(ends) else duration)) for i, start in enumerate(starts)
    ]
    keep, cursor = [], 0.0
    for start, end in silent:
        if start - cursor > 0.05:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor > 0.05:
        keep.append((cursor, duration))
    if len(keep) <= 1:
        shutil.copyfile(in_path, out_path)
        return False
    filters, concat_inputs = [], []
    for index, (start, end) in enumerate(keep):
        filters += [
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]",
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]",
        ]
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append("".join(concat_inputs) + f"concat=n={len(keep)}:v=1:a=1[v][a]")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            in_path,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            out_path,
        ],
        check=True,
    )
    return True


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    caption_segments: Optional[List[Dict]] = None,
    burn_captions: bool = True,
    caption_style: str = "bold",
    remove_silence: bool = False,
    normalize_audio: bool = False,
    denoise_audio: bool = False,
    remove_filler_words: bool = False,
    caption_position: str = "bottom",
    caption_font: str = "Arial",
    caption_size: int = 0,
    caption_color: Optional[str] = None,
    background_music: Optional[str] = None,
    watermark: Optional[str] = None,
    auto_reframe: bool = True,
    crop_position: float = 0.5,
    fit_mode: str = "crop",
    zoom: float = 1.0,
    layout: str = "single",
    intro: Optional[str] = None,
    outro: Optional[str] = None,
    jump_cuts: bool = False,
    output_height: int = 1920,
) -> List[Dict]:
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict] = []
    items = highlights if isinstance(highlights, (list, tuple)) else []
    for i, h in enumerate(items, 1):
        out_path = os.path.join(out_dir, f"short_{i:02d}.mp4")
        if not isinstance(h, dict):
            message = "highlight must be a JSON object"
            print(f"[clip/local] {i} failed: {message}", flush=True)
            results.append({"clip_url": None, "error": message})
            continue
        print(f"[clip/local] {i}/{len(items)}: {h.get('title', '(untitled)')}", flush=True)
        preexisting_output = os.path.isfile(out_path)
        try:
            start_time = float(h["start_time"])
            end_time = float(h["end_time"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            message = f"invalid highlight timestamps: {exc}"
            print(f"[clip/local] {i} failed: {message}", flush=True)
            results.append({**h, "clip_url": None, "error": message})
            continue
        if not math.isfinite(start_time) or not math.isfinite(end_time) or end_time <= start_time:
            message = "invalid highlight timestamps: end_time must be after start_time"
            print(f"[clip/local] {i} failed: {message}", flush=True)
            results.append({**h, "clip_url": None, "error": message})
            continue
        captions_for_clip = burn_captions and _has_caption_window(start_time, end_time, caption_segments)
        try:
            crop_clip_local(
                source_path,
                start_time,
                end_time,
                aspect_ratio,
                out_path,
                caption_segments=caption_segments,
                burn_captions=burn_captions,
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
                layout=layout,
                intro=intro,
                outro=outro,
                jump_cuts=jump_cuts,
                output_height=output_height,
            )
            item = {**h, "clip_url": out_path}
            try:
                from .visual import extract_thumbnail

                thumbnail_path = os.path.join(out_dir, f"short_{i:02d}.jpg")
                extract_thumbnail(
                    source_path,
                    (start_time + end_time) / 2.0,
                    thumbnail_path,
                    text=h.get("hook_sentence") or h.get("title") or "",
                )
                item["thumbnail_path"] = thumbnail_path
            except Exception as exc:
                print(f"[thumbnail/local] {i} skipped: {exc}", flush=True)
            if captions_for_clip:
                item["captions_burned"] = True
            results.append(item)
        except Exception as e:
            print(f"[clip/local] {i} failed: {e}", flush=True)
            if not preexisting_output and os.path.isfile(out_path):
                try:
                    _remove_with_retry(out_path)
                except OSError:
                    pass
            results.append({**h, "clip_url": None, "error": str(e)})
    return results
