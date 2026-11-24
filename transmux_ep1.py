"""Transmux Episode 1 MKV container to YouTube-optimized MP4 container losslessly.

Zero re-encoding, 100% pristine original 4K 60FPS video quality,
adds +faststart moov atom for instantaneous YouTube web upload and playback.
"""

import os
import subprocess
import time

INPUT_MKV = r"C:\Users\techd\Videos\DO NOT MISS THIS IN GTA 6! Jason's House Repair Guide (Ep. 1).mkv"
OUTPUT_MP4 = r"C:\Users\techd\Videos\GTA_6_Episode_1_4K_Master.mp4"

def transmux():
    if not os.path.exists(INPUT_MKV):
        print(f"Error: Master file not found at {INPUT_MKV}")
        return

    print(f"=== Starting Lossless MKV -> MP4 Transmux ===")
    print(f"Source: {INPUT_MKV}")
    print(f"Target: {OUTPUT_MP4}")

    t0 = time.time()
    cmd = [
        "ffmpeg", "-y",
        "-i", INPUT_MKV,
        "-c", "copy",
        "-movflags", "+faststart",
        OUTPUT_MP4
    ]
    subprocess.run(cmd, check=True)
    size_gb = os.path.getsize(OUTPUT_MP4) / (1024 ** 3)
    print(f"Transmux completed in {time.time() - t0:.2f}s! Master MP4: {size_gb:.2f} GB")

if __name__ == "__main__":
    transmux()
