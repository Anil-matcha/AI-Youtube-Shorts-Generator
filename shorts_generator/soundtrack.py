"""Optional background music via Sonilo (--music).

After a short is rendered, the finished clip is uploaded to Sonilo's
``/v1/video-to-music`` endpoint, which analyzes the clip's pacing, motion, and
emotion and returns an original soundtrack matched to the video (AAC in an
.m4a container, same duration as the clip). The track is then mixed under the
clip's existing audio with ffmpeg at low volume so the speech stays fully
intelligible. Generated tracks are licensed and safe for commercial use
(terms apply).

Fully opt-in: nothing here runs unless ``--music`` is passed, and it needs
``SONILO_API_KEY``. Any per-clip failure (API error, missing ffmpeg, clip over
the endpoint's duration limit) is logged and that short ships with its
original audio — the pipeline never fails because music generation did.

The endpoint streams NDJSON events over a single POST:
  * ``audio_chunk`` — base64 audio bytes, aggregated per ``stream_index``
  * ``title``       — optional track title
  * ``complete``    — terminal success
  * ``error``       — terminal failure
Progress events (``stage_start``, ...) and unparseable lines are ignored.
"""
import base64
import binascii
import json
import os
import shutil
import subprocess
from typing import Dict, Iterable, List, Optional, Tuple

import requests

from .config import (
    LOCAL_OUTPUT_DIR,
    SONILO_API_URL,
    SONILO_MUSIC_VOLUME,
    SONILO_TIMEOUT_SECONDS,
    require_sonilo_key,
)

SONILO_VIDEO_TO_MUSIC_PATH = "/v1/video-to-music"

# The endpoint rejects videos longer than 6 minutes. Shorts are well under
# that, but check locally first (best-effort, via ffprobe) so an oversized
# clip is skipped instead of wasting an upload the backend will reject.
MAX_VIDEO_DURATION_SECONDS = 360


class SoniloError(RuntimeError):
    pass


def _error_detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body
    if isinstance(parsed, dict):
        detail = parsed.get("message") or parsed.get("detail") or parsed.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return body


def _http_error_message(status_code: int, body: str) -> str:
    detail = _error_detail(body)
    if status_code == 401:
        return "Invalid SONILO_API_KEY — check the key in your .env"
    if status_code == 402:
        return detail or "Sonilo account is out of credit"
    if status_code == 413:
        return f"upload too large: {detail}"
    if status_code == 429:
        return f"Sonilo rate limit hit: {detail}"
    return f"Sonilo API error ({status_code}): {detail}"


def _consume_ndjson(lines: Iterable[str]) -> Tuple[bytes, Optional[str]]:
    """Consume the NDJSON event stream; return (audio bytes, optional title).

    Audio chunks are aggregated per stream_index; the first stream is returned.
    """
    streams: Dict[int, bytearray] = {}
    title: Optional[str] = None
    completed = False
    for line in lines:
        if not line or not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "audio_chunk":
            data = event.get("data")
            if not isinstance(data, str):
                continue
            try:
                index = int(event.get("stream_index", 0))
            except (TypeError, ValueError):
                continue
            if index < 0:
                continue
            try:
                decoded = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                continue
            streams.setdefault(index, bytearray()).extend(decoded)
        elif event_type == "title":
            value = event.get("title")
            if isinstance(value, str) and value.strip():
                title = value.strip()
        elif event_type == "complete":
            completed = True
        elif event_type == "error":
            message = event.get("message") or event.get("code") or "stream error"
            raise SoniloError(f"music generation failed: {message}")
        # stage_start / stage_complete / other progress events are ignored.

    if not completed:
        raise SoniloError("music stream ended unexpectedly (no complete event)")
    if not streams:
        raise SoniloError("music stream completed but returned no audio")
    first_index = sorted(streams)[0]
    return bytes(streams[first_index]), title


def generate_music(video_path: str, prompt: str = "") -> Tuple[bytes, Optional[str]]:
    """Upload one rendered short and return (m4a audio bytes, optional title)."""
    api_key = require_sonilo_key()
    url = f"{SONILO_API_URL}{SONILO_VIDEO_TO_MUSIC_PATH}"
    data = {"prompt": prompt.strip()} if prompt and prompt.strip() else None
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with open(video_path, "rb") as fh:
            files = {"video": (os.path.basename(video_path), fh, "video/mp4")}
            # The generation endpoint is non-idempotent (it bills per call),
            # so unlike muapi.submit there is no retry here.
            resp = requests.post(
                url,
                headers=headers,
                data=data,
                files=files,
                stream=True,
                timeout=SONILO_TIMEOUT_SECONDS,
            )
    except requests.Timeout as e:
        raise SoniloError(f"music generation timed out ({SONILO_TIMEOUT_SECONDS:.0f}s)") from e
    except requests.ConnectionError as e:
        raise SoniloError(f"could not reach Sonilo: {e}") from e

    with resp:
        if resp.status_code >= 400:
            raise SoniloError(_http_error_message(resp.status_code, resp.text))
        try:
            return _consume_ndjson(resp.iter_lines(decode_unicode=True))
        except requests.RequestException as e:
            raise SoniloError(f"music stream failed: {e}") from e


def _probe_duration(video_path: str) -> Optional[float]:
    """Best-effort duration check via ffprobe; None if it can't be determined."""
    if shutil.which("ffprobe") is None:
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                video_path,
            ],
            capture_output=True,
            timeout=30,
        )
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _mix_music(video_path: str, music_path: str, out_path: str, volume: float) -> str:
    """ffmpeg-mix the generated track under the clip's original audio.

    The original speech stays at full volume; the music sits under it at
    `volume` (default 0.3). Video stream is copied untouched.
    """
    filter_complex = (
        f"[1:a]volume={volume}[bgm];"
        "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[mix]"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v:0", "-map", "[mix]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _ensure_local_clip(clip_url: str, out_dir: str, index: int) -> str:
    """Return a local path for the clip, downloading it first if it's remote.

    API-mode shorts are hosted URLs; music mixing runs locally, so the clip is
    fetched into `out_dir` (same place local mode writes its shorts).
    """
    if not clip_url.startswith(("http://", "https://")):
        return clip_url
    os.makedirs(out_dir, exist_ok=True)
    local_path = os.path.join(out_dir, f"short_{index:02d}.mp4")
    print(f"[music] downloading clip {index} for mixing", flush=True)
    with requests.get(clip_url, stream=True, timeout=SONILO_TIMEOUT_SECONDS) as resp:
        resp.raise_for_status()
        with open(local_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    return local_path


def add_music_to_short(short: Dict, index: int, out_dir: str, prompt: str = "") -> Dict:
    """Generate + mix music for one short; returns the updated dict. Raises on failure."""
    # ffmpeg is needed for the mix — check before the (billed) generation call.
    if shutil.which("ffmpeg") is None:
        raise SoniloError("ffmpeg not found on PATH (required to mix the music)")

    local_path = _ensure_local_clip(short["clip_url"], out_dir, index)

    duration = _probe_duration(local_path)
    if duration is not None and duration > MAX_VIDEO_DURATION_SECONDS:
        raise SoniloError(
            f"clip is {duration:.0f}s, over the {MAX_VIDEO_DURATION_SECONDS}s "
            "limit for music generation"
        )

    audio, title = generate_music(local_path, prompt=prompt)

    music_path = os.path.splitext(local_path)[0] + ".music.m4a"
    with open(music_path, "wb") as fh:
        fh.write(audio)

    tmp_path = local_path + ".tmp.mp4"
    try:
        _mix_music(local_path, music_path, tmp_path, SONILO_MUSIC_VOLUME)
        os.replace(tmp_path, local_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    updated = {**short, "music_path": music_path}
    if title:
        updated["music_title"] = title
    if local_path != short["clip_url"]:
        updated["source_clip_url"] = short["clip_url"]
        updated["clip_url"] = local_path
    return updated


def add_music_to_shorts(
    shorts: List[Dict],
    prompt: Optional[str] = None,
    out_dir: Optional[str] = None,
) -> List[Dict]:
    """Add background music to every rendered short.

    Mirrors crop_highlights' failure policy: a failed clip is logged and kept
    as-is (original audio, no music keys) instead of failing the run.
    """
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    results: List[Dict] = []
    for i, short in enumerate(shorts, 1):
        if not short.get("clip_url"):
            results.append(short)  # cropping already failed for this one
            continue
        print(f"[music] {i}/{len(shorts)}: {short.get('title', '(untitled)')}", flush=True)
        try:
            results.append(add_music_to_short(short, i, out_dir, prompt=prompt or ""))
        except Exception as e:
            print(f"[music] {i} failed: {e} — keeping the short without music", flush=True)
            results.append(short)
    return results
