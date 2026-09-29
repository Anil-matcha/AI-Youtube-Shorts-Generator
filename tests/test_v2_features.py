"""Focused coverage for the v2 performance, style, channel, and model seams."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web.app as studio
import web.channel_routes as channel_routes
import web.model_manager as model_manager


@pytest.fixture()
def v2_client() -> TestClient:
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()
    with TestClient(studio.app, base_url="http://127.0.0.1") as test_client:
        yield test_client
    with studio._lock:
        studio._jobs.clear()
        studio._job_credentials.clear()
        studio._cancel_events.clear()


def _seed_job(job_id: str = "v2-dashboard-job") -> dict:
    return {
        "id": job_id,
        "name": "V2 dashboard demo",
        "status": "done",
        "request": {
            "url": "https://www.youtube.com/watch?v=demo",
            "caption_style": "bold",
            "caption_position": "bottom",
            "caption_font": "Arial",
            "caption_color": "#ffffff",
            "aspect_ratio": "9:16",
            "focus": "educational",
            "transition": "fade",
        },
        "raw_shorts": [{"title": "A useful hook", "hook_sentence": "Here is the useful part.", "score": 0.91}],
        "factory": {"approvals": [{"clip_index": 0, "decision": "approved"}]},
        "variants": [{"id": "variant-b", "name": "Hook B", "clip_index": 0}],
        "analytics": [],
        "publishing": [],
        "logs": [],
    }


def test_dashboard_import_style_memory_and_backup(v2_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(studio, "_style_profile_path", tmp_path / "style_profile.json")
    with studio._lock:
        studio._jobs.clear()
        studio._jobs["v2-dashboard-job"] = _seed_job()

    imported = v2_client.post(
        "/api/analytics/import",
        json={
            "records": [
                {
                    "job_id": "v2-dashboard-job",
                    "platform": "youtube_shorts",
                    "views": 1200,
                    "likes": 80,
                    "comments": 12,
                    "completion_rate": 0.61,
                }
            ]
        },
    )
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1
    dashboard = imported.json()["dashboard"]
    assert dashboard["performance"]["overall"]["views"] == 1200

    learned = v2_client.post("/api/style-profile/learn", json={"job_ids": ["v2-dashboard-job"]})
    assert learned.status_code == 200
    assert learned.json()["profile"]["preferences"]["caption_style"] == "bold"
    assert learned.json()["profile"]["examples"][0]["hook"] == "Here is the useful part."

    saved = v2_client.put("/api/style-profile", json={"name": "Demo voice", "notes": "Keep the first sentence direct."})
    assert saved.status_code == 200
    assert saved.json()["profile"]["name"] == "Demo voice"

    archive = v2_client.get("/api/backup")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        profile = json.loads(bundle.read("style_profile.json"))
        assert profile["name"] == "Demo voice"
        assert "https://" not in json.dumps(profile)


def test_channel_preview_is_bounded_and_only_returns_youtube_urls(v2_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _source, download=False):
            assert download is False
            return {
                "entries": [
                    {"id": "one", "title": "First"},
                    {"webpage_url": "https://www.youtube.com/watch?v=two", "title": "Second"},
                    {"webpage_url": "https://example.com/nope", "title": "Rejected"},
                ]
            }

    fake_module = SimpleNamespace(YoutubeDL=FakeYoutubeDL)
    monkeypatch.setattr(channel_routes, "validate_remote_source", lambda value: value)
    original_import = channel_routes.importlib.import_module
    monkeypatch.setattr(
        channel_routes.importlib,
        "import_module",
        lambda name: fake_module if name == "yt_dlp" else original_import(name),
    )
    response = v2_client.post(
        "/api/channel/preview",
        json={"source": "https://www.youtube.com/@demo/videos", "max_items": 2},
    )
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 2
    assert all("youtube.com/" in item["url"] for item in entries)


def test_model_manager_catalog_cache_and_confirmed_delete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = tmp_path / "hub"
    model_dir = cache / "models--Systran--faster-whisper-base"
    model_dir.mkdir(parents=True)
    (model_dir / "weights.bin").write_bytes(b"weights")
    monkeypatch.setattr(model_manager, "_model_dirs", lambda name: [cache / f"models--Systran--faster-whisper-{name}"])

    catalog = {item["name"]: item for item in model_manager.list_models()}
    assert catalog["base"]["installed"] is True
    assert catalog["tiny"]["installed"] is False
    assert model_manager.delete("base")["removed_bytes"] == len(b"weights")
    assert not model_dir.exists()
