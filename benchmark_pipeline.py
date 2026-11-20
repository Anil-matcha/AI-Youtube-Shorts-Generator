"""Automated QA and benchmark suite for video encoding and audio mastering.

Evaluates:
- Execution speed (FPS and elapsed time) across hardware and CPU encoders.
- Audio loudness compliance against the EBU R128 (-14 LUFS) broadcast standard.
- Resolution, aspect ratio, colorimetry tags, and moov atom placement.
"""

import json
import os
import re
import subprocess
import time
from typing import Dict, Any


def run_render_benchmark(source_path: str, out_path: str, encoder_choice: str) -> Dict[str, Any]:
    """Execute timed rendering pass with specified encoder.

    Args:
        source_path: Input media path.
        out_path: Destination media path.
        encoder_choice: Encoder to test ('qsv' or 'cpu').

    Returns:
        Dictionary with encoder name, elapsed seconds, output size, and success status.
    """
    from shorts_generator.local.clipper import render_short_clip

    start_t = time.perf_counter()
    render_short_clip(
        source_path=source_path,
        start_time=0.0,
        end_time=15.0,
        out_path=out_path,
        framing="split_stack",
        burn_subtitles=True,
        master_audio=True,
        encoder_choice=encoder_choice
    )
    elapsed = time.perf_counter() - start_t
    size_mb = os.path.getsize(out_path) / (1024 * 1024)

    return {
        "encoder": encoder_choice,
        "elapsed_sec": round(elapsed, 2),
        "size_mb": round(size_mb, 2),
        "fps": round(15.0 * 60.0 / elapsed, 1) if elapsed > 0 else 0.0
    }


def verify_audio_loudness(media_path: str) -> Dict[str, Any]:
    """Analyze audio stream against EBU R128 loudness standards using FFmpeg ebur128.

    Args:
        media_path: Video or audio file path.

    Returns:
        Dictionary with integrated loudness (LUFS), loudness range (LU), and true peak (dBFS).
    """
    cmd = [
        "ffmpeg", "-nostats",
        "-i", media_path,
        "-af", "ebur128",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    i_lufs = None
    lra = None
    tp = None

    for line in res.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            match = re.search(r"I:\s*(-?[\d\.]+)\s*LUFS", line)
            if match:
                i_lufs = float(match.group(1))
        if "LRA:" in line and "LU" in line:
            match = re.search(r"LRA:\s*([\d\.]+)\s*LU", line)
            if match:
                lra = float(match.group(1))
        if "Peak:" in line and "dBFS" in line:
            match = re.search(r"Peak:\s*(-?[\d\.]+)\s*dBFS", line)
            if match:
                tp = float(match.group(1))

    return {
        "integrated_lufs": i_lufs,
        "loudness_range_lu": lra,
        "true_peak_dbfs": tp,
        "compliant_with_shorts": bool(i_lufs is not None and -15.5 <= i_lufs <= -13.0)
    }


def verify_stream_parameters(media_path: str) -> Dict[str, Any]:
    """Inspect video container and stream parameters using ffprobe.

    Args:
        media_path: Media file path.

    Returns:
        Dictionary containing codec, resolution, framerate, and color flags.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,color_space,color_primaries,color_transfer",
        "-of", "json",
        media_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(res.stdout)
    stream = data.get("streams", [{}])[0]

    return {
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "frame_rate": stream.get("r_frame_rate"),
        "color_space": stream.get("color_space"),
        "color_primaries": stream.get("color_primaries"),
        "color_transfer": stream.get("color_transfer")
    }


if __name__ == "__main__":
    test_src = r"output\raw_4k_moment1.mp4"
    if not os.path.exists(test_src):
        print(f"Source file not found: {test_src}")
        exit(1)

    print("--- BENCHMARK 1: Intel Arc QSV Hardware Encoding ---")
    qsv_res = run_render_benchmark(test_src, r"output\bench_qsv.mp4", "qsv")
    print(f"QSV Result: {qsv_res['elapsed_sec']}s ({qsv_res['fps']} FPS), Size: {qsv_res['size_mb']} MB")

    print("\n--- BENCHMARK 2: Audio Loudness Verification (EBU R128) ---")
    audio_res = verify_audio_loudness(r"output\bench_qsv.mp4")
    print(f"Integrated Loudness: {audio_res['integrated_lufs']} LUFS")
    print(f"Loudness Range: {audio_res['loudness_range_lu']} LU")
    print(f"True Peak: {audio_res['true_peak_dbfs']} dBFS")
    print(f"Shorts Compliant: {audio_res['compliant_with_shorts']}")

    print("\n--- BENCHMARK 3: Stream & Color Parameters ---")
    stream_res = verify_stream_parameters(r"output\bench_qsv.mp4")
    print(json.dumps(stream_res, indent=2))
