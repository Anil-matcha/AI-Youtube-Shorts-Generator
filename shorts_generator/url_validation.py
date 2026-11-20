"""Input validation for remote video sources."""
from urllib.parse import urlsplit


YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)


def validate_youtube_url(value: str) -> str:
    """Return a safe YouTube URL or raise before forwarding it to a downloader."""
    message = "Only HTTPS URLs from youtube.com or youtu.be are supported as remote video sources."
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)

    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError(message) from exc

    if (
        parsed.scheme.lower() != "https"
        or host is None
        or host.lower() not in YOUTUBE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError(message)

    return value.strip()
