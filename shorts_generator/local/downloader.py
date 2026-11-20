"""High-speed YouTube downloader with slice streaming and 4K support via yt-dlp.

Supports:
- Full video download with automatic format selection up to 4K (2160p @ 60fps).
- High-speed targeted slice downloads via ffmpeg external downloader.
- Local media path resolution and reuse of cached files.
"""

import os
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from typing import Optional

from ..config import LOCAL_OUTPUT_DIR


def _import_ytdlp():
    """Import and return the yt_dlp module.

    Returns:
        The yt_dlp module object.

    Raises:
        RuntimeError: If yt_dlp is not installed.
    """
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required for --mode local. Install it with:\n"
            "    pip install yt-dlp"
        ) from e
    return yt_dlp


def _format_for(fmt: str) -> str:
    """Map quality selector shorthand to yt-dlp format specification.

    Args:
        fmt: Desired quality ('720', '1080', '2160', '4k', 'best').

    Returns:
        Format selection string for yt-dlp.
    """
    fmt_lower = fmt.strip().lower()
    if fmt_lower in ("2160", "4k", "best"):
        return "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    if fmt_lower == "1080":
        return "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best"
    return "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best"


def _extract_youtube_video_id(source: str) -> Optional[str]:
    """Extract YouTube video identifier from URL.

    Args:
        source: URL or string identifier.

    Returns:
        11-character video ID if found, else None.
    """
    parsed = urlparse(source)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host in ("youtu.be", "www.youtu.be"):
        return parsed.path.lstrip("/").split("/", 1)[0] or None

    if "youtube.com" in host:
        if parsed.path.startswith("/watch"):
            return parse_qs(parsed.query).get("v", [""])[0] or None
        match = re.search(r"/(?:shorts|embed|live)/([^/?#&]+)", parsed.path)
        if match:
            return match.group(1)

    return None


def _resolve_local_path(source: str) -> Optional[str]:
    """Resolve input to an existing local filesystem path if applicable.

    Args:
        source: URI or local path string.

    Returns:
        Normalized absolute path string, or None if remote.
    """
    parsed = urlparse(source)
    if parsed.scheme == "file":
        raw = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            raw = f"//{parsed.netloc}{raw}"
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
        raise RuntimeError(f"Local file URL does not exist: {source}")

    if parsed.scheme in ("http", "https"):
        return None

    candidate = Path(source).expanduser()
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())

    if any(sep in source for sep in (os.sep, "/")) or source.startswith("~") or source.startswith("."):
        raise RuntimeError(f"Local file path does not exist: {source}")

    return None


def _existing_download(out_dir: str, video_id: str) -> Optional[str]:
    """Locate existing download cache for a YouTube video identifier.

    Args:
        out_dir: Target directory to inspect.
        video_id: YouTube video identifier string.

    Returns:
        Path to cached file if present, else None.
    """
    for ext in (".mp4", ".mkv", ".webm"):
        candidate = os.path.join(out_dir, f"source_{video_id}{ext}")
        if os.path.exists(candidate):
            return candidate
    return None


def download_youtube_local(video_url: str, fmt: str = "2160", out_dir: Optional[str] = None) -> str:
    """Download a YouTube video or return a local media path.

    Args:
        video_url: Video URL or local path.
        fmt: Target resolution format.
        out_dir: Output cache directory.

    Returns:
        Path to downloaded or local media file.
    """
    local_path = _resolve_local_path(video_url)
    if local_path:
        return local_path

    yt_dlp = _import_ytdlp()
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    video_id = _extract_youtube_video_id(video_url)
    if video_id:
        cached = _existing_download(out_dir, video_id)
        if cached:
            return cached

    ydl_opts = {
        "format": _format_for(fmt),
        "outtmpl": os.path.join(out_dir, "source_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        path = ydl.prepare_filename(info)
        if not os.path.exists(path):
            stem, _ = os.path.splitext(path)
            for ext in (".mp4", ".mkv", ".webm"):
                if os.path.exists(stem + ext):
                    path = stem + ext
                    break

    return path


def download_youtube_slice(
    video_url: str,
    start_seconds: float,
    end_seconds: float,
    out_path: str,
    fmt: str = "2160"
) -> str:
    """Download only a specified time slice of a remote YouTube video at native quality.

    Args:
        video_url: Remote YouTube URL.
        start_seconds: Start timestamp in seconds.
        end_seconds: End timestamp in seconds.
        out_path: Target destination path for the sliced .mp4.
        fmt: Target quality format.

    Returns:
        Path to the downloaded video slice.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    yt_dlp = _import_ytdlp()

    ydl_opts = {
        "format": "628+234/bestvideo+bestaudio/best",
        "outtmpl": out_path,
        "external_downloader": "ffmpeg",
        "external_downloader_args": {
            "ffmpeg_i": ["-ss", f"{start_seconds:.2f}", "-to", f"{end_seconds:.2f}"]
        },
        "merge_output_format": "mp4",
        "overwrites": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    return out_path
