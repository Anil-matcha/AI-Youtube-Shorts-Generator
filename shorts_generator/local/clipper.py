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

from ..config import LOCAL_OUTPUT_DIR, RAW_CAPTIONS_DIR
from ..clip_registry import ClipRegistry
from ..diversity_types import CandidateHighlight, FramingMode, HighlightArchetype, ZoomPlan
from ..framing_analyzer import FramingAnalyzer
from ..viral_zoom_analyzer import ViralZoomAnalyzer
from .subtitles import generate_ass_file


def detect_hardware_encoder() -> Tuple[str, List[str], str]:
    """Probe system hardware to select optimal video encoder.

    Returns:
        Tuple of (encoder_name, extra_cli_flags, pixel_format_filter).
    """
    return get_encoder_config(encoder_choice="auto", resolution="4k")


def get_encoder_config(encoder_choice: str = "auto", resolution: str = "4k") -> Tuple[str, List[str], str]:
    """Select optimal video encoder and high-bitrate flags for broadcast quality.

    Args:
        encoder_choice: Encoder selection ('auto', 'qsv', 'cpu').
        resolution: Target resolution profile ('4k' or '1080p').

    Returns:
        Tuple of (encoder_name, extra_cli_flags, pixel_format_filter).
    """
    is_4k = (resolution or "4k").lower() == "4k"

    if encoder_choice in ("auto", "qsv"):
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
                if is_4k:
                    qsv_flags = ["-global_quality", "16", "-b:v", "35M", "-maxrate", "50M", "-bufsize", "60M", "-look_ahead", "1"]
                else:
                    qsv_flags = ["-global_quality", "18", "-b:v", "15M", "-maxrate", "25M", "-bufsize", "30M", "-look_ahead", "1"]
                return "h264_qsv", qsv_flags, "format=nv12"
        except Exception:
            pass

    if is_4k:
        cpu_flags = ["-preset", "medium", "-crf", "16", "-b:v", "30M", "-maxrate", "45M", "-bufsize", "60M", "-threads", "0"]
    else:
        cpu_flags = ["-preset", "slow", "-crf", "17", "-b:v", "15M", "-maxrate", "25M", "-bufsize", "30M", "-threads", "0"]
    return "libx264", cpu_flags, "format=yuv420p"


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
    pixel_format: str = "format=nv12",
    resolution: str = "4k",
    framing_params: Optional[Dict] = None,
) -> str:
    """Construct FFmpeg video filtergraph with framing, separator, zoom, and subtitle burn-in.

    Args:
        src_w: Source video width in pixels.
        src_h: Source video height in pixels.
        framing: Framing mode (split_stack, left_focus, right_focus, smart_focus, center, fit_blur, zoom_blur).
        ass_path: Optional path to ASS subtitle file to overlay.
        pixel_format: Pixel format filter string for encoder compatibility.
        resolution: Target resolution profile ('4k' for 2160x3840 or '1080p' for 1080x1920).
        framing_params: Optional dictionary of fine-tuned spatial coordinates, ratios, and dynamic zoom plans.

    Returns:
        FFmpeg filtergraph string.
    """
    escaped_ass = ""
    if ass_path:
        norm_path = os.path.abspath(ass_path).replace("\\", "/").replace(":", "\\:")
        escaped_ass = f",ass='{norm_path}'"

    is_4k = (resolution or "4k").lower() == "4k"
    out_w = 2160 if is_4k else 1080
    out_h = 3840 if is_4k else 1920

    crop_w_9_16 = int(src_h * (out_w / out_h))
    crop_w_9_16 = max(2, crop_w_9_16 - (crop_w_9_16 % 2))

    zoom_plan = framing_params.get("zoom_plan", None) if framing_params else None
    focal_x = framing_params.get("focal_x", 0.5) if framing_params else 0.5
    focal_y = framing_params.get("focal_y", 0.45) if framing_params else 0.45

    if framing == "split_stack":
        sub_ratio = framing_params.get("sub_h_ratio", 0.72) if framing_params else 0.72
        sub_h = int(src_h * sub_ratio)
        sub_w = int(sub_h * (out_w / (out_h // 2)))
        sub_w = max(2, sub_w - (sub_w % 2))
        sub_h = max(2, sub_h - (sub_h % 2))

        def_x_left = max(0, int(src_w * 0.08))
        def_x_right = min(src_w - sub_w, int(src_w * 0.46))
        def_y = int((src_h - sub_h) * 0.35)

        x_top = framing_params.get("x_top", def_x_left) if framing_params else def_x_left
        x_bot = framing_params.get("x_bot", def_x_right) if framing_params else def_x_right
        y_top = framing_params.get("y_top", def_y) if framing_params else def_y
        y_bot = framing_params.get("y_bot", def_y) if framing_params else def_y

        half_h = out_h // 2
        line_y = half_h - 1
        line_thick = 4 if is_4k else 2

        zoom_plan_top = framing_params.get("zoom_plan_top", zoom_plan) if framing_params else zoom_plan
        zoom_plan_bot = framing_params.get("zoom_plan_bot", None) if framing_params else None

        crop_top = ViralZoomAnalyzer.build_crop_filter_with_zoom(sub_w, sub_h, x_top, y_top, zoom_plan_top, focal_x, focal_y)
        crop_bot = ViralZoomAnalyzer.build_crop_filter_with_zoom(sub_w, sub_h, x_bot, y_bot, zoom_plan_bot, focal_x, focal_y)

        filtergraph = (
            f"[0:v]{crop_top},scale={out_w}:{half_h}:flags=lanczos[top]; "
            f"[0:v]{crop_bot},scale={out_w}:{half_h}:flags=lanczos[bot]; "
            f"[top][bot]vstack=inputs=2,drawbox=y={line_y}:w={out_w}:h={line_thick}:color=black@0.9:t=fill"
            f"{escaped_ass},{pixel_format}[v_out]"
        )
        return filtergraph

    if framing == "fit_blur":
        box_blur = "50:10" if is_4k else "25:5"
        filtergraph = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},boxblur={box_blur},eq=brightness=-0.30[bg]; "
            f"[0:v]scale={out_w}:-1:flags=lanczos[fg]; "
            f"[bg][fg]overlay=0:(H-h)/2"
            f"{escaped_ass},{pixel_format}[v_out]"
        )
        return filtergraph

    if framing == "zoom_blur":
        box_blur = "50:10" if is_4k else "25:5"
        fg_crop_w = int(src_w * 0.625)
        fg_crop_h = int(fg_crop_w * (9 / 16))
        fg_crop_w = max(2, fg_crop_w - (fg_crop_w % 2))
        fg_crop_h = max(2, fg_crop_h - (fg_crop_h % 2))
        fg_crop_x = int(src_w * 0.208)
        fg_crop_y = int(src_h * 0.138)
        fg_h = int(out_w * (9 / 16))
        fg_h = max(2, fg_h - (fg_h % 2))

        filtergraph = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},boxblur={box_blur},eq=brightness=-0.35[bg]; "
            f"[0:v]crop={fg_crop_w}:{fg_crop_h}:{fg_crop_x}:{fg_crop_y},scale={out_w}:{fg_h}:flags=lanczos[fg]; "
            f"[bg][fg]overlay=0:(H-h)/2"
            f"{escaped_ass},{pixel_format}[v_out]"
        )
        return filtergraph

    if framing == "left_focus":
        x_pos = max(0, int(src_w * 0.18))
        crop_filter = ViralZoomAnalyzer.build_crop_filter_with_zoom(crop_w_9_16, src_h, x_pos, 0, zoom_plan, focal_x, focal_y)
        return f"{crop_filter},scale={out_w}:{out_h}:flags=lanczos{escaped_ass},{pixel_format}"

    if framing == "right_focus":
        x_pos = min(src_w - crop_w_9_16, int(src_w * 0.48))
        crop_filter = ViralZoomAnalyzer.build_crop_filter_with_zoom(crop_w_9_16, src_h, x_pos, 0, zoom_plan, focal_x, focal_y)
        return f"{crop_filter},scale={out_w}:{out_h}:flags=lanczos{escaped_ass},{pixel_format}"

    if framing == "smart_focus":
        strip_letterbox = framing_params.get("strip_letterbox", False) if framing_params else False
        if strip_letterbox:
            active_h = framing_params.get("active_h", int(src_h * 0.88)) if framing_params else int(src_h * 0.88)
            active_h = max(2, active_h - (active_h % 2))
            crop_w = int(active_h * (out_w / out_h))
            crop_w = max(2, crop_w - (crop_w % 2))
            y_offset = framing_params.get("y_offset", (src_h - active_h) // 2) if framing_params else (src_h - active_h) // 2
            x_ratio = framing_params.get("x_ratio", 0.30) if framing_params else 0.30
            x_pos = max(0, min(src_w - crop_w, int(src_w * x_ratio)))
            crop_filter = ViralZoomAnalyzer.build_crop_filter_with_zoom(crop_w, active_h, x_pos, y_offset, zoom_plan, focal_x, focal_y)
            return f"{crop_filter},scale={out_w}:{out_h}:flags=lanczos{escaped_ass},{pixel_format}"
        x_ratio = framing_params.get("x_ratio", 0.28) if framing_params else 0.28
        x_pos = max(0, min(src_w - crop_w_9_16, int(src_w * x_ratio)))
        crop_filter = ViralZoomAnalyzer.build_crop_filter_with_zoom(crop_w_9_16, src_h, x_pos, 0, zoom_plan, focal_x, focal_y)
        return f"{crop_filter},scale={out_w}:{out_h}:flags=lanczos{escaped_ass},{pixel_format}"

    x_pos = (src_w - crop_w_9_16) // 2
    crop_filter = ViralZoomAnalyzer.build_crop_filter_with_zoom(crop_w_9_16, src_h, x_pos, 0, zoom_plan, focal_x, focal_y)
    return f"{crop_filter},scale={out_w}:{out_h}:flags=lanczos{escaped_ass},{pixel_format}"


def render_short_clip(
    source_path: str,
    start_time: float,
    end_time: float,
    out_path: str,
    framing: str = "split_stack",
    burn_subtitles: bool = True,
    master_audio: bool = True,
    encoder_choice: str = "auto",
    resolution: str = "4k",
    framing_params: Optional[Dict] = None,
) -> str:
    """Render a mobile vertical Short with hardware acceleration and broadcast audio.

    Args:
        source_path: Local media file path.
        start_time: Start timestamp in seconds.
        end_time: End timestamp in seconds.
        out_path: Output file destination path.
        framing: Framing strategy (split_stack, left_focus, right_focus, smart_focus, center, fit_blur, zoom_blur).
        burn_subtitles: Whether to burn animated karaoke subtitles.
        master_audio: Whether to apply EBU R128 loudness normalization and EQ.
        encoder_choice: Encoder selection ('auto', 'qsv', 'cpu').
        resolution: Output resolution profile ('4k' for 2160x3840 or '1080p' for 1080x1920).
        framing_params: Optional dictionary of fine-tuned spatial coordinates and ratios.

    Returns:
        Path to rendered .mp4 file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    src_w, src_h = get_source_dimensions(source_path)

    is_4k = (resolution or "4k").lower() == "4k"
    target_w = 2160 if is_4k else 1080
    target_h = 3840 if is_4k else 1920

    encoder, extra_enc_args, pix_fmt = get_encoder_config(encoder_choice, resolution=resolution)

    ass_path: Optional[str] = None
    if burn_subtitles:
        stem = Path(out_path).stem
        ass_path = os.path.join(RAW_CAPTIONS_DIR, f"{stem}_captions.ass")
        default_margin_v = 940 if framing == "split_stack" else 520
        margin_v = framing_params.get("margin_v", default_margin_v) if framing_params else default_margin_v
        generate_ass_file(source_path, ass_path, margin_v=margin_v, target_w=target_w, target_h=target_h)

    filtergraph = build_ffmpeg_filtergraph(
        src_w, src_h,
        framing=framing,
        ass_path=ass_path,
        pixel_format=pix_fmt,
        resolution=resolution,
        framing_params=framing_params,
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
        fade_out_st = max(0.0, duration - 0.03)
        af_chain = (
            f"afade=t=in:ss=0:d=0.02,afade=t=out:st={fade_out_st:.3f}:d=0.03,"
            "highpass=f=80,equalizer=f=3200:t=q:w=1.5:g=3.0,loudnorm=I=-14:LRA=11:TP=-1.5,aresample=48000"
        )
        cmd.extend([
            "-af", af_chain,
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
    out_dir: Optional[str] = None,
    video_id: Optional[str] = None,
    resolution: str = "4k",
    transcript_segments: Optional[List[Dict]] = None,
    auto_framing: bool = True,
    auto_zoom: bool = True,
) -> List[Dict]:
    """Batch render highlights into ready-to-upload vertical Shorts with monotonic registry tracking.

    Args:
        source_path: Local media file path.
        highlights: List of highlight dictionaries with start_time and end_time.
        aspect_ratio: Target aspect ratio string for backward compatibility.
        framing: Framing strategy.
        burn_subtitles: Whether to burn dynamic karaoke subtitles.
        master_audio: Whether to apply EBU R128 audio mastering.
        out_dir: Output directory path.
        video_id: Optional video identifier for persistent sequence indexing.
        resolution: Output resolution profile ('4k' or '1080p').
        transcript_segments: Optional Whisper transcript segments for intelligent framing.
        auto_framing: Whether to automatically analyze and recommend framing for clips.
        auto_zoom: Whether to automatically schedule dynamic viral zoom-ins on impactful moments.

    Returns:
        List of processed highlight dictionaries with clip_url paths.
    """
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict] = []
    registry = ClipRegistry()
    vid = video_id or Path(source_path).stem
    src_dims = get_source_dimensions(source_path)

    framing_analyzer = FramingAnalyzer(target_resolution=resolution) if auto_framing else None
    zoom_analyzer = ViralZoomAnalyzer() if auto_zoom else None

    for i, h in enumerate(highlights, 1):
        archetype_str = str(h.get("archetype", "HIGHLIGHT")).upper()
        archetype_enum = HighlightArchetype.from_string(archetype_str)
        clip_framing = h.get("framing", framing)
        clip_framing_params = dict(h.get("framing_params") or {})

        candidate = CandidateHighlight(
            title=str(h.get("title", "")),
            raw_start=float(h["start_time"]),
            raw_end=float(h["end_time"]),
            score=int(h.get("score", 0)),
            archetype=archetype_enum,
            hook_sentence=str(h.get("hook_sentence", "")),
            virality_reason=str(h.get("virality_reason", "")),
            snapped_start=float(h.get("snapped_start", h["start_time"])),
            snapped_end=float(h.get("snapped_end", h["end_time"])),
            is_snapped=bool(h.get("is_snapped", False)),
        )

        if auto_framing and framing_analyzer and (clip_framing in ("auto", None) or not clip_framing_params):
            rec = framing_analyzer.recommend_framing(
                highlight=candidate,
                transcript_segments=transcript_segments,
                source_dimensions=src_dims,
            )
            if clip_framing in ("auto", None):
                clip_framing = rec.mode
            clip_framing_params = {**rec.params, **clip_framing_params}

        if auto_zoom and zoom_analyzer and "zoom_plan" not in clip_framing_params:
            z_plan = zoom_analyzer.plan_zooms(candidate)
            if z_plan.events:
                clip_framing_params["zoom_plan"] = z_plan

        seq = registry.get_next_sequence_number(vid)
        out_path = os.path.join(out_dir, f"short_{vid}_{seq:03d}_{archetype_str}.mp4")
        print(f"[clip/local] Rendering {i}/{len(highlights)}: {h.get('title', '(untitled)')} [{clip_framing}] ({resolution}) -> {Path(out_path).name}", flush=True)
        try:
            render_short_clip(
                source_path=source_path,
                start_time=float(h["start_time"]),
                end_time=float(h["end_time"]),
                out_path=out_path,
                framing=clip_framing,
                burn_subtitles=burn_subtitles,
                master_audio=master_audio,
                resolution=resolution,
                framing_params=clip_framing_params,
            )
            registry.register_clip(
                video_id=vid,
                start_time=float(h["start_time"]),
                end_time=float(h["end_time"]),
                guard_band=45.0,
                archetype=archetype_str,
                score=int(h.get("score", 0)),
                title=str(h.get("title", "")),
                hook_sentence=str(h.get("hook_sentence", "")),
                file_path=out_path
            )
            results.append({
                **h,
                "clip_url": out_path,
                "framing": clip_framing,
                "framing_params": clip_framing_params,
            })
        except Exception as e:
            print(f"[clip/local] Error on clip {i}: {e}", flush=True)
            results.append({**h, "clip_url": None, "error": str(e)})

    return results
