"""Inspect Episode 3 transcript segments to locate dialogue and gameplay peaks."""

import json
from pathlib import Path


def main() -> None:
    """Print all segments with timestamps and text."""
    transcript_path = Path("output/raw/captions/ep3_transcript.json")
    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total Duration: {data.get('duration')}s")
    print(f"Total Segments: {len(data.get('segments', []))}\n")

    for i, s in enumerate(data.get("segments", []), 1):
        if s["end"] <= 650:
            start = s["start"]
            end = s["end"]
            dur = end - start
            print(f"[{i:03d}] {start:7.1f}s -> {end:7.1f}s ({dur:4.1f}s) | {s['text']}")


if __name__ == "__main__":
    main()
