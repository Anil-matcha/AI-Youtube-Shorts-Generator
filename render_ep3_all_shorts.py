"""Master rendering pipeline for Episode 3 True 4K 60FPS Vertical YouTube Shorts.

Streams 4K 60FPS slices to output/raw/video/ and renders finalized True 4K vertical masters
(2160x3840 @ 60FPS, 35 Mbps) directly into output/ with dynamic karaoke subtitles,
EBU R128 broadcast loudness mastering, monotonic ClipRegistry tracking, and tailored framing
(Up & Down split_stack for dialogue and immersive 9:16 smart_focus for action).
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shorts_generator.clip_registry import ClipRegistry
from shorts_generator.local.clipper import render_short_clip
from shorts_generator.paths import (
    ensure_output_dirs,
    resolve_final_short_path,
    resolve_raw_video_path,
)

MANIFEST_PATH = Path("output/raw/video/ep3_video_info.json")
VIDEO_ID = "Lvfc2eYMRHU"

SHORTS_SPECS: List[Dict] = [
    {
        "id": 1,
        "name": "Mandy: Get To Work Stud! (Plunger & Sink Disaster)",
        "start_sec": 521.00,
        "end_sec": 555.00,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 320,
            "y_top": 120,
            "x_bot": 1600,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "DIALOGUE_BANTER",
        "score": 94,
        "raw_slice": "ep3_raw_4k_moment1_sink.mp4",
        "out_name": "ep3_short_1_Mandy_Sink_Plunger_4K.mp4",
        "hook_sentence": "I found the plunger, well then get to work stud! Nasty... how's it going in there?",
    },
    {
        "id": 2,
        "name": "Mandy: It's NOT Stalking If We Met In Person!",
        "start_sec": 565.09,
        "end_sec": 600.90,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 380,
            "y_top": 120,
            "x_bot": 1650,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "DIALOGUE_BANTER",
        "score": 98,
        "raw_slice": "ep3_raw_4k_moment1.mp4",
        "out_name": "ep3_short_2_Mandy_Stalker_Banter_4K.mp4",
        "hook_sentence": "I think that's called stalking Mandy. No it's not stalking if you've met in person!",
    },
    {
        "id": 3,
        "name": "Bhai Ne Bola Marne Ka: Arnold Gang Turf War Standoff",
        "start_sec": 1269.54,
        "end_sec": 1327.69,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1950,
            "y_top": 120,
            "x_bot": 380,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "ACTION_HEIST",
        "score": 97,
        "raw_slice": "ep3_raw_4k_moment2.mp4",
        "out_name": "ep3_short_3_Arnold_Turf_War_4K.mp4",
        "hook_sentence": "We didn't start the turf war, we ended it! Ask to speak to my manager!",
    },
    {
        "id": 4,
        "name": "Scuba Diving Disaster: Drunk Bachelor Party & Death Waiver",
        "start_sec": 3335.94,
        "end_sec": 3385.99,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1350,
            "y_top": 100,
            "x_bot": 350,
            "y_bot": 100,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "STUNT_FAIL",
        "score": 95,
        "raw_slice": "ep3_raw_4k_moment5.mp4",
        "out_name": "ep3_short_4_Scuba_Waiver_Roast_4K.mp4",
        "hook_sentence": "Don't people need to train for scuba diving? This guy skips all that bullshit, sign the waiver!",
    },
    {
        "id": 5,
        "name": "Boat License Chaos: Bro Do You Even Have A Boat License?!",
        "start_sec": 3411.28,
        "end_sec": 3452.93,
        "framing": "smart_focus",
        "framing_params": {
            "x_ratio": 0.30,
            "margin_v": 520,
        },
        "archetype": "STUNT_FAIL",
        "score": 93,
        "raw_slice": "ep3_raw_4k_moment8.mp4",
        "out_name": "ep3_short_5_Boat_License_Chaos_4K.mp4",
        "hook_sentence": "Bro do you even have your boat driving license?! Who goes skydiving at 6 AM?!",
    },
    {
        "id": 6,
        "name": "Secret Shipwreck Heist: Diving Into The Deep Abyss",
        "start_sec": 3524.50,
        "end_sec": 3587.30,
        "framing": "smart_focus",
        "framing_params": {
            "x_ratio": 0.32,
            "margin_v": 520,
        },
        "archetype": "ACTION_HEIST",
        "score": 94,
        "raw_slice": "ep3_raw_4k_moment6.mp4",
        "out_name": "ep3_short_6_Shipwreck_Abyss_Dive_4K.mp4",
        "hook_sentence": "Shipwreck dive starts now... remember what you're really doing down there, good luck!",
    },
    {
        "id": 7,
        "name": "Treasure Hunter Kenny: What 100-Year-Old Gold Feels Like",
        "start_sec": 1930.17,
        "end_sec": 1960.35,
        "framing": "smart_focus",
        "framing_params": {
            "strip_letterbox": True,
            "active_h": 1920,
            "x_ratio": 0.31,
            "margin_v": 520,
        },
        "archetype": "LORE_BACKSTORY",
        "score": 92,
        "raw_slice": "ep3_raw_4k_moment7.mp4",
        "out_name": "ep3_short_7_Treasure_Hunter_Kenny_4K.mp4",
        "hook_sentence": "When you hold hundreds-of-years-old gold in the middle of the ocean, you know how rich you are.",
    },
    {
        "id": 8,
        "name": "Mandy: Ever Heard Of Auto-Pay Dinosaur?! (Hallway Flirtation)",
        "start_sec": 407.38,
        "end_sec": 435.80,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1500,
            "y_top": 120,
            "x_bot": 420,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "DIALOGUE_BANTER",
        "score": 94,
        "raw_slice": "ep3_raw_4k_moment8_hallway.mp4",
        "out_name": "ep3_short_8_Mandy_AutoPay_Flirt_4K.mp4",
        "hook_sentence": "Ever heard of auto-pay you dinosaur? You got a website? Yeah it's called PayMandyNow.com!",
    },
    {
        "id": 9,
        "name": "Brian Heder: 15-Year Table Ritual & Mob Ghosting",
        "start_sec": 973.97,
        "end_sec": 1030.00,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1650,
            "y_top": 120,
            "x_bot": 380,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "LORE_BACKSTORY",
        "score": 93,
        "raw_slice": "ep3_raw_4k_moment9_brian.mp4",
        "out_name": "ep3_short_9_Brian_Table_Ritual_4K.mp4",
        "hook_sentence": "I've had that same table for fifteen years! Arnold doesn't just disappear, something went down!",
    },
    {
        "id": 10,
        "name": "Vice City Drive: Did Arnold Ghost You Like A Tinder Date?!",
        "start_sec": 1177.10,
        "end_sec": 1219.50,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1750,
            "y_top": 120,
            "x_bot": 380,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "DIALOGUE_BANTER",
        "score": 97,
        "raw_slice": "ep3_raw_4k_moment10_car.mp4",
        "out_name": "ep3_short_10_Car_Chase_Tinder_Ghost_4K.mp4",
        "hook_sentence": "Jason use your eyes! Did Arnold ghost you like a Tinder date? I'm not trying to f*** him!",
    },
    {
        "id": 11,
        "name": "Tiki Bar: Waiting To See Unicorns Baby! & Kenton Rees",
        "start_sec": 1844.06,
        "end_sec": 1884.49,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1600,
            "y_top": 120,
            "x_bot": 420,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "LORE_BACKSTORY",
        "score": 91,
        "raw_slice": "ep3_raw_4k_moment11_tiki.mp4",
        "out_name": "ep3_short_11_Tiki_Bar_Unicorns_4K.mp4",
        "hook_sentence": "Lori what are you drinking? Waiting to see unicorns baby! Kenny meet Kenton Rees.",
    },
    {
        "id": 12,
        "name": "Rockstar Satire Ad: Mr. Garcia Sued Surgeon (BBL Disaster)",
        "start_sec": 2764.20,
        "end_sec": 2824.08,
        "framing": "smart_focus",
        "framing_params": {
            "x_ratio": 0.33,
            "margin_v": 520,
        },
        "archetype": "SATIRE_COMMERCIAL",
        "score": 98,
        "raw_slice": "ep3_raw_4k_moment12_mrgarcia.mp4",
        "out_name": "ep3_short_12_MrGarcia_BBL_Lawyer_4K.mp4",
        "hook_sentence": "My plastic surgeon botched my BBL, now thanks to Mr. Garcia, he is my full-time unpaid butler!",
    },
    {
        "id": 13,
        "name": "Rockstar Satire Ad: King Gator Golf (Look At All Them Holes!)",
        "start_sec": 2883.40,
        "end_sec": 2937.74,
        "framing": "smart_focus",
        "framing_params": {
            "x_ratio": 0.33,
            "margin_v": 520,
        },
        "archetype": "SATIRE_COMMERCIAL",
        "score": 95,
        "raw_slice": "ep3_raw_4k_moment13_kinggator.mp4",
        "out_name": "ep3_short_13_King_Gator_Golf_4K.mp4",
        "hook_sentence": "King Gator Adventure Golf! Look at all them holes! Mini golf with real hungry Florida gators!",
    },
    {
        "id": 14,
        "name": "Ocean Salvage Lore: Sir Todd Bankcroft The Rich English Asshole",
        "start_sec": 3252.58,
        "end_sec": 3289.68,
        "framing": "split_stack",
        "framing_params": {
            "x_top": 1400,
            "y_top": 120,
            "x_bot": 380,
            "y_bot": 120,
            "sub_h_ratio": 0.72,
            "margin_v": 940,
        },
        "archetype": "LORE_BACKSTORY",
        "score": 92,
        "raw_slice": "ep3_raw_4k_moment14_todd.mp4",
        "out_name": "ep3_short_14_Todd_Bankcroft_Lore_4K.mp4",
        "hook_sentence": "Sir Todd Bankcroft... rich English asshole who bought exclusive salvage rights to the whole reef.",
    },
    {
        "id": 15,
        "name": "Noob Driver Fail: 4x4 Tree Crash & Highway Sparks",
        "start_sec": 1360.00,
        "end_sec": 1405.00,
        "framing": "smart_focus",
        "framing_params": {
            "x_ratio": 0.28,
            "margin_v": 520,
        },
        "archetype": "STUNT_FAIL",
        "score": 96,
        "raw_slice": "ep3_raw_4k_moment15_noob_crash.mp4",
        "out_name": "ep3_short_15_Noob_Driver_Tree_Crash_4K.mp4",
        "hook_sentence": "Bro who gave this guy a driver's license in GTA 6?! Crashed straight into the trees!",
    },
]

_CACHED_STREAM_URLS: Optional[Tuple[str, str]] = None


def format_hms(seconds: float) -> str:
    """Format seconds into HH:MM:SS string.

    Args:
        seconds: Float seconds.

    Returns:
        Formatted timestamp string.
    """
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_stream_urls(force_refresh: bool = False) -> Tuple[str, str]:
    """Retrieve fresh format 628 (4K 60FPS) and format 234/140 (audio) streaming URLs.

    Extracts live GoogleVideo URLs directly from YouTube to prevent token/HLS expiration.

    Args:
        force_refresh: Whether to ignore cached stream URLs.

    Returns:
        Tuple of (video_url, audio_url).

    Raises:
        RuntimeError: If formats are missing from manifest.
    """
    global _CACHED_STREAM_URLS
    if _CACHED_STREAM_URLS and not force_refresh:
        return _CACHED_STREAM_URLS

    import yt_dlp

    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://youtu.be/{VIDEO_ID}", download=False)

    v_url = None
    a_url = None
    for fmt in info.get("formats", []):
        fid = fmt.get("format_id")
        if fid == "628":
            v_url = fmt.get("url")
        elif fid in ("234", "140") and not a_url:
            a_url = fmt.get("url")

    if not v_url or not a_url:
        raise RuntimeError(f"Could not locate 4K stream 628/234 for {VIDEO_ID}")

    _CACHED_STREAM_URLS = (v_url, a_url)
    return _CACHED_STREAM_URLS


def download_4k_slice(start_sec: float, end_sec: float, out_path: str) -> None:
    """Stream targeted 4K 60FPS slice directly via FFmpeg using fresh streaming URLs.

    Args:
        start_sec: Start timestamp in seconds.
        end_sec: End timestamp in seconds.
        out_path: Destination path for raw slice.
    """
    start_str = format_hms(start_sec)
    end_str = format_hms(end_sec)
    try:
        v_url, a_url = get_stream_urls()
        cmd = [
            "ffmpeg", "-y",
            "-ss", start_str,
            "-to", end_str,
            "-i", v_url,
            "-ss", start_str,
            "-to", end_str,
            "-i", a_url,
            "-c:v", "copy",
            "-c:a", "copy",
            out_path
        ]
        t0 = time.time()
        print(f"[*] Slicing 4K stream {start_str} -> {end_str} to {Path(out_path).name}...", flush=True)
        subprocess.run(cmd, check=True)
        print(f"[+] Sliced in {time.time() - t0:.2f}s.", flush=True)
    except subprocess.CalledProcessError:
        print("[!] FFmpeg slice failed. Refreshing stream URLs and retrying...", flush=True)
        v_url, a_url = get_stream_urls(force_refresh=True)
        cmd = [
            "ffmpeg", "-y",
            "-ss", start_str,
            "-to", end_str,
            "-i", v_url,
            "-ss", start_str,
            "-to", end_str,
            "-i", a_url,
            "-c:v", "copy",
            "-c:a", "copy",
            out_path
        ]
        t0 = time.time()
        subprocess.run(cmd, check=True)
        print(f"[+] Sliced in {time.time() - t0:.2f}s on retry.", flush=True)


def run_pipeline() -> None:
    """Execute complete 4K download, master rendering, and registry update for Episode 3."""
    ensure_output_dirs()
    registry = ClipRegistry()

    total_start = time.time()
    print(f"=== Starting True 4K Vertical Master Pipeline for Episode 3 ({len(SHORTS_SPECS)} Shorts) ===", flush=True)

    for spec in SHORTS_SPECS:
        s_id = spec["id"]
        raw_path = str(resolve_raw_video_path(spec["raw_slice"]))
        final_path = str(resolve_final_short_path(spec["out_name"]))

        if os.path.exists(final_path):
            print(f"\n[{s_id}/{len(SHORTS_SPECS)}] Master short already exists at {Path(final_path).name} - Skipping!", flush=True)
            continue

        if not os.path.exists(raw_path):
            print(f"\n[{s_id}/{len(SHORTS_SPECS)}] Downloading 4K slice for '{spec['name']}'...", flush=True)
            download_4k_slice(spec["start_sec"], spec["end_sec"], raw_path)
        else:
            print(f"\n[{s_id}/{len(SHORTS_SPECS)}] Raw 4K slice already present at {Path(raw_path).name}", flush=True)

        print(f"[{s_id}/{len(SHORTS_SPECS)}] Rendering True 4K Short (2160x3840 @ 60FPS, 35M) [{spec['framing']}] -> {Path(final_path).name}...", flush=True)
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
            framing_params=spec.get("framing_params"),
        )
        print(f"[{s_id}/{len(SHORTS_SPECS)}] Mastered in {time.time() - t_render:.2f}s!", flush=True)

        registry.register_clip(
            video_id=VIDEO_ID,
            start_time=spec["start_sec"],
            end_time=spec["end_sec"],
            guard_band=45.0,
            archetype=spec["archetype"],
            score=spec["score"],
            title=spec["name"],
            hook_sentence=spec["hook_sentence"],
            file_path=final_path,
        )

    print(f"\n=== All {len(SHORTS_SPECS)} Episode 3 Shorts Mastered in True 4K in {time.time() - total_start:.2f}s ===", flush=True)


if __name__ == "__main__":
    run_pipeline()
