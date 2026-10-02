"""Regression guards for edit reservations and pre-acquisition lock eviction."""

from __future__ import annotations

import threading

import pytest

import web.app as studio
from web.editor_routes import _clip_edit_operation


def test_artifact_waiter_reserves_same_lock_during_map_churn(monkeypatch: pytest.MonkeyPatch) -> None:
    paused, proceed = threading.Event(), threading.Event()
    class PausedLock:
        def __init__(self):
            self.real = threading.Lock()
        def locked(self):
            return self.real.locked()
        def __enter__(self):
            if threading.current_thread().name == "paused-artifact-writer":
                paused.set()
                assert proceed.wait(5)
            self.real.acquire()
        def __exit__(self, *_args):
            self.real.release()
    target = PausedLock()
    monkeypatch.setattr(studio, "_artifact_locks", {"target": target})
    monkeypatch.setattr(studio, "_artifact_users", {})
    monkeypatch.setattr(studio, "_MAX_ARTIFACT_LOCKS", 2)
    finished = threading.Event()
    def write():
        with studio._artifact_lock("target"):
            finished.set()
    worker = threading.Thread(target=write, name="paused-artifact-writer")
    worker.start()
    try:
        assert paused.wait(5)
        for index in range(5):
            with studio._artifact_lock(f"churn-{index}"):
                pass
        assert studio._artifact_locks["target"] is target
        with studio._artifact_lock("target"):
            assert studio._artifact_users["target"] == 2
    finally:
        proceed.set()
        worker.join(5)
    assert not worker.is_alive() and finished.is_set()
    assert not studio._artifact_users


def test_clip_edit_reservation_survives_nested_work_and_releases_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(studio, "_jobs", {"edit-job": {"id": "edit-job", "schedule": []}})
    monkeypatch.setattr(studio, "_clip_edit_counts", {})
    with pytest.raises(RuntimeError, match="render failed"):
        with _clip_edit_operation("edit-job"):
            assert studio._clip_edit_counts["edit-job"] == 1
            with _clip_edit_operation("edit-job"):
                assert studio._clip_edit_counts["edit-job"] == 2
            assert studio._clip_edit_counts["edit-job"] == 1
            raise RuntimeError("render failed")
    assert not studio._clip_edit_counts
