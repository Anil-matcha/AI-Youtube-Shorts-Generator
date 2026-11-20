"""Download targeted 4K slice directly from cached GoogleVideo manifests.

Uses cached HLS manifest URLs from ep2_video_info.json, bypassing YouTube rate limits.
"""

import json
import subprocess
import time


def download_slice(start_time: str, end_time: str, out_path: str) -> None:
    """Download a time slice using direct GoogleVideo HLS streams.

    Args:
        start_time: Timestamp string (e.g. '00:53:35').
        end_time: Timestamp string (e.g. '00:54:32').
        out_path: Output .mp4 destination.
    """
    with open("output/ep2_video_info.json", "r", encoding="utf-8-sig") as f:
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
        out_path
    ]

    t0 = time.time()
    print(f"Downloading slice {start_time} -> {end_time} to {out_path}...", flush=True)
    subprocess.run(cmd, check=True)
    print(f"Downloaded in {time.time() - t0:.2f} seconds.", flush=True)


if __name__ == "__main__":
    download_slice("00:53:35", "00:54:32", "output/ep2_raw_4k_moment3.mp4")
