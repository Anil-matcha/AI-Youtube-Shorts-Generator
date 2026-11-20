"""Master rendering pipeline for all Episode 2 4K 60FPS vertical YouTube Shorts.

Downloads 4K slices to output/raw/video/ and renders finalized master shorts
directly into output/ using Intel Arc QSV, Whisper karaoke subtitles, and EBU R128 mastering.
"""

import os
import subprocess
import time
from typing import Dict, List

from download_direct_slice import download_slice
from shorts_generator.local.clipper import render_short_clip
from shorts_generator.paths import (
    ensure_output_dirs,
    resolve_final_short_path,
    resolve_raw_video_path,
)

SHORTS_SPECS: List[Dict] = [
    {
        "id": 1,
        "name": "Leonida Tourism Life Jacket Warning",
        "start": "00:05:00",
        "end": "00:05:30",
        "framing": "fit_blur",
        "raw_slice": "ep2_raw_4k_moment1.mp4",
        "out_name": "ep2_short_1_4K_mastered.mp4",
    },
    {
        "id": 2,
        "name": "Jason's Mercenary Past",
        "start": "00:18:50",
        "end": "00:19:40",
        "framing": "center",
        "raw_slice": "ep2_raw_4k_moment2.mp4",
        "out_name": "ep2_short_2_4K_mastered.mp4",
    },
    {
        "id": 3,
        "name": "Collecting Brian's Rent (Hippie Beatdown)",
        "start": "00:53:35",
        "end": "00:54:32",
        "framing": "zoom_blur",
        "raw_slice": "ep2_raw_4k_moment3.mp4",
        "out_name": "ep2_short_3_4K_mastered.mp4",
    },
    {
        "id": 4,
        "name": "High School Weed Dealer Energy",
        "start": "00:20:45",
        "end": "00:21:12",
        "framing": "smart_focus",
        "raw_slice": "ep2_raw_4k_moment4.mp4",
        "out_name": "ep2_short_4_4K_mastered.mp4",
    },
    {
        "id": 5,
        "name": "The 20-Pound Weed Impound Heist",
        "start": "00:18:02",
        "end": "00:18:32",
        "framing": "smart_focus",
        "raw_slice": "ep2_raw_4k_moment5.mp4",
        "out_name": "ep2_short_5_4K_mastered.mp4",
    },
    {
        "id": 6,
        "name": "Hopper Crematory TV Ad Satire",
        "start": "00:04:45",
        "end": "00:05:02",
        "framing": "fit_blur",
        "raw_slice": "ep2_raw_4k_moment6.mp4",
        "out_name": "ep2_short_6_4K_mastered.mp4",
    },
    {
        "id": 7,
        "name": "Mandy's Secret Mission: She ONLY Wants You",
        "start": "00:45:15",
        "end": "00:45:36",
        "framing": "smart_focus",
        "raw_slice": "ep2_raw_4k_moment7.mp4",
        "out_name": "ep2_short_7_4K_mastered.mp4",
    },
    {
        "id": 8,
        "name": "Secret Underground Safe Code: 7700",
        "start": "00:56:00",
        "end": "00:56:29",
        "framing": "smart_focus",
        "raw_slice": "ep2_raw_4k_moment8.mp4",
        "out_name": "ep2_short_8_4K_mastered.mp4",
    },
]


def run_pipeline():
    """Execute download and render pipeline for all 8 viral shorts."""
    ensure_output_dirs()
    total_start = time.time()

    print(f"=== Starting Master Pipeline for {len(SHORTS_SPECS)} Shorts ===", flush=True)
    for spec in SHORTS_SPECS:
        s_id = spec["id"]
        raw_path = resolve_raw_video_path(spec["raw_slice"])
        final_path = resolve_final_short_path(spec["out_name"])

        if not os.path.exists(raw_path):
            print(f"\n[{s_id}/8] Downloading 4K slice for '{spec['name']}'...", flush=True)
            download_slice(spec["start"], spec["end"], spec["raw_slice"])
        else:
            print(f"\n[{s_id}/8] Raw slice already present at {raw_path}", flush=True)

        print(f"[{s_id}/8] Rendering Master Short to {final_path} [{spec['framing']}]...", flush=True)
        t_render = time.time()

        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", raw_path]
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True, check=True)
        dur = float(res.stdout.strip())

        render_short_clip(
            source_path=raw_path,
            start_time=0.0,
            end_time=dur,
            out_path=final_path,
            framing=spec["framing"],
            burn_subtitles=True,
            master_audio=True,
            resolution="4k",
        )
        print(f"[{s_id}/8] Rendered in {time.time() - t_render:.2f} seconds!", flush=True)

    print(f"\n=== All {len(SHORTS_SPECS)} Shorts Mastered Successfully in {time.time() - total_start:.2f}s ===", flush=True)


if __name__ == "__main__":
    run_pipeline()
