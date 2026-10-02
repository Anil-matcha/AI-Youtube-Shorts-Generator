"""Verify local evidence through an isolated, authenticated source or frozen app.

No creator footage or provider account is used. Generated media and job state
are removed after shutdown. --require-ocr makes missing Tesseract a failure.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _request(url: str, token: str = "", data: Any = None, method: str = "GET") -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ValueError("Runtime checks require an explicit loopback HTTP endpoint")
    connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=110)
    try:
        connection.request(method, parsed.path, body=None if data is None else json.dumps(data).encode(), headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _fixture(directory: Path, ffmpeg: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    output = directory / "output"
    jobs = output / "jobs"
    jobs.mkdir(parents=True)
    image = Image.new("RGB", (960, 540), "white")
    ImageDraw.Draw(image).text((60, 200), "CREATOR REVENUE 2026", fill="black", font=ImageFont.load_default(size=48))
    frame = directory / "fixture.png"
    image.save(frame)
    source = output / "fixture.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(frame),
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "2", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    record = {"id": "v21-smoke", "name": "Generated evidence check", "status": "done", "stage": "done",
              "raw_source_video_url": str(source), "raw_shorts": [], "raw_transcript": {}, "logs": [],
              "request": {"url": str(source), "mode": "local"}, "created_at": time.time()}
    (jobs / "v21-smoke.json").write_text(json.dumps(record), encoding="utf-8")


def verify(executable: Path | None = None, *, require_ocr: bool = False, tesseract: Path | None = None,
           expected_version: str | None = None) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if executable and (executable.parent / "ffmpeg.exe").is_file():
        ffmpeg = str((executable.parent / "ffmpeg.exe").resolve())
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for the generated fixture")
    if executable and not executable.is_file():
        raise ValueError("The packaged executable does not exist")
    with tempfile.TemporaryDirectory(prefix="shorts-v21-verify-") as raw:
        directory = Path(raw)
        _fixture(directory, ffmpeg)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment = {**os.environ, "SHORTS_API_TOKEN": token, "SHORTS_STUDIO_DATA_DIR": str(directory),
                       "LOCAL_OUTPUT_DIR": str(directory / "output"), "SHORTS_AUTO_RESUME": "false",
                       "SHORTS_STUDIO_HEADLESS": "true", "SHORTS_STUDIO_BROWSER": "1", "SHORTS_BIND_HOST": "127.0.0.1"}
        if tesseract:
            environment["LOCAL_TESSERACT_PATH"] = str(tesseract.resolve())
        command = ([str(executable.resolve()), "--browser", "--port", str(port)] if executable
                   else [sys.executable, str(ROOT / "launcher.py"), "--browser", "--port", str(port)])
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        base = f"http://127.0.0.1:{port}/api/v1"
        report: dict[str, Any] = {"schema": "shorts-v21-runtime-check-1", "runtime": "packaged" if executable else "source"}
        try:
            deadline = time.monotonic() + 90
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Runtime exited before becoming healthy")
                try:
                    if _request(f"{base}/health")[0] == 200:
                        break
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Runtime did not become healthy")
                time.sleep(0.25)
            assert _request(f"{base}/system")[0] == 401, "Anonymous system request was accepted"
            assert _request(f"{base}/system", token)[0] == 200, "Authenticated system request failed"
            if expected_version:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                try:
                    connection.request("GET", "/", headers={"Authorization": f"Bearer {token}"})
                    response = connection.getresponse()
                    html = response.read().decode("utf-8")
                    match = re.search(r'<meta name="shorts-studio-version" content="([^"]+)"', html)
                    assert response.status == 200 and match and match[1] == expected_version, "Packaged UI version mismatch"
                    report["ui_version"] = match[1]
                finally:
                    connection.close()
            print("Runtime health and authentication passed", flush=True)
            status, catalog = _request(f"{base}/story/models", token)
            assert status == 200, "Evidence model discovery failed"
            models = {item["id"]: item for item in catalog["models"]}
            assert models["silero-vad"]["available"], "Packaged local speech model is unavailable"
            if require_ocr and not models["tesseract"]["available"]:
                raise RuntimeError("Real OCR was required but Tesseract is unavailable")
            payload = {"audio_model": "silero-vad", "duration_seconds": 2, "max_frames": 2}
            if models["tesseract"]["available"]:
                payload["ocr_model"] = "tesseract"
            status, analyzed = _request(f"{base}/jobs/v21-smoke/story/analyze", token, payload, "POST")
            assert status == 200, f"Local evidence failed with {status}: {analyzed.get('code', 'unknown')}"
            evidence = analyzed["evidence"]
            assert evidence["audio"] == [], "A pure tone was incorrectly treated as speech"
            report["audio"] = "passed"
            report["ocr"] = "unavailable"
            if payload.get("ocr_model"):
                status, searched = _request(f"{base}/story/search", token, {"query": "revenue", "job_ids": ["v21-smoke"]}, "POST")
                assert status == 200 and any(item["kind"] == "ocr" for item in searched["results"]), "Real OCR did not produce searchable fixture text"
                report["ocr"] = "passed"
            assert _request(f"{base}/jobs/v21-smoke/story/analyze", token, method="DELETE")[0] == 200
            assert _request(f"{base}/jobs/v21-smoke/story/analyze", token)[1]["evidence"] is None
            assert _request(f"{base}/shutdown", token, {}, "POST")[0] == 200
            process.wait(timeout=20)
            assert process.returncode == 0, "Runtime did not exit cleanly"
            report.update({"health": 200, "anonymous_system": 401, "authenticated_system": 200, "shutdown": "clean", "status": "passed"})
            return report
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--tesseract", type=Path)
    parser.add_argument("--require-ocr", action="store_true")
    parser.add_argument("--expected-version", help="Require the served UI to match the release version")
    parser.add_argument("--output", type=Path, default=ROOT / "release" / "v21-runtime-check.json")
    args = parser.parse_args()
    try:
        report = verify(args.executable, require_ocr=args.require_ocr, tesseract=args.tesseract, expected_version=args.expected_version)
    except (AssertionError, OSError, RuntimeError, ValueError, subprocess.SubprocessError, http.client.HTTPException) as exc:
        detail = str(exc)[:300] if isinstance(exc, (AssertionError, RuntimeError, ValueError)) else "Runtime check failed; inspect the local environment"
        report = {"status": "failed", "error_type": type(exc).__name__, "error": detail}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
