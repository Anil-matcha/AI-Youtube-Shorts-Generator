"""Inspect and rank potential viral moments from Episode 2 transcript."""

import json


def inspect_dialogue():
    """Print dialogue segments with timestamps and text."""
    with open(r"output\ep2_transcript.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total Segments: {len(data['segments'])}")
    for i, s in enumerate(data["segments"]):
        txt = s["text"].strip()
        if len(txt) > 8:
            s_m, s_s = int(s["start"] // 60), int(s["start"] % 60)
            e_m, e_s = int(s["end"] // 60), int(s["end"] % 60)
            print(f"[{i:03d}] {s_m:02d}:{s_s:02d} -> {e_m:02d}:{e_s:02d} ({s['end']-s['start']:.1f}s): {txt}")


if __name__ == "__main__":
    inspect_dialogue()
