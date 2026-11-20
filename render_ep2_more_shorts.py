"""Render pipeline for Episode 2 additional viral 4K vertical YouTube Shorts.

Renders Short 3 (Hippie Beatdown / 0420 Code) and Short 4 (Weed Dealer Energy / Police Heist)
with dynamic karaoke subtitles, broadcast audio mastering, and Intel Arc QSV.
"""

import time
from shorts_generator.local.clipper import render_short_clip


def run_render_more_shorts() -> None:
    """Execute rendering pipeline for Episode 2 additional vertical shorts."""
    print("=== STARTING ADDITIONAL EPISODE 2 4K SHORTS RENDERING ===", flush=True)

    t0 = time.time()
    s3_in = "output/ep2_raw_4k_moment3.mp4"
    s3_out = "output/ep2_short_3_4K_mastered.mp4"
    print(f"Rendering Short 3 (Collecting Brian's Rent) with zoom_blur framing...", flush=True)
    render_short_clip(
        source_path=s3_in,
        start_time=0.0,
        end_time=57.0,
        out_path=s3_out,
        framing="zoom_blur",
        burn_subtitles=True,
        master_audio=True,
        encoder_choice="auto"
    )
    t1 = time.time()
    print(f"Short 3 finished in {t1 - t0:.2f} seconds: {s3_out}", flush=True)

    t2 = time.time()
    s4_in = "output/ep2_raw_4k_moment4.mp4"
    s4_out = "output/ep2_short_4_4K_mastered.mp4"
    print(f"Rendering Short 4 (Weed Dealer Energy) with smart_focus framing...", flush=True)
    render_short_clip(
        source_path=s4_in,
        start_time=0.0,
        end_time=27.0,
        out_path=s4_out,
        framing="smart_focus",
        burn_subtitles=True,
        master_audio=True,
        encoder_choice="auto"
    )
    t3 = time.time()
    print(f"Short 4 finished in {t3 - t2:.2f} seconds: {s4_out}", flush=True)
    print("=== ADDITIONAL EPISODE 2 RENDERING COMPLETE ===", flush=True)


if __name__ == "__main__":
    run_render_more_shorts()
