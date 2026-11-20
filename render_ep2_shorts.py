"""Render pipeline for Episode 2 viral 4K vertical YouTube Shorts.

Renders Short 1 (Leonida Tourism PSA) and Short 2 (Jason's Mercenary Past)
with dynamic karaoke subtitles, broadcast audio mastering, and Intel Arc QSV.
"""

import time
from shorts_generator.local.clipper import render_short_clip


def run_episode2_render() -> None:
    """Execute rendering pipeline for Episode 2 vertical shorts."""
    print("=== STARTING EPISODE 2 4K SHORTS RENDERING ===", flush=True)

    t0 = time.time()
    s1_in = "output/ep2_raw_4k_moment1.mp4"
    s1_out = "output/ep2_short_1_4K_mastered.mp4"
    print(f"Rendering Short 1 (Leonida Tourism PSA) with fit_blur framing...", flush=True)
    render_short_clip(
        source_path=s1_in,
        start_time=0.0,
        end_time=30.0,
        out_path=s1_out,
        framing="fit_blur",
        burn_subtitles=True,
        master_audio=True,
        encoder_choice="auto"
    )
    t1 = time.time()
    print(f"Short 1 finished in {t1 - t0:.2f} seconds: {s1_out}", flush=True)

    t2 = time.time()
    s2_in = "output/ep2_raw_4k_moment2.mp4"
    s2_out = "output/ep2_short_2_4K_mastered.mp4"
    print(f"Rendering Short 2 (Jason's Mercenary Past) with center framing...", flush=True)
    render_short_clip(
        source_path=s2_in,
        start_time=0.0,
        end_time=50.0,
        out_path=s2_out,
        framing="center",
        burn_subtitles=True,
        master_audio=True,
        encoder_choice="auto"
    )
    t3 = time.time()
    print(f"Short 2 finished in {t3 - t2:.2f} seconds: {s2_out}", flush=True)
    print("=== EPISODE 2 RENDERING COMPLETE ===", flush=True)


if __name__ == "__main__":
    run_episode2_render()
