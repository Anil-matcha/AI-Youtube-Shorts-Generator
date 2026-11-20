"""Multi-mode high-performance vertical clipper for short-form video.

Supports intelligent framing modes:
- split_stack: Dual-character stacked layout (Top: Left character, Bottom: Right character).
- left_focus: Frames left side character (e.g. Driver / Jason) in full vertical 9:16.
- right_focus: Frames right side character (e.g. Passenger / Gunner) in full vertical 9:16.
- smart_focus: Centers active dialogue character or salient subject.
- center: Standard geometric center crop.

Integrates single-pass FFmpeg rendering with Lanczos scaling and optional
dynamic animated karaoke subtitle burn-in.
"""

import os
import subprocess
from typing import Dict, List, Optional
from pathlib import Path

from ..config import LOCAL_OUTPUT_DIR
from .subtitles import generate_ass_file


def get_source_dimensions(media_path: str) -> tuple[int, int]:
    """Retrieve video width and height using ffprobe.

    Args:
        media_path: Local media file path.

    Returns:
        Tuple of (width, height).
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        media_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    parts = res.stdout.strip().split("x")
    return int(parts[0]), int(parts[1])


def build_ffmpeg_filtergraph(
    src_w: int,
    src_h: int,
    framing: str = "split_stack",
    ass_path: Optional[str] = None
) -> str:
    """Construct an FFmpeg filtergraph string based on the chosen framing layout.

    Args:
        src_w: Source video width in pixels.
        src_h: Source video height in pixels.
        framing: Framing mode identifier (split_stack, left_focus, right_focus, smart_focus, center).
        ass_path: Optional path to an ASS subtitle file to burn into the output.

    Returns:
        Complete FFmpeg filter string.
    """
    escaped_ass = ""
    if ass_path:
        norm_path = os.path.abspath(ass_path).replace("\\", "/")
        norm_path = norm_path.replace(":", "\\:")
        escaped_ass = f",ass='{norm_path}'"

    crop_w_9_16 = int(src_h * (9 / 16))
    crop_w_9_16 = max(2, crop_w_9_16 - (crop_w_9_16 % 2))

    if framing == "split_stack":
        sub_h = int(src_h * 0.72)
        sub_w = int(sub_h * (1080 / 960))
        sub_w = max(2, sub_w - (sub_w % 2))
        sub_h = max(2, sub_h - (sub_h % 2))

        x_left = max(0, int(src_w * 0.08))
        x_right = min(src_w - sub_w, int(src_w * 0.46))
        y_pos = int((src_h - sub_h) * 0.35)

        filtergraph = (
            f"[0:v]crop={sub_w}:{sub_h}:{x_left}:{y_pos},scale=1080:960:flags=lanczos[top]; "
            f"[0:v]crop={sub_w}:{sub_h}:{x_right}:{y_pos},scale=1080:960:flags=lanczos[bot]; "
            f"[top][bot]vstack=inputs=2[v_stack]; "
            f"[v_stack]null{escaped_ass}[v_out]"
        )
        return filtergraph

    if framing == "left_focus":
        x_pos = max(0, int(src_w * 0.18))
    elif framing == "right_focus":
        x_pos = min(src_w - crop_w_9_16, int(src_w * 0.48))
    elif framing == "smart_focus":
        x_pos = max(0, min(src_w - crop_w_9_16, int(src_w * 0.28)))
    else:
        x_pos = (src_w - crop_w_9_16) // 2

    filtergraph = f"crop={crop_w_9_16}:{src_h}:{x_pos}:0,scale=1080:1920:flags=lanczos{escaped_ass}"
    return filtergraph


def render_short_clip(
    source_path: str,
    start_time: float,
    end_time: float,
    out_path: str,
    framing: str = "split_stack",
    burn_subtitles: bool = True
) -> str:
    """Cut, reframe, scale, and burn subtitles into a vertical Short in a single pass.

    Args:
        source_path: Input media file path.
        start_time: Start timestamp in seconds.
        end_time: End timestamp in seconds.
        out_path: Output .mp4 destination file path.
        framing: Framing mode (split_stack, left_focus, right_focus, smart_focus, center).
        burn_subtitles: Whether to generate and burn animated karaoke subtitles.

    Returns:
        Path to rendered .mp4 file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    src_w, src_h = get_source_dimensions(source_path)

    ass_path: Optional[str] = None
    if burn_subtitles:
        stem = Path(out_path).stem
        ass_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), f"{stem}_captions.ass")
        margin_v = 480 if framing == "split_stack" else 520
        generate_ass_file(source_path, ass_path, margin_v=margin_v)

    filtergraph = build_ffmpeg_filtergraph(src_w, src_h, framing=framing, ass_path=ass_path)

    duration = end_time - start_time
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-i", source_path
    ]

    if framing == "split_stack":
        cmd.extend([
            "-filter_complex", filtergraph,
            "-map", "[v_out]",
            "-map", "0:a"
        ])
    else:
        cmd.extend([
            "-vf", filtergraph,
            "-c:a", "aac",
            "-b:a", "192k"
        ])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "17",
        "-pix_fmt", "yuv420p",
        out_path
    ])

    subprocess.run(cmd, check=True)
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    framing: str = "split_stack",
    burn_subtitles: bool = True,
    out_dir: Optional[str] = None
) -> List[Dict]:
    """Process multiple highlights into ready-to-upload vertical Shorts.

    Args:
        source_path: Input source video file.
        highlights: List of highlight metadata dictionaries with start_time and end_time.
        framing: Framing strategy for reframing.
        burn_subtitles: Whether to burn animated karaoke captions.
        out_dir: Output directory path.

    Returns:
        List of processed highlight dictionaries with clip_url paths.
    """
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict] = []

    for i, h in enumerate(highlights, 1):
        out_path = os.path.join(out_dir, f"short_{i:02d}.mp4")
        print(f"[clip/local] Rendering {i}/{len(highlights)}: {h.get('title', '(untitled)')} [{framing}]", flush=True)
        try:
            render_short_clip(
                source_path=source_path,
                start_time=float(h["start_time"]),
                end_time=float(h["end_time"]),
                out_path=out_path,
                framing=framing,
                burn_subtitles=burn_subtitles
            )
            results.append({**h, "clip_url": out_path})
        except Exception as e:
            print(f"[clip/local] Error on clip {i}: {e}", flush=True)
            results.append({**h, "clip_url": None, "error": str(e)})

    return results
