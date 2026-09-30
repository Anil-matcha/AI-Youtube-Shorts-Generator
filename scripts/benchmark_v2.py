"""Measure the v2 local model-load and first-render path.

The harness is intentionally bounded and produces a machine-readable report.
It does not publish media, contact a provider, or retain the synthetic video.
Run it from the project environment, for example:

    python scripts/benchmark_v2.py --model tiny --device cpu
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _error(exc: BaseException) -> str:
    return " ".join(str(exc).replace("\x00", "").split())[:500] or exc.__class__.__name__


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import ctranslate2  # type: ignore

        return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    except (ImportError, RuntimeError, OSError, AttributeError):
        return "cpu"


def _resolve_ffmpeg() -> Optional[str]:
    try:
        from shorts_generator.local.clipper import _find_ffmpeg

        return _find_ffmpeg()
    except (ImportError, OSError, RuntimeError):
        return shutil.which("ffmpeg")


def _render_benchmark(ffmpeg: Optional[str], timeout: float) -> Dict[str, Any]:
    if not ffmpeg:
        return {"status": "unavailable", "error": "ffmpeg was not found"}
    try:
        from shorts_generator.local.clipper import crop_clip_local
    except (ImportError, OSError, RuntimeError) as exc:
        return {"status": "unavailable", "error": _error(exc)}

    with tempfile.TemporaryDirectory(prefix="shorts-studio-v2-benchmark-") as raw_dir:
        directory = Path(raw_dir)
        source = directory / "synthetic-source.mp4"
        output = directory / "synthetic-short.mp4"
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000",
            "-t",
            "2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(source),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=timeout)
            started = time.perf_counter()
            crop_clip_local(
                str(source),
                0.0,
                1.5,
                "9:16",
                str(output),
                burn_captions=False,
                auto_reframe=False,
                output_height=360,
            )
            elapsed = time.perf_counter() - started
            return {
                "status": "measured",
                "first_render_seconds": round(elapsed, 4),
                "output_bytes": output.stat().st_size if output.is_file() else 0,
                "synthetic_source": {"duration_seconds": 2.0, "width": 320, "height": 180},
            }
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            return {"status": "failed", "error": _error(exc)}


def _model_benchmark(model_name: str, device: str, compute_type: str) -> Dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except (ImportError, OSError) as exc:
        return {"status": "unavailable", "error": _error(exc)}
    started = time.perf_counter()
    try:
        # Construction includes the normal faster-whisper cache lookup and any
        # first-run model download, which is the latency this report is meant to
        # make visible to release planning.
        WhisperModel(model_name, device=device, compute_type=compute_type)
        return {
            "status": "measured",
            "load_seconds": round(time.perf_counter() - started, 4),
            "model": model_name,
            "device": device,
            "compute_type": compute_type,
        }
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        return {
            "status": "failed",
            "load_seconds": round(time.perf_counter() - started, 4),
            "model": model_name,
            "device": device,
            "compute_type": compute_type,
            "error": _error(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("LOCAL_WHISPER_MODEL", "tiny"), help="faster-whisper model name")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--compute-type", default=None, help="Override faster-whisper compute type")
    parser.add_argument("--skip-model", action="store_true", help="Only measure the synthetic first-render path")
    parser.add_argument("--timeout", type=float, default=120.0, help="Synthetic FFmpeg timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("release") / "benchmark-v2.json")
    args = parser.parse_args()

    selected_device = _resolve_device(args.device)
    compute_type = args.compute_type or ("float16" if selected_device == "cuda" else "int8")
    report: Dict[str, Any] = {
        "schema": "shorts-studio-v2-benchmark-1",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor()[:160],
        "requested_device": args.device,
        "selected_device": selected_device,
        "model": args.model,
        "model_load": {"status": "skipped"} if args.skip_model else _model_benchmark(args.model, selected_device, compute_type),
        "first_render": _render_benchmark(_resolve_ffmpeg(), max(5.0, min(args.timeout, 300.0))),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(item.get("status") not in {"failed"} for item in (report["model_load"], report["first_render"])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
