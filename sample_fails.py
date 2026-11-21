"""Sample visual frames from gameplay chase and free-roam sections to identify stunts, crashes, and noob fails."""

import os
import subprocess
import time
from pathlib import Path

from render_ep3_all_shorts import get_stream_urls, format_hms

OUTPUT_DIR = Path("output/fail_samples")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Timestamps to sample for stunts, car chase, crashes, and noob gameplay:
# 1355 to 1720: Car getaway from Arnold's turf
# 2000 to 2700: Free roam, police chase, street driving
SAMPLE_TIMES = [
    1365, 1400, 1450, 1500, 1550, 1600, 1650, 1700,
    2050, 2120, 2200, 2280, 2350, 2420, 2500, 2580, 2650,
    3420, 3440
]

def main() -> None:
    v_url, _ = get_stream_urls()
    print(f"Sampling {len(SAMPLE_TIMES)} gameplay frames...")
    for t in SAMPLE_TIMES:
        out_jpg = OUTPUT_DIR / f"frame_{t}s.jpg"
        if out_jpg.exists():
            continue
        ts_str = format_hms(t)
        cmd = [
            "ffmpeg", "-y",
            "-ss", ts_str,
            "-i", v_url,
            "-vframes", "1",
            "-q:v", "3",
            str(out_jpg)
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            print(f"[+] Sampled {ts_str} -> {out_jpg.name}")
        except Exception as e:
            print(f"[-] Failed at {ts_str}: {e}")

if __name__ == "__main__":
    main()
