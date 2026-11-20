"""Tests for the TwelveLabs Pegasus highlight backend.

* The unit test runs with no network and no SDK — it stubs the TwelveLabs
  client and asserts the provider indexes the video once, caches the video id,
  and forwards the prompt to Pegasus's ``analyze``.
* The live test is skipped unless ``TWELVELABS_API_KEY`` is set; it confirms
  the SDK + credentials are wired by making a real Marengo embedding call
  (cheap and fast, unlike a full Pegasus video index).
"""
import os
import sys
import types

import pytest


def _install_fake_sdk(monkeypatch, recorder):
    """Inject a fake ``twelvelabs`` module so the provider runs offline."""

    class FakeTask:
        id = "task_1"
        status = "ready"
        video_id = "vid_123"

    class FakeTasks:
        def create(self, *, index_id, video_file):
            recorder["index_id"] = index_id
            recorder["uploaded"] = True
            return FakeTask()

        def wait_for_done(self, *, task_id):
            return FakeTask()

    class FakeIndex:
        id = "idx_new"

    class FakeIndexes:
        def create(self, *, index_name, models):
            recorder["created_index"] = (index_name, models)
            return FakeIndex()

    class FakeResult:
        data = '{"highlights": []}'

    class FakeClient:
        def __init__(self, *, api_key):
            recorder["api_key"] = api_key
            self.tasks = FakeTasks()
            self.indexes = FakeIndexes()

        def analyze(self, *, model_name, video_id, prompt, max_tokens):
            recorder["analyze"] = {
                "model_name": model_name,
                "video_id": video_id,
                "prompt": prompt,
                "max_tokens": max_tokens,
            }
            return FakeResult()

    fake_mod = types.ModuleType("twelvelabs")
    fake_mod.TwelveLabs = FakeClient
    monkeypatch.setitem(sys.modules, "twelvelabs", fake_mod)


def test_provider_indexes_once_and_calls_pegasus(tmp_path, monkeypatch):
    monkeypatch.setenv("TWELVELABS_API_KEY", "test-key")
    monkeypatch.setenv("TWELVELABS_INDEX_ID", "")  # force auto-create

    # config reads env at import time; reload it after setting env.
    import importlib

    from shorts_generator import config
    importlib.reload(config)
    from shorts_generator.local import twelvelabs_provider
    importlib.reload(twelvelabs_provider)

    recorder: dict = {}
    _install_fake_sdk(monkeypatch, recorder)

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not-a-real-mp4")

    out = twelvelabs_provider.call_twelvelabs_llm("rank highlights", video_path=str(video))

    assert out == '{"highlights": []}'
    assert recorder["api_key"] == "test-key"
    assert recorder["uploaded"] is True
    assert recorder["created_index"][0] == "ai-youtube-shorts-generator"
    assert recorder["analyze"]["video_id"] == "vid_123"
    assert recorder["analyze"]["model_name"] == "pegasus1.5"
    assert recorder["analyze"]["prompt"] == "rank highlights"

    # Video id cached beside the file → a second call skips re-indexing.
    cache = video.with_suffix(".mp4.tlvideo")
    assert cache.read_text() == "vid_123"

    recorder.clear()
    _install_fake_sdk(monkeypatch, recorder)
    twelvelabs_provider.call_twelvelabs_llm("again", video_path=str(video))
    assert "uploaded" not in recorder  # reused cache, no re-upload
    assert recorder["analyze"]["video_id"] == "vid_123"


def test_missing_key_raises(monkeypatch):
    monkeypatch.setenv("TWELVELABS_API_KEY", "")
    import importlib

    from shorts_generator import config
    importlib.reload(config)
    with pytest.raises(RuntimeError, match="TWELVELABS_API_KEY"):
        config.require_twelvelabs_key()


@pytest.mark.skipif(
    not os.getenv("TWELVELABS_API_KEY"),
    reason="set TWELVELABS_API_KEY to run the live TwelveLabs smoke test",
)
def test_live_credentials_and_sdk():
    """Cheap live check: Marengo text embedding returns a 512-dim vector."""
    from twelvelabs import TwelveLabs

    client = TwelveLabs(api_key=os.environ["TWELVELABS_API_KEY"])
    resp = client.embed.create(
        model_name="marengo3.0",
        text="a person laughing at a surprising revelation",
    )
    vector = resp.text_embedding.segments[0].float_
    assert len(vector) == 512
