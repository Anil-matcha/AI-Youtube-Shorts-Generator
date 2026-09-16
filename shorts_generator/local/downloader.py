"""Local YouTube download via yt-dlp.

Returns a local mp4 path so the rest of the local pipeline can read it
directly off disk.
"""

import json
import os
import re
import ipaddress
import socket
import threading
from importlib import import_module
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from typing import Optional

from ..config import LOCAL_OUTPUT_DIR, cancellation_requested


_DEFAULT_REMOTE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
_DOWNLOAD_CONTEXT = threading.local()


def _remote_host_allowlist() -> set[str]:
    configured = os.getenv("SHORTS_ALLOWED_REMOTE_HOSTS", "").strip()
    extra = {item.strip().lower().rstrip(".") for item in configured.split(",") if item.strip()}
    return _DEFAULT_REMOTE_HOSTS | extra


def _host_allowed(host: str, allowlist: set[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == item or host.endswith("." + item) for item in allowlist)


def _public_addresses(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise ValueError("remote host could not be resolved") from exc
    addresses: list[str] = []
    for record in records:
        address = record[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("remote host resolved to an invalid address") from exc
        # Treat every resolved address as a trust boundary. Rejecting when any
        # answer is private prevents DNS rebinding from reaching local services.
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_unspecified
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed in ipaddress.ip_network("100.64.0.0/10")
            or parsed in ipaddress.ip_network("169.254.0.0/16")
        ):
            raise ValueError("remote host resolves to a private or reserved network")
        addresses.append(str(parsed))
    if not addresses:
        raise ValueError("remote host has no usable addresses")
    return addresses


def validate_remote_source(source: str) -> str:
    """Validate a remote source before yt-dlp can make any network request.

    Only YouTube hosts (or an explicit administrator allowlist) are accepted.
    DNS answers are checked too, so an allowed hostname cannot be used as a
    redirect/rebinding tunnel into loopback, link-local, or cloud metadata.
    """
    parsed = urlparse(str(source or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("remote source must be an http(s) URL with a hostname")
    if parsed.username or parsed.password:
        raise ValueError("remote source credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("remote source port is invalid") from exc
    if port not in (None, 80, 443):
        raise ValueError("remote source ports must be 80 or 443")
    host = parsed.hostname.rstrip(".").lower()
    if not _host_allowed(host, _remote_host_allowlist()):
        raise ValueError("remote source host is not on the administrator allowlist")
    _public_addresses(host, port or (443 if scheme == "https" else 80))
    return parsed.geturl()


def _import_ytdlp():
    try:
        return import_module("yt_dlp")
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp is required for --mode local. Install it with:\n    pip install -r requirements-local.txt"
        ) from e


def _format_for(fmt: str) -> str:
    """Map our '720' / '1080' shorthand to a yt-dlp format selector."""
    try:
        height = int(fmt)
    except (TypeError, ValueError, OverflowError):
        height = 720
    if height <= 0:
        height = 720
    return f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best"


def _extract_youtube_video_id(source: str) -> Optional[str]:
    """Best-effort extraction of a YouTube video id from a URL."""
    if not source:
        return None
    source = str(source).strip()
    if not source:
        return None
    parsed = urlparse(source)
    host = (parsed.netloc or "").lower().split("@")[-1].split(":", 1)[0].rstrip(".")
    if host.startswith("www."):
        host = host[4:]

    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        return video_id or None

    if host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            video_id = qs.get("v", [""])[0]
            return video_id or None
        match = re.search(r"/(?:shorts|embed|live)/([^/?#&]+)", parsed.path)
        if match:
            return match.group(1)

    return None


def _resolve_local_path(source: str) -> Optional[str]:
    """Return a local filesystem path if the input already points at one."""
    if source is None:
        raise RuntimeError("A YouTube URL or local video path is required.")
    source = str(source).strip()
    if not source:
        raise RuntimeError("A YouTube URL or local video path is required.")
    parsed = urlparse(source)
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            raw_path = f"//{parsed.netloc}{raw_path}"
        # RFC 8089 file URIs encode a Windows drive as ``file:///C:/...``.
        # urlparse leaves the slash before the drive letter; remove it before
        # constructing a native Windows path.
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw_path):
            raw_path = raw_path[1:]
        candidate = Path(raw_path).expanduser()
        if candidate.exists() and candidate.is_file():
            return str(candidate.resolve())
        raise RuntimeError(f"Local file URL does not exist: {source}")

    if parsed.scheme in ("http", "https"):
        try:
            validate_remote_source(source)
        except ValueError as exc:
            raise RuntimeError(f"Remote source is not allowed: {exc}") from exc
        return None

    candidate = Path(source).expanduser()
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())

    if any(sep in source for sep in (os.sep, "/")) or source.startswith("~") or source.startswith("."):
        raise RuntimeError(f"Local file path does not exist: {source}")

    return None


def _existing_download(out_dir: str, video_id: str) -> Optional[str]:
    """Return a cached download path if we already have this YouTube id."""
    for ext in (".mp4", ".mkv", ".webm"):
        candidate = os.path.join(out_dir, f"source_{video_id}{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None


def download_youtube_local(video_url: str, fmt: str = "720", out_dir: Optional[str] = None) -> str:
    """Download a remote URL or return a local file path unchanged."""
    if video_url is None:
        raise RuntimeError("A YouTube URL or local video path is required.")
    video_url = str(video_url).strip()
    if cancellation_requested():
        raise RuntimeError("Job cancelled")
    local_path = _resolve_local_path(video_url)
    if local_path:
        _DOWNLOAD_CONTEXT.info = {}
        print(f"[download/local] using local file: {local_path}", flush=True)
        return local_path

    yt_dlp = _import_ytdlp()
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    video_id = _extract_youtube_video_id(video_url)
    if video_id:
        cached = _existing_download(out_dir, video_id)
        if cached:
            _DOWNLOAD_CONTEXT.info = _load_download_info(cached)
            print(f"[download/local] reusing cached download: {cached}", flush=True)
            return cached

    print(f"[download/local] {video_url} @ {fmt}p -> {out_dir}/", flush=True)
    ydl_opts = {
        "format": _format_for(fmt),
        "outtmpl": os.path.join(out_dir, "source_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 3,
        # YouTube now requires solving a JS "n" challenge to unlock most
        # formats. Without a JS runtime + solver script, yt-dlp reports
        # perfectly-playable videos as "not available". See:
        # https://github.com/yt-dlp/yt-dlp/wiki/EJS
        "js_runtimes": {"node": {"path": None}},
        "remote_components": ["ejs:github"],
        # The default Android client can return format URLs that YouTube
        # rejects with HTTP 403 from some networks. The embedded web client
        # currently provides a playable, challenge-solved fallback.
        "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
    }

    def cancellation_hook(_status: object) -> None:
        if cancellation_requested():
            raise RuntimeError("Job cancelled")

    ydl_opts["progress_hooks"] = [cancellation_hook]

    def match_filter(info: object, *, incomplete: bool = False) -> Optional[str]:
        if incomplete or not isinstance(info, dict):
            return None
        candidate = str(info.get("webpage_url") or info.get("original_url") or video_url)
        try:
            validate_remote_source(candidate)
        except ValueError as exc:
            return str(exc)
        return None

    ydl_opts["match_filter"] = match_filter

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            _DOWNLOAD_CONTEXT.info = info if isinstance(info, dict) else {}
            if cancellation_requested():
                raise RuntimeError("Job cancelled")
            path = ydl.prepare_filename(info)
            # merge_output_format may rename the extension after merge
            if not os.path.exists(path):
                stem, _ = os.path.splitext(path)
                for ext in (".mp4", ".mkv", ".webm"):
                    if os.path.exists(stem + ext):
                        path = stem + ext
                        break
            if not os.path.isfile(path):
                raise RuntimeError(
                    f"yt-dlp reported success, but the downloaded video file was not found. Expected: {path}"
                )
    except Exception as exc:
        message = str(exc)
        if "403" in message or "Forbidden" in message:
            raise RuntimeError(
                "YouTube refused the download (HTTP 403). The embedded client "
                "was tried automatically; try again later or drag the video file "
                "into Shorts Studio instead. If it only fails for age-restricted "
                "videos, configure yt-dlp browser cookies on the machine running the app."
            ) from exc
        raise
    print(f"[download/local] ready: {path}", flush=True)
    return path


def _load_download_info(media_path: str) -> dict:
    """Load the small metadata sidecar written next to a cached download."""
    sidecar = Path(media_path).with_suffix(".info.json")
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError, UnicodeError):
        return {}


def _write_download_info(media_path: str, info: object) -> None:
    if not isinstance(info, dict):
        return
    # Keep only the metadata needed by chapter-aware ranking; do not persist
    # extractor cookies, signatures, or the full yt-dlp response.
    chapters = info.get("chapters")
    safe_chapters = []
    if isinstance(chapters, (list, tuple)):
        for chapter in chapters[:200]:
            if not isinstance(chapter, dict):
                continue
            safe_chapters.append(
                {
                    "start_time": chapter.get("start_time", chapter.get("start")),
                    "end_time": chapter.get("end_time", chapter.get("end")),
                    "title": str(chapter.get("title") or "Chapter")[:200],
                }
            )
    if not safe_chapters:
        return
    try:
        Path(media_path).with_suffix(".info.json").write_text(
            json.dumps({"chapters": safe_chapters}, ensure_ascii=False), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError):
        return


def download_youtube_local_with_metadata(
    video_url: str, fmt: str = "720", out_dir: Optional[str] = None
) -> tuple[str, dict]:
    """Download a source and return its path plus safe YouTube metadata."""
    _DOWNLOAD_CONTEXT.info = {}
    path = download_youtube_local(video_url, fmt=fmt, out_dir=out_dir)
    info = getattr(_DOWNLOAD_CONTEXT, "info", {})
    if isinstance(info, dict):
        _write_download_info(path, info)
        chapters = info.get("chapters")
        safe = []
        if isinstance(chapters, (list, tuple)):
            for chapter in chapters[:200]:
                if not isinstance(chapter, dict):
                    continue
                try:
                    start = float(chapter.get("start_time", chapter.get("start", 0.0)))
                    end_value = chapter.get("end_time", chapter.get("end"))
                    end = float(end_value) if end_value is not None else None
                except (TypeError, ValueError, OverflowError):
                    continue
                if start < 0 or (end is not None and end <= start):
                    continue
                safe.append({"start_time": start, "end_time": end, "title": str(chapter.get("title") or "Chapter")[:200]})
        return path, {"chapters": safe}
    return path, {}
