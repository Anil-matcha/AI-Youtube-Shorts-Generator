"""Offline cache and controlled-download regressions; never touch real models."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from web import model_manager as manager


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cache = tmp_path / "hub"
    monkeypatch.setattr(manager, "_cache_roots", lambda: [cache])
    monkeypatch.setattr(manager, "_states", {})
    return cache


def complete_snapshot(cache: Path, model: str = "base", revision: str = "a" * 40) -> Path:
    directory = cache / f"models--Systran--faster-whisper-{model}"
    snapshot = directory / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (directory / "refs").mkdir(exist_ok=True)
    (directory / "refs" / "main").write_text(revision, encoding="utf-8")
    (snapshot / "model.bin").write_bytes(b"complete-weights")
    (snapshot / "config.json").write_text('{"is_multilingual":true}', encoding="utf-8")
    (snapshot / "tokenizer.json").write_text('{"model":{"type":"BPE"}}', encoding="utf-8")
    (snapshot / "vocabulary.json").write_text('["hello"]', encoding="utf-8")
    return snapshot


def test_empty_repository_is_not_an_installed_model(isolated_cache: Path) -> None:
    (isolated_cache / "models--Systran--faster-whisper-base").mkdir(parents=True)
    assert not manager.installed("base")
    assert manager._state("base")["status"] == "not_installed"


@pytest.mark.parametrize("filename", ["model.bin", "config.json", "tokenizer.json", "vocabulary.json"])
@pytest.mark.parametrize("damage", ["missing", "empty"])
def test_partial_snapshot_is_not_ready(isolated_cache: Path, filename: str, damage: str) -> None:
    snapshot = complete_snapshot(isolated_cache)
    if damage == "missing":
        (snapshot / filename).unlink()
    else:
        (snapshot / filename).write_bytes(b"")
    assert not manager.installed("base")


@pytest.mark.parametrize("filename", ["config.json", "tokenizer.json", "vocabulary.json"])
def test_invalid_json_is_not_ready(isolated_cache: Path, filename: str) -> None:
    snapshot = complete_snapshot(isolated_cache)
    (snapshot / filename).write_text("not-json", encoding="utf-8")
    assert not manager.installed("base")


def test_invalid_optional_preprocessor_does_not_claim_ready(isolated_cache: Path) -> None:
    snapshot = complete_snapshot(isolated_cache)
    (snapshot / "preprocessor_config.json").write_text("broken", encoding="utf-8")
    assert not manager.installed("base")


def test_hf_blob_links_are_valid_only_inside_model_repository(isolated_cache: Path, tmp_path: Path) -> None:
    snapshot = complete_snapshot(isolated_cache)
    weights = snapshot / "model.bin"
    blob_dir = snapshot.parent.parent / "blobs"
    blob_dir.mkdir()
    blob = blob_dir / ("b" * 64)
    weights.replace(blob)
    try:
        weights.symlink_to(blob)
    except OSError:
        pytest.skip("creating symlinks requires Windows Developer Mode or elevation")
    assert manager.installed("base")
    weights.unlink()
    external = tmp_path / "external.bin"
    external.write_bytes(b"external weights")
    weights.symlink_to(external)
    assert not manager.installed("base")
    assert external.read_bytes() == b"external weights"


def test_current_ref_cannot_be_hidden_by_complete_older_snapshot(isolated_cache: Path) -> None:
    snapshot = complete_snapshot(isolated_cache)
    (snapshot.parent.parent / "refs" / "main").write_text("b" * 40, encoding="utf-8")
    assert not manager.installed("base")


def test_pinned_snapshot_is_ready_without_mutable_main_ref(isolated_cache: Path) -> None:
    snapshot = complete_snapshot(isolated_cache, revision=manager.MODEL_REVISIONS["base"])
    (snapshot.parent.parent / "refs" / "main").unlink()
    assert manager.cached_snapshot("base") == snapshot
    assert manager.cached_snapshot("base", pinned_only=True) == snapshot


def test_pinned_snapshot_precedes_complete_legacy_cache(
    monkeypatch: pytest.MonkeyPatch, isolated_cache: Path, tmp_path: Path
) -> None:
    complete_snapshot(isolated_cache)
    pinned_root = tmp_path / "pinned-hub"
    pinned = complete_snapshot(pinned_root, revision=manager.MODEL_REVISIONS["base"])
    monkeypatch.setattr(manager, "_cache_roots", lambda: [isolated_cache, pinned_root])
    assert manager.cached_snapshot("base") == pinned


def test_legacy_snapshot_is_usable_but_not_a_pinned_download(isolated_cache: Path) -> None:
    legacy = complete_snapshot(isolated_cache)
    assert manager.cached_snapshot("base") == legacy
    assert manager.cached_snapshot("base", pinned_only=True) is None


def test_invalid_ref_cannot_escape_snapshots(isolated_cache: Path) -> None:
    snapshot = complete_snapshot(isolated_cache)
    (snapshot.parent.parent / "refs" / "main").write_text("../../outside", encoding="utf-8")
    assert not manager.installed("base")


def test_cache_hit_has_metrics_and_never_starts_a_download(
    monkeypatch: pytest.MonkeyPatch, isolated_cache: Path
) -> None:
    complete_snapshot(isolated_cache)
    monkeypatch.setattr(manager.threading, "Thread", lambda **kwargs: pytest.fail("cache hit started a thread"))
    state = manager.download(" BASE ")
    assert state["status"] == "ready"
    assert state["cache_hit"] is True
    assert state["duration_seconds"] == 0.0
    assert state["cached_bytes"] > 0


def test_cache_removed_externally_does_not_remain_ready(isolated_cache: Path) -> None:
    snapshot = complete_snapshot(isolated_cache)
    manager.download("base")
    (snapshot / "model.bin").unlink()
    assert manager._state("base")["status"] == "not_installed"
    assert manager._state("base")["progress"] == 0


@pytest.mark.parametrize("configured,expected", [("0", 1), ("999", 8), ("invalid", 4), ("2", 2)])
def test_download_concurrency_is_bounded(monkeypatch: pytest.MonkeyPatch, configured: str, expected: int) -> None:
    monkeypatch.setenv("SHORTS_MODEL_DOWNLOAD_WORKERS", configured)
    assert manager._download_workers() == expected


def test_download_only_fetches_public_supported_runtime_files(
    monkeypatch: pytest.MonkeyPatch, isolated_cache: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def snapshot_download(**kwargs: Any) -> str:
        calls.append(kwargs)
        return str(complete_snapshot(isolated_cache, revision=manager.MODEL_REVISIONS["base"]))

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    monkeypatch.setenv("SHORTS_MODEL_DOWNLOAD_WORKERS", "999")
    manager._download_worker("base")
    assert len(calls) == 1
    assert calls[0]["repo_id"] == "Systran/faster-whisper-base"
    assert calls[0]["revision"] == manager.MODEL_REVISIONS["base"]
    assert calls[0]["token"] is False
    assert calls[0]["endpoint"] == "https://huggingface.co"
    assert calls[0]["max_workers"] == 8
    assert "*.bin" not in calls[0]["allow_patterns"]
    assert "model.bin" in calls[0]["allow_patterns"]
    state = manager._state("base")
    assert state["status"] == "ready"
    assert state["duration_seconds"] >= 0


def test_download_rejects_partial_success(monkeypatch: pytest.MonkeyPatch, isolated_cache: Path) -> None:
    def snapshot_download(**kwargs: Any) -> str:
        snapshot = complete_snapshot(isolated_cache, revision=manager.MODEL_REVISIONS["base"])
        (snapshot / "tokenizer.json").unlink()
        return str(snapshot)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    manager._download_worker("base")
    assert manager._state("base")["status"] == "error"
    assert not manager.installed("base")


def test_download_cannot_mask_partial_target_with_another_complete_cache(monkeypatch, isolated_cache, tmp_path):
    other = tmp_path / "other-cache"
    complete_snapshot(other, revision=manager.MODEL_REVISIONS["base"])
    monkeypatch.setattr(manager, "_cache_roots", lambda: [isolated_cache, other])
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=lambda **kwargs: "unused"))
    with pytest.raises(RuntimeError, match="complete model snapshot"):
        manager._download_snapshot("base")


def test_explicit_download_cache_does_not_use_default_roots(monkeypatch, isolated_cache, tmp_path):
    chosen = tmp_path / "explicit-cache"

    def download(**kwargs):
        assert kwargs["cache_dir"] == str(chosen)
        return str(complete_snapshot(chosen, revision=manager.MODEL_REVISIONS["base"]))

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    result = manager._download_snapshot("base", cache_dir=chosen)
    assert result.is_relative_to(chosen)
    assert not isolated_cache.exists()


def test_download_error_does_not_expose_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def snapshot_download(**kwargs: Any) -> str:
        raise RuntimeError("Bearer secret-token https://host.invalid/file?signature=private")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    manager._download_worker("base")
    state = manager._state("base")
    assert state["status"] == "error"
    assert "secret-token" not in str(state)
    assert "signature" not in str(state)
    assert state["duration_seconds"] >= 0


def test_active_download_is_deduplicated_and_cannot_be_deleted() -> None:
    manager._states["base"] = {"status": "downloading", "progress": 5}
    assert manager.download("base")["status"] == "downloading"
    with pytest.raises(ValueError, match="finish"):
        manager.delete("base")


def test_total_model_downloads_are_bounded() -> None:
    manager._states.update({"base": {"status": "downloading"}, "small": {"status": "downloading"}})
    with pytest.raises(ValueError, match="already active"):
        manager.download("tiny")


def test_thread_start_failure_releases_download_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_start() -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(manager.threading, "Thread", lambda **kwargs: SimpleNamespace(start=fail_start))
    assert manager.download("base")["status"] == "error"
    assert manager._states["base"]["status"] != "downloading"


def test_symlinked_model_directory_is_not_deleted(isolated_cache: Path, tmp_path: Path) -> None:
    external_cache = tmp_path / "external" / "hub"
    snapshot = complete_snapshot(external_cache)
    isolated_cache.mkdir()
    link = isolated_cache / "models--Systran--faster-whisper-base"
    try:
        link.symlink_to(snapshot.parent.parent, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks requires Windows Developer Mode or elevation")
    result = manager.delete("base")
    assert result["removed_bytes"] == 0
    assert result["state"]["status"] == "error"
    assert (snapshot / "model.bin").read_bytes() == b"complete-weights"


def test_arbitrary_repository_cannot_be_requested() -> None:
    with pytest.raises(ValueError, match="unknown"):
        manager.download("attacker/whisper-model")
    with pytest.raises(ValueError, match="unknown"):
        manager._download_snapshot("attacker/whisper-model")


def test_active_state_uses_monotonic_elapsed_and_no_fake_percentage(monkeypatch):
    manager._states["base"] = {"status": "downloading", "phase": "downloading", "started_monotonic": 10,
                                "duration_seconds": None, "progress": 0}
    monkeypatch.setattr(manager.time, "monotonic", lambda: 22.5)
    state = manager._state("base")
    assert state["elapsed_seconds"] == 12.5
    assert state["progress_measured"] is False
    assert state["retryable"] is False
    assert "started_monotonic" not in state


@pytest.mark.parametrize("error,code", [
    (ImportError("private"), "dependencies_missing"),
    (PermissionError("private"), "cache_permission_denied"),
    (OSError(28, "private"), "disk_full"),
    (TimeoutError("private"), "network_unavailable"),
    (RuntimeError("https://host/?token=private"), "download_failed"),
])
def test_download_failure_messages_are_actionable_and_private(error, code):
    actual, message = manager._download_error(error)
    assert actual == code
    assert "private" not in message


def test_worker_reports_validation_before_ready(monkeypatch, isolated_cache):
    phases = []

    def snapshot_download(**kwargs):
        phases.append(manager._state("base")["phase"])
        return str(complete_snapshot(isolated_cache, revision=manager.MODEL_REVISIONS["base"]))

    original = manager._snapshot_bytes

    def validate(snapshot, model_dir):
        if manager._states.get("base", {}).get("phase") == "validating":
            phases.append("validating")
        return original(snapshot, model_dir)

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot_download))
    monkeypatch.setattr(manager, "_snapshot_bytes", validate)
    manager._download_worker("base")
    assert phases[0] == "downloading"
    assert "validating" in phases
    state = manager._state("base")
    assert state["phase"] == "ready"
    assert state["progress_measured"] is True
    assert state["error_code"] is None


def test_retry_starts_with_clean_error_state(monkeypatch):
    manager._states["base"] = {"status": "error", "error_code": "disk_full", "error": "Not enough disk space"}
    monkeypatch.setattr(manager.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None))
    state = manager.download("base")
    assert state["phase"] == "preparing"
    assert state["error_code"] is None
    assert state["error"] is None
