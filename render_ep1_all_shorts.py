"""Master rendering pipeline for all Episode 1 4K 60FPS vertical YouTube Shorts.

Extracts 4K slices directly from local source video and renders finalized master shorts
directly into output/ using Intel Arc QSV hardware acceleration, Whisper subtitles,
and broadcast audio mastering (EBU R128).
"""

import os
import subprocess
import time
from typing import Dict, List

from shorts_generator.local.clipper import render_short_clip
from shorts_generator.paths import (
    ensure_output_dirs,
    resolve_final_short_path,
    resolve_raw_video_path,
)

SOURCE_VIDEO = r"C:\Users\techd\Videos\DO NOT MISS THIS IN GTA 6! Jason's House Repair Guide (Ep. 1).mkv"

SHORTS_SPECS: List[Dict] = [
    {
        "id": 1,
        "name": "Lucia Parole Grill & Criminal Record Roast",
        "start": 88.0,
        "end": 128.0,
        "framing": "split_stack",
        "framing_params": {"x_top": 1850, "y_top": 120, "x_bot": 450, "y_bot": 120, "sub_h_ratio": 0.72, "margin_v": 940},
        "raw_slice": "ep1_raw_4k_moment1.mp4",
        "out_name": "ep1_short_1_Lucia_Parole_Grill_4K.mp4",
    },
    {
        "id": 2,
        "name": "VPN & Red Light Running Philosophy",
        "start": 241.0,
        "end": 269.0,
        "framing": "smart_focus",
        "framing_params": {"x_ratio": 0.33, "margin_v": 520},
        "raw_slice": "ep1_raw_4k_moment2.mp4",
        "out_name": "ep1_short_2_VPN_Driving_Philosophy_4K.mp4",
    },
    {
        "id": 3,
        "name": "Speedboat Sharks & Barracuda Warning",
        "start": 350.0,
        "end": 378.0,
        "framing": "smart_focus",
        "framing_params": {"x_ratio": 0.32, "margin_v": 520},
        "raw_slice": "ep1_raw_4k_moment3.mp4",
        "out_name": "ep1_short_3_Speedboat_Sharks_Warning_4K.mp4",
    },
    {
        "id": 4,
        "name": "Donnie Kidnapped! They Torture Baby Animals",
        "start": 662.0,
        "end": 698.0,
        "framing": "smart_focus",
        "framing_params": {"x_ratio": 0.34, "margin_v": 520},
        "raw_slice": "ep1_raw_4k_moment4.mp4",
        "out_name": "ep1_short_4_Donnie_Kidnapped_Baby_Animals_4K.mp4",
    },
    {
        "id": 5,
        "name": "ATV High-Speed Shootout & Swamp Ambush",
        "start": 1090.0,
        "end": 1135.0,
        "framing": "smart_focus",
        "framing_params": {"x_ratio": 0.34, "margin_v": 520},
        "raw_slice": "ep1_raw_4k_moment5.mp4",
        "out_name": "ep1_short_5_ATV_Shootout_Escape_4K.mp4",
    },
    {
        "id": 6,
        "name": "Boss Brian Grill: Fishing Under The Bridge",
        "start": 1555.0,
        "end": 1598.0,
        "framing": "split_stack",
        "framing_params": {"x_top": 1800, "y_top": 120, "x_bot": 500, "y_bot": 120, "sub_h_ratio": 0.72, "margin_v": 940},
        "raw_slice": "ep1_raw_4k_moment6.mp4",
        "out_name": "ep1_short_6_Boss_Brian_Fishing_Under_Bridge_4K.mp4",
    },
    {
        "id": 7,
        "name": "Redneck Dating Logic & Beat-up Truck",
        "start": 1698.0,
        "end": 1739.0,
        "framing": "split_stack",
        "framing_params": {"x_top": 550, "y_top": 120, "x_bot": 1750, "y_bot": 120, "sub_h_ratio": 0.72, "margin_v": 940},
        "raw_slice": "ep1_raw_4k_moment7.mp4",
        "out_name": "ep1_short_7_Redneck_Dating_Logic_4K.mp4",
    },
    {
        "id": 8,
        "name": "Lucia Prison Phone Call: Overcrowding Release",
        "start": 2112.0,
        "end": 2156.0,
        "framing": "smart_focus",
        "framing_params": {"x_ratio": 0.33, "margin_v": 520},
        "raw_slice": "ep1_raw_4k_moment8.mp4",
        "out_name": "ep1_short_8_Lucia_Prison_Overcrowding_Call_4K.mp4",
    },
    {
        "id": 9,
        "name": "Jason's House Roof Repair: Don't Fix It Too Good",
        "start": 2255.0,
        "end": 2292.0,
        "framing": "split_stack",
        "framing_params": {"x_top": 1200, "y_top": 100, "x_bot": 1400, "y_bot": 400, "sub_h_ratio": 0.70, "margin_v": 940},
        "raw_slice": "ep1_raw_4k_moment9.mp4",
        "out_name": "ep1_short_9_House_Roof_Repair_Rent_Roast_4K.mp4",
    },
    {
        "id": 10,
        "name": "Lucia's Child Mystery: The Abandoned Coffee Shop Baby",
        "start": 16.0,
        "end": 58.0,
        "framing": "split_stack",
        "framing_params": {"x_top": 700, "y_top": 120, "x_bot": 1800, "y_bot": 120, "sub_h_ratio": 0.72, "margin_v": 940},
        "raw_slice": "ep1_raw_4k_moment10.mp4",
        "out_name": "ep1_short_10_Lucia_Secret_Baby_Mystery_4K.mp4",
    },
]


def slice_local_moment(src: str, start: float, end: float, out_path: str):
    """Losslessly slice exact moment from local 4K master MKV video.

    Args:
        src: Path to master video.
        start: Start timestamp in seconds.
        end: End timestamp in seconds.
        out_path: Output slice path.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start),
        "-to", str(end),
        "-i", src,
        "-c", "copy",
        out_path
    ]
    subprocess.run(cmd, check=True)


def run_pipeline():
    """Execute slicing and 4K vertical rendering for all 10 Episode 1 shorts."""
    ensure_output_dirs()
    total_start = time.time()

    print(f"=== Starting Master Episode 1 Pipeline for {len(SHORTS_SPECS)} Shorts ===", flush=True)

    for spec in SHORTS_SPECS:
        s_id = spec["id"]
        raw_path = resolve_raw_video_path(spec["raw_slice"])
        final_path = resolve_final_short_path(spec["out_name"])

        print(f"\n--------------------------------------------------", flush=True)
        print(f"[{s_id}/10] Processing: {spec['name']} ({spec['framing']})", flush=True)
        print(f"--------------------------------------------------", flush=True)

        if not os.path.exists(raw_path):
            print(f"[{s_id}/10] Slicing {spec['start']}s -> {spec['end']}s from source video...", flush=True)
            t_slice = time.time()
            slice_local_moment(SOURCE_VIDEO, spec["start"], spec["end"], raw_path)
            print(f"[{s_id}/10] Sliced raw clip in {time.time() - t_slice:.2f}s -> {raw_path}", flush=True)
        else:
            print(f"[{s_id}/10] Raw slice already present: {raw_path}", flush=True)

        if os.path.exists(final_path):
            size_mb = os.path.getsize(final_path) / (1024 * 1024)
            print(f"[{s_id}/10] Master short already exists ({size_mb:.1f} MB): {final_path}", flush=True)
            continue

        print(f"[{s_id}/10] Rendering True 4K Vertical Short to {final_path}...", flush=True)
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
            framing_params=spec["framing_params"],
        )
        dur_render = time.time() - t_render
        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        print(f"[{s_id}/10] Rendered successfully in {dur_render:.2f}s! Size: {size_mb:.1f} MB", flush=True)

    print(f"\n=== All {len(SHORTS_SPECS)} Episode 1 Shorts Mastered in {time.time() - total_start:.2f}s ===", flush=True)


if __name__ == "__main__":
    run_pipeline()
