"""Download targeted 4K slice directly from cached GoogleVideo manifests.

Uses cached HLS manifest URLs from output/raw/video/ep2_video_info.json,
bypassing YouTube rate limits and streaming slices at hardware speed into output/raw/video/.
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Optional

from shorts_generator.paths import resolve_raw_video_path


def download_slice(start_time: str, end_time: str, out_filename: str) -> str:
    """Download a time slice using direct GoogleVideo HLS streams.

    Args:
        start_time: Timestamp string (e.g. '00:18:02' or '00:53:35').
        end_time: Timestamp string (e.g. '00:18:35' or '00:54:32').
        out_filename: Base output filename (e.g. 'ep2_raw_4k_moment5.mp4').

    Returns:
        Absolute destination path in output/raw/video/.

    Raises:
        RuntimeError: If formats 628 or 234 are not present in the cached manifest.
    """
    manifest_path = Path("output/raw/video/ep2_video_info.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    v_url = None
    a_url = None
    for fmt in data.get("formats", []):
        if fmt.get("format_id") == "628":
            v_url = fmt.get("url")
        elif fmt.get("format_id") == "234":
            a_url = fmt.get("url")

    if not v_url or not a_url:
        raise RuntimeError("Could not find formats 628/234 in ep2_video_info.json")

    dest_path = resolve_raw_video_path(out_filename)
    cmd = [
        "ffmpeg", "-y",
        "-ss", start_time,
        "-to", end_time,
        "-i", v_url,
        "-ss", start_time,
        "-to", end_time,
        "-i", a_url,
        "-c:v", "copy",
        "-c:a", "copy",
        dest_path
    ]

    t0 = time.time()
    print(f"Downloading slice {start_time} -> {end_time} to {dest_path}...", flush=True)
    subprocess.run(cmd, check=True)
    print(f"Downloaded in {time.time() - t0:.2f} seconds.", flush=True)
    return dest_path


if __name__ == "__main__":
    download_slice("00:18:02", "00:18:35", "ep2_raw_4k_moment5.mp4")
