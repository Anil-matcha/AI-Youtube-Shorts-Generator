"""CLI entry point.

Usage:
    python main.py "https://www.youtube.com/watch?v=..." \
        --num-clips 3 --aspect-ratio 9:16
"""
import argparse
import json
import math
import sys
from pathlib import Path

# Windows uses 'charmap' by default, which can't encode Unicode characters
# like →. Reconfigure stdout/stderr to UTF-8 so output works on all platforms.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from shorts_generator import generate_shorts


def _display_seconds(value: object) -> float:
    """Format malformed clip timestamps without crashing the CLI summary."""
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return seconds if math.isfinite(seconds) and seconds >= 0 else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Shorts Studio — local-first short-form video editor")
    parser.add_argument("url", help="YouTube URL, file:// URL, or local file path")
    parser.add_argument(
        "--mode",
        choices=["api", "local"],
        default="api",
        help="api (default, MuAPI) or local (remote URL, file://, or local path + faster-whisper + LLM provider + ffmpeg).",
    )
    parser.add_argument("--num-clips", type=int, default=3, help="How many shorts to render (default: 3)")
    parser.add_argument("--aspect-ratio", default="9:16", help="Output aspect ratio (default: 9:16)")
    parser.add_argument("--format", default="720", help="Source download resolution: 360 / 480 / 720 / 1080 (default: 720)")
    parser.add_argument("--language", default=None, help="Force Whisper language code, e.g. 'en' (default: auto-detect)")
    parser.add_argument("--output-json", default=None, help="Write the full result JSON to this path")
    args = parser.parse_args()

    try:
        result = generate_shorts(
            youtube_url=args.url,
            num_clips=args.num_clips,
            aspect_ratio=args.aspect_ratio,
            download_format=args.format,
            language=args.language,
            mode=args.mode,
        )
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1
    if not isinstance(result, dict):
        print("\nFAILED: pipeline returned an invalid result object", file=sys.stderr)
        return 1

    print("\n" + "=" * 72)
    print(f"Mode:          {result.get('mode', args.mode)}")
    print(f"Source video:  {result.get('source_video_url') or 'unknown'}")
    highlights = result.get("highlights") if isinstance(result.get("highlights"), list) else []
    shorts = result.get("shorts") if isinstance(result.get("shorts"), list) else []
    print(f"Highlights:    {len(highlights)} candidates -> kept top {len(shorts)}")
    print("=" * 72)
    for i, s in enumerate(shorts, 1):
        if not isinstance(s, dict):
            print(f"\n#{i}  clip: FAILED (malformed clip result)")
            continue
        start = _display_seconds(s.get("start_time"))
        end = _display_seconds(s.get("end_time"))
        print(f"\n#{i}  score={s.get('score')}  {start:.1f}s -> {end:.1f}s")
        print(f"     title:  {s.get('title')}")
        print(f"     hook:   {s.get('hook_sentence')}")
        if s.get("clip_url"):
            print(f"     clip:   {s['clip_url']}")
        else:
            print(f"     clip:   FAILED ({s.get('error')})")

    if args.output_json:
        output_path = Path(args.output_json).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\nFull JSON written to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
