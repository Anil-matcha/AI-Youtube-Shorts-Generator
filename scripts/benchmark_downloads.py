"""Measure an explicitly authorized public model download in disposable caches.

Existing models and credentials are never reused. Effective throughput measures
runtime artifact bytes divided by wall time, not network wire bytes. Each sample
is cold; the local completeness lookup is measured separately, without networking.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_v2 import _error, _timing_summary
from web.model_manager import MODEL_CATALOG, MODEL_REVISIONS, _download_snapshot, _snapshot_bytes


def _worker(settings: dict[str, Any]) -> dict[str, Any]:
    model = settings["model"]
    root = Path(settings["cache"])
    if model not in MODEL_CATALOG or not 1 <= settings["workers"] <= 8:
        raise ValueError("Invalid download settings")
    if root.exists() and any(root.iterdir()):
        raise ValueError("Cold benchmark requires an empty cache")
    started = time.perf_counter()
    snapshot = _download_snapshot(model, workers=settings["workers"], cache_dir=root)
    duration = time.perf_counter() - started
    lookup_started = time.perf_counter()
    size = _snapshot_bytes(snapshot, root / f"models--Systran--faster-whisper-{model}")
    lookup = time.perf_counter() - lookup_started
    if size is None:
        raise RuntimeError("Downloaded cache is incomplete")
    return {"status": "measured", "download_seconds": round(duration, 4), "runtime_bytes": size,
            "effective_mib_per_second": round(size / (1024 * 1024) / max(duration, 0.0001), 4),
            "offline_validation_seconds": round(lookup, 4)}


def _environment(directory: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        environment.pop(key, None)
    environment.update({"HF_HOME": str(directory / "home"), "HF_HUB_CACHE": str(directory / "hub"),
                        "HUGGINGFACE_HUB_CACHE": str(directory / "hub"), "HF_XET_CACHE": str(directory / "xet"),
                        "HF_TOKEN_PATH": str(directory / "absent-token"), "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
                        "HF_HUB_DISABLE_PROGRESS_BARS": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    return environment


def benchmark(model: str, *, workers: int = 4, repetitions: int = 1, timeout: float = 180) -> dict[str, Any]:
    if model not in MODEL_CATALOG or not 1 <= workers <= 8 or not 1 <= repetitions <= 3:
        raise ValueError("Unsupported model or resource budget")
    if not math.isfinite(timeout) or not 10 <= timeout <= 600:
        raise ValueError("Download timeout must be 10-600 seconds")
    report: dict[str, Any] = {"schema": "shorts-cold-download-1", "model": model, "revision": MODEL_REVISIONS[model],
                              "workers": workers, "network_allowed": True, "cache_reused": False, "samples": []}
    for _ in range(repetitions):
        with tempfile.TemporaryDirectory(prefix="shorts-cold-download-") as raw:
            directory = Path(raw)
            settings = {"model": model, "workers": workers, "cache": str(directory / "hub")}
            try:
                completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                           input=json.dumps(settings), capture_output=True, text=True, check=True,
                                           timeout=timeout, env=_environment(directory),
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                sample = json.loads(completed.stdout)
                if sample.get("status") != "measured":
                    raise RuntimeError("Download sample failed")
                report["samples"].append(sample)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                return {**report, "status": "failed", "error": _error(exc)}
    report.update({"status": "measured", "download_summary": _timing_summary([s["download_seconds"] for s in report["samples"]])})
    return report


def main() -> int:
    if sys.argv[1:] == ["--worker"]:
        try:
            print(json.dumps(_worker(json.loads(sys.stdin.read()))))
            return 0
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": _error(exc)}))
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-download", action="store_true", help="Explicitly permit anonymous public downloads")
    parser.add_argument("--model", choices=tuple(MODEL_CATALOG), default="tiny")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--repetitions", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, default=Path("release/benchmark-v21-download.json"))
    args = parser.parse_args()
    if not args.allow_download:
        parser.error("Cold benchmarks require --allow-download; temporary downloads are deleted after each sample")
    if not math.isfinite(args.timeout) or not 10 <= args.timeout <= 600:
        parser.error("--timeout must be finite and between 10 and 600")
    report = benchmark(args.model, workers=args.workers, repetitions=args.repetitions, timeout=args.timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
