"""High-performance multi-mode vertical clipper with hardware acceleration.

Features:
- Dual-engine encoding: Auto-detects Intel Arc Quick Sync Video (h264_qsv)
  with Direct3D11 hardware acceleration, falling back to multi-threaded libx264.
- Broadcast audio mastering: EBU R128 loudness normalization (-14 LUFS, -1.5 dBFS True Peak),
  highpass rumble cut (80 Hz), and vocal presence boost (3.2 kHz).
- Studio reframing modes: split_stack, left_focus, right_focus, smart_focus, center.
- Mobile streaming optimization: BT.709 broadcast colorimetry and moov atom faststart.
"""

import os
import subprocess
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from ..config import LOCAL_OUTPUT_DIR
from .subtitles import generate_ass_file


def detect_hardware_encoder() -> Tuple[str, List[str], str]:
    """Probe system hardware to select optimal video encoder.

    Returns:
        Tuple of (encoder_name, extra_cli_flags, pixel_format_filter).
    """
    probe_cmd = [
        "ffmpeg", "-v", "error",
        "-f", "lavfi",
        "-i", "color=c=black:s=128x128:r=30:d=0.1",
        "-pix_fmt", "nv12",
        "-c:v", "h264_qsv",
        "-b:v", "1M",
        "-f", "null", "-"
    ]
    try:
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0:
            return "h264_qsv", ["-global_quality", "21", "-look_ahead", "1"], "format=nv12"
    except Exception:
        pass

    return "libx264", ["-preset", "slow", "-crf", "17", "-threads", "0"], "format=yuv420p"


def get_source_dimensions(media_path: str) -> Tuple[int, int]:
    """Retrieve video dimensions via ffprobe.

    Args:
        media_path: Path to source media file.

    Returns:
        Tuple of (width, height) in pixels.
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
    ass_path: Optional[str] = None,
    pixel_format: str = "format=nv12"
) -> str:
    """Construct FFmpeg video filtergraph with framing, separator, and subtitle burn-in.

    Args:
        src_w: Source video width in pixels.
        src_h: Source video height in pixels.
        framing: Framing mode (split_stack, left_focus, right_focus, smart_focus, center).
        ass_path: Optional path to ASS subtitle file to overlay.
        pixel_format: Pixel format filter string for encoder compatibility.

    Returns:
        FFmpeg filtergraph string.
    """
    escaped_ass = ""
    if ass_path:
        norm_path = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
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
            f"[top][bot]vstack=inputs=2,drawbox=y=959:w=1080:h=2:color=black@0.9:t=fill"
            f"{escaped_ass},{pixel_format}[v_out]"
        )
        return filtergraph

    if framing == "fit_blur":
        filtergraph = (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5,eq=brightness=-0.30[bg]; "
            f"[0:v]scale=1080:-1:flags=lanczos[fg]; "
            f"[bg][fg]overlay=0:(H-h)/2"
            f"{escaped_ass},{pixel_format}[v_out]"
        )
        return filtergraph

    if framing == "zoom_blur":
        filtergraph = (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5,eq=brightness=-0.35[bg]; "
            f"[0:v]crop=2400:1350:800:300,scale=1080:608:flags=lanczos[fg]; "
            f"[bg][fg]overlay=0:(H-h)/2"
            f"{escaped_ass},{pixel_format}[v_out]"
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

    filtergraph = f"crop={crop_w_9_16}:{src_h}:{x_pos}:0,scale=1080:1920:flags=lanczos{escaped_ass},{pixel_format}"
    return filtergraph


def render_short_clip(
    source_path: str,
    start_time: float,
    end_time: float,
    out_path: str,
    framing: str = "split_stack",
    burn_subtitles: bool = True,
    master_audio: bool = True,
    encoder_choice: str = "auto"
) -> str:
    """Render a mobile vertical Short with hardware acceleration and broadcast audio.

    Args:
        source_path: Local media file path.
        start_time: Start timestamp in seconds.
        end_time: End timestamp in seconds.
        out_path: Output file destination path.
        framing: Framing strategy (split_stack, left_focus, right_focus, smart_focus, center).
        burn_subtitles: Whether to burn animated karaoke subtitles.
        master_audio: Whether to apply EBU R128 loudness normalization and EQ.
        encoder_choice: Encoder selection ('auto', 'qsv', 'cpu').

    Returns:
        Path to rendered .mp4 file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    src_w, src_h = get_source_dimensions(source_path)

    if encoder_choice == "qsv":
        encoder, extra_enc_args, pix_fmt = "h264_qsv", ["-global_quality", "21", "-look_ahead", "1"], "format=nv12"
    elif encoder_choice == "cpu":
        encoder, extra_enc_args, pix_fmt = "libx264", ["-preset", "slow", "-crf", "17", "-threads", "0"], "format=yuv420p"
    else:
        encoder, extra_enc_args, pix_fmt = detect_hardware_encoder()

    ass_path: Optional[str] = None
    if burn_subtitles:
        stem = Path(out_path).stem
        ass_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), f"{stem}_captions.ass")
        margin_v = 480 if framing in ["split_stack", "fit_blur", "zoom_blur"] else 520
        generate_ass_file(source_path, ass_path, margin_v=margin_v)

    filtergraph = build_ffmpeg_filtergraph(
        src_w, src_h,
        framing=framing,
        ass_path=ass_path,
        pixel_format=pix_fmt
    )

    duration = end_time - start_time
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-i", source_path
    ]

    if framing in ["split_stack", "fit_blur", "zoom_blur"]:
        cmd.extend([
            "-filter_complex", filtergraph,
            "-map", "[v_out]",
            "-map", "0:a"
        ])
    else:
        cmd.extend([
            "-vf", filtergraph
        ])

    if master_audio:
        cmd.extend([
            "-af", "highpass=f=80,equalizer=f=3200:t=q:w=1.5:g=3.0,loudnorm=I=-14:LRA=11:TP=-1.5,aresample=48000",
            "-c:a", "aac",
            "-b:a", "192k"
        ])
    else:
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "192k"
        ])

    cmd.extend([
        "-c:v", encoder,
        *extra_enc_args,
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-color_range", "tv",
        "-movflags", "+faststart",
        out_path
    ])

    subprocess.run(cmd, check=True)
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    aspect_ratio: str = "9:16",
    framing: str = "split_stack",
    burn_subtitles: bool = True,
    master_audio: bool = True,
    out_dir: Optional[str] = None
) -> List[Dict]:
    """Batch render highlights into ready-to-upload vertical Shorts.

    Args:
        source_path: Local media file path.
        highlights: List of highlight dictionaries with start_time and end_time.
        aspect_ratio: Target aspect ratio string for backward compatibility.
        framing: Framing strategy.
        burn_subtitles: Whether to burn dynamic karaoke subtitles.
        master_audio: Whether to apply EBU R128 audio mastering.
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
                burn_subtitles=burn_subtitles,
                master_audio=master_audio
            )
            results.append({**h, "clip_url": out_path})
        except Exception as e:
            print(f"[clip/local] Error on clip {i}: {e}", flush=True)
            results.append({**h, "clip_url": None, "error": str(e)})

    return results
