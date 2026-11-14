"""Tests for the optional Sonilo background-music step (--music).

All tests run offline — no network, no ffmpeg/ffprobe, no real API key.
The Sonilo HTTP calls and the ffmpeg mix are stubbed; the tests assert the
wiring: Bearer auth, multipart upload, prompt forwarding, NDJSON event
handling, the duration pre-check, and the ship-without-music failure policy.
"""
import base64
import importlib
import json

import pytest


def _load_soundtrack(monkeypatch, **env):
    """Reload config + soundtrack after setting env (both bind at import time)."""
    monkeypatch.setenv("SONILO_API_KEY", "test-key")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from shorts_generator import config
    importlib.reload(config)
    from shorts_generator import soundtrack
    importlib.reload(soundtrack)
    return soundtrack


def _chunk_line(data: bytes, index: int = 0) -> str:
    return json.dumps({
        "type": "audio_chunk",
        "stream_index": index,
        "data": base64.b64encode(data).decode(),
    })


# ---------- NDJSON stream consumer ----------

def test_consume_ndjson_aggregates_chunks_and_title(monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    lines = [
        json.dumps({"type": "stage_start", "stage": "analysis"}),  # ignored
        _chunk_line(b"AB"),
        "not json at all",                                          # ignored
        json.dumps(["not", "a", "dict"]),                           # ignored
        json.dumps({"type": "audio_chunk", "stream_index": 0, "data": "!!!"}),  # bad b64, ignored
        json.dumps({"type": "audio_chunk", "stream_index": -1, "data": base64.b64encode(b"x").decode()}),  # ignored
        _chunk_line(b"CD"),
        _chunk_line(b"ZZ", index=1),  # second stream — not returned
        json.dumps({"type": "title", "title": "Neon Drift"}),
        json.dumps({"type": "complete"}),
    ]
    audio, title = soundtrack._consume_ndjson(lines)
    assert audio == b"ABCD"
    assert title == "Neon Drift"


def test_consume_ndjson_error_event_raises(monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    lines = [json.dumps({"type": "error", "message": "generation blew up"})]
    with pytest.raises(soundtrack.SoniloError, match="generation blew up"):
        soundtrack._consume_ndjson(lines)


def test_consume_ndjson_requires_complete_event(monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    with pytest.raises(soundtrack.SoniloError, match="ended unexpectedly"):
        soundtrack._consume_ndjson([_chunk_line(b"AB")])


def test_consume_ndjson_requires_audio(monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    with pytest.raises(soundtrack.SoniloError, match="no audio"):
        soundtrack._consume_ndjson([json.dumps({"type": "complete"})])


# ---------- config ----------

def test_missing_key_raises(monkeypatch):
    monkeypatch.setenv("SONILO_API_KEY", "")
    from shorts_generator import config
    importlib.reload(config)
    with pytest.raises(RuntimeError, match="SONILO_API_KEY"):
        config.require_sonilo_key()


# ---------- generate_music HTTP wiring ----------

class _FakeStreamResponse:
    def __init__(self, lines, status_code=200, text=""):
        self._lines = lines
        self.status_code = status_code
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)


def test_generate_music_sends_bearer_and_multipart(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)

    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"not-a-real-mp4")

    recorded = {}

    def fake_post(url, headers=None, data=None, files=None, stream=None, timeout=None):
        recorded.update(url=url, headers=headers, data=data, files=files, stream=stream)
        return _FakeStreamResponse([
            _chunk_line(b"MUSIC"),
            json.dumps({"type": "title", "title": "Golden Hour"}),
            json.dumps({"type": "complete"}),
        ])

    monkeypatch.setattr(soundtrack.requests, "post", fake_post)

    audio, title = soundtrack.generate_music(str(video), prompt="lofi hip hop")

    assert audio == b"MUSIC"
    assert title == "Golden Hour"
    assert recorded["url"].endswith("/v1/video-to-music")
    assert recorded["headers"]["Authorization"] == "Bearer test-key"
    assert recorded["data"] == {"prompt": "lofi hip hop"}
    assert recorded["stream"] is True
    name, fh, mime = recorded["files"]["video"]
    assert name == "short_01.mp4"
    assert mime == "video/mp4"


def test_generate_music_omits_empty_prompt(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"x")

    recorded = {}

    def fake_post(url, **kwargs):
        recorded.update(kwargs)
        return _FakeStreamResponse([_chunk_line(b"M"), json.dumps({"type": "complete"})])

    monkeypatch.setattr(soundtrack.requests, "post", fake_post)
    soundtrack.generate_music(str(video), prompt="   ")
    assert recorded["data"] is None


def test_generate_music_maps_http_errors(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"x")

    def fake_post(url, **kwargs):
        return _FakeStreamResponse(
            [], status_code=402, text=json.dumps({"message": "out of credit"})
        )

    monkeypatch.setattr(soundtrack.requests, "post", fake_post)
    with pytest.raises(soundtrack.SoniloError, match="out of credit"):
        soundtrack.generate_music(str(video))


# ---------- add_music_to_shorts orchestration ----------

def _stub_tooling(monkeypatch, soundtrack, duration=42.0):
    """Pretend ffmpeg/ffprobe exist and the clip has a known duration."""
    monkeypatch.setattr(soundtrack.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(soundtrack, "_probe_duration", lambda path: duration)


def test_full_flow_mixes_in_place_and_keeps_track(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    _stub_tooling(monkeypatch, soundtrack)

    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"ORIGINAL")

    recorded = {}

    def fake_generate(video_path, prompt=""):
        recorded["generate"] = {"video_path": video_path, "prompt": prompt}
        return b"AUDIO", "Neon Drift"

    def fake_mix(video_path, music_path, out_path, volume):
        recorded["mix"] = {"volume": volume}
        with open(out_path, "wb") as fh:
            fh.write(b"MIXED")
        return out_path

    monkeypatch.setattr(soundtrack, "generate_music", fake_generate)
    monkeypatch.setattr(soundtrack, "_mix_music", fake_mix)

    shorts = [{"title": "hook", "clip_url": str(video)}]
    out = soundtrack.add_music_to_shorts(shorts, prompt="lofi", out_dir=str(tmp_path))

    assert recorded["generate"]["prompt"] == "lofi"
    assert recorded["mix"]["volume"] == pytest.approx(0.3)
    # The mixed file replaces the original path — clip_url stays stable.
    assert out[0]["clip_url"] == str(video)
    assert video.read_bytes() == b"MIXED"
    assert "source_clip_url" not in out[0]
    # The generated track is kept beside the short for remixing.
    music = tmp_path / "short_01.music.m4a"
    assert out[0]["music_path"] == str(music)
    assert music.read_bytes() == b"AUDIO"
    assert out[0]["music_title"] == "Neon Drift"


def test_remote_clip_downloaded_before_upload(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    _stub_tooling(monkeypatch, soundtrack)

    class _FakeGetResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=None):
            return iter([b"REMOTE-CLIP"])

    monkeypatch.setattr(soundtrack.requests, "get", lambda url, **kw: _FakeGetResponse())
    monkeypatch.setattr(soundtrack, "generate_music", lambda path, prompt="": (b"AUDIO", None))

    def fake_mix(video_path, music_path, out_path, volume):
        with open(out_path, "wb") as fh:
            fh.write(b"MIXED")
        return out_path

    monkeypatch.setattr(soundtrack, "_mix_music", fake_mix)

    remote = "https://cdn.example.com/clips/short_1.mp4"
    out = soundtrack.add_music_to_shorts(
        [{"title": "t", "clip_url": remote}], out_dir=str(tmp_path)
    )

    local = tmp_path / "short_01.mp4"
    assert out[0]["clip_url"] == str(local)
    assert out[0]["source_clip_url"] == remote
    assert local.read_bytes() == b"MIXED"
    assert "music_title" not in out[0]  # no title event → no key


def test_failure_ships_short_unchanged(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    _stub_tooling(monkeypatch, soundtrack)

    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"ORIGINAL")

    def failing_generate(video_path, prompt=""):
        raise soundtrack.SoniloError("Sonilo rate limit hit: slow down")

    monkeypatch.setattr(soundtrack, "generate_music", failing_generate)

    short = {"title": "t", "clip_url": str(video), "score": 90}
    out = soundtrack.add_music_to_shorts([short], out_dir=str(tmp_path))

    assert out == [short]  # untouched — no music keys, no exception
    assert video.read_bytes() == b"ORIGINAL"


def test_duration_cap_skips_generation(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    _stub_tooling(monkeypatch, soundtrack, duration=400.0)  # over the 360s cap

    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"ORIGINAL")

    called = {}
    monkeypatch.setattr(
        soundtrack, "generate_music",
        lambda *a, **kw: called.setdefault("generate", True),
    )

    short = {"title": "t", "clip_url": str(video)}
    out = soundtrack.add_music_to_shorts([short], out_dir=str(tmp_path))

    assert "generate" not in called  # never uploaded, never billed
    assert out == [short]


def test_missing_ffmpeg_skips_generation(tmp_path, monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    monkeypatch.setattr(soundtrack.shutil, "which", lambda name: None)

    video = tmp_path / "short_01.mp4"
    video.write_bytes(b"ORIGINAL")

    called = {}
    monkeypatch.setattr(
        soundtrack, "generate_music",
        lambda *a, **kw: called.setdefault("generate", True),
    )

    short = {"title": "t", "clip_url": str(video)}
    out = soundtrack.add_music_to_shorts([short], out_dir=str(tmp_path))

    assert "generate" not in called  # ffmpeg checked before the billed call
    assert out == [short]


def test_failed_crop_passes_through(monkeypatch):
    soundtrack = _load_soundtrack(monkeypatch)
    short = {"title": "t", "clip_url": None, "error": "autocrop failed"}
    assert soundtrack.add_music_to_shorts([short]) == [short]
