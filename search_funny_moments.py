"""Detailed inspection of gameplay segments for stunts, laughing, accidents, and noob moments."""

import json
from pathlib import Path


def inspect_detailed() -> None:
    """Print all segments between 1000s and 3000s."""
    transcript_path = Path("output/raw/captions/ep3_transcript.json")
    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    segments = data.get("segments", [])
    print(f"Total segments: {len(segments)}")

    for i, s in enumerate(segments):
        start = s["start"]
        end = s["end"]
        if 1000 <= start <= 3000:
            print(f"[{i:03d}] {start:7.1f}s -> {end:7.1f}s ({end-start:4.1f}s): {s['text'][:120]}")


if __name__ == "__main__":
    inspect_detailed()
