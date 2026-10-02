"""Cold-download tests are mocked and never use real models or networking."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import benchmark_downloads as downloads


def test_cli_requires_explicit_network_opt_in(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["benchmark_downloads"])
    monkeypatch.setattr(downloads, "benchmark", lambda *args, **kwargs: pytest.fail("Unexpected network"))
    with pytest.raises(SystemExit) as exc:
        downloads.main()
    assert exc.value.code == 2


def test_child_environment_isolates_all_hub_caches_and_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "private")
    monkeypatch.setenv("HF_HOME", "existing-cache")
    environment = downloads._environment(tmp_path)
    assert "HF_TOKEN" not in environment
    assert environment["HF_TOKEN_PATH"] == str(tmp_path / "absent-token")
    assert environment["HF_XET_CACHE"] == str(tmp_path / "xet")
    assert environment["HF_HOME"] == str(tmp_path / "home")
    assert os.environ["HF_HOME"] == "existing-cache"


def test_each_sample_is_disposable_and_distinct(monkeypatch):
    roots = []

    def run(command, **kwargs):
        settings = json.loads(kwargs["input"])
        root = Path(settings["cache"])
        roots.append(root)
        root.mkdir()
        (root / "model.bin").write_bytes(b"fixture")
        assert kwargs["timeout"] == 20
        return SimpleNamespace(stdout=json.dumps({"status": "measured", "download_seconds": 2.0}))

    monkeypatch.setattr(downloads.subprocess, "run", run)
    report = downloads.benchmark("tiny", repetitions=2, timeout=20)
    assert report["status"] == "measured"
    assert roots[0] != roots[1]
    assert all(not root.exists() for root in roots)
    assert not report["cache_reused"]
    assert report["download_summary"]["count"] == 2


def test_timeout_cleans_partial_cache_and_redacts_error(monkeypatch):
    roots = []

    def run(command, **kwargs):
        root = Path(json.loads(kwargs["input"])["cache"])
        roots.append(root)
        root.mkdir()
        (root / "partial").touch()
        raise subprocess.TimeoutExpired("https://host/?token=private", 10)

    monkeypatch.setattr(downloads.subprocess, "run", run)
    report = downloads.benchmark("base", timeout=10)
    assert report["status"] == "failed"
    assert "private" not in json.dumps(report)
    assert not roots[0].exists()


@pytest.mark.parametrize("kwargs", [{"workers": 0}, {"repetitions": 4}, {"timeout": float("nan")}, {"timeout": 601}])
def test_budget_rejected_before_launch(kwargs):
    with pytest.raises(ValueError):
        downloads.benchmark("tiny", **kwargs)


def test_worker_rejects_existing_cache_before_download(monkeypatch, tmp_path):
    (tmp_path / "existing").touch()
    monkeypatch.setattr(downloads, "_download_snapshot", lambda *args, **kwargs: pytest.fail("Existing cache reused"))
    with pytest.raises(ValueError, match="empty cache"):
        downloads._worker({"model": "tiny", "workers": 4, "cache": str(tmp_path)})
