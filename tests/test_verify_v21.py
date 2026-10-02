"""Regression checks for the isolated runtime verification harness."""

import json
import sys
from pathlib import Path

import pytest

from scripts import verify_v21


@pytest.mark.parametrize("url", ["file:///private", "http://example.com:80/api", "http://127.0.0.1/api"])
def test_requests_are_loopback_only(url):
    with pytest.raises(ValueError, match="loopback"):
        verify_v21._request(url, "test-token")


def test_missing_ffmpeg_fails_before_launch(monkeypatch):
    monkeypatch.setattr(verify_v21.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="FFmpeg is required"):
        verify_v21.verify()


def test_missing_package_fails_before_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_v21.shutil, "which", lambda _: "ffmpeg")
    with pytest.raises(ValueError, match="does not exist"):
        verify_v21.verify(tmp_path / "absent.exe")


def test_failure_report_does_not_expose_local_paths(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise OSError("private credential path /private/account/token")

    output = tmp_path / "report.json"
    monkeypatch.setattr(verify_v21, "verify", fail)
    monkeypatch.setattr(sys, "argv", ["verify_v21", "--output", str(output)])
    assert verify_v21.main() == 1
    report = json.loads(output.read_text())
    assert report["status"] == "failed"
    assert "private" not in report["error"]


def test_cli_requires_ocr_and_selects_package(monkeypatch, tmp_path):
    output = tmp_path / "report.json"
    calls = []

    def verify(executable, **kwargs):
        calls.append((executable, kwargs))
        return {"status": "passed"}

    monkeypatch.setattr(verify_v21, "verify", verify)
    monkeypatch.setattr(sys, "argv", ["verify_v21", "--require-ocr", "--executable", "app.exe", "--output", str(output)])
    assert verify_v21.main() == 0
    assert calls == [(Path("app.exe"), {"require_ocr": True, "tesseract": None, "expected_version": None})]
