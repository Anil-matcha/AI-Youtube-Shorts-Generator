"""Extract and cleanly save video manifest for Episode 3 without internal postprocessors."""

import json
from pathlib import Path
import yt_dlp

VIDEO_URL = "https://youtu.be/Lvfc2eYMRHU"
MANIFEST_PATH = Path("output/raw/video/ep3_video_info.json")


def main() -> None:
    """Extract manifest with download=False and save sanitized JSON."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(VIDEO_URL, download=False)
        clean = ydl.sanitize_info(info)

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)

    print(f"[+] Saved clean manifest ({len(clean.get('formats', []))} formats) to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
