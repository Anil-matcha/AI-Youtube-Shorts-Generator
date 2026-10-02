"""Measure the v2 local model-load and first-render path.

The harness is intentionally bounded and produces a machine-readable report.
It uses cached models by default, does not publish media or contact a provider,
and removes synthetic media after each sample. Downloads require --allow-download.
Run it from the project environment, for example:

    python scripts/benchmark_v2.py --model tiny --device cpu
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
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

from web.model_manager import MODEL_CATALOG, _download_snapshot, cached_snapshot


def _error(exc: BaseException) -> str:
    # Exceptions from SDKs can embed signed URLs or credentials. Keep the
    # diagnostic type without copying secrets into a shareable report.
    return f"{exc.__class__.__name__}: benchmark stage failed"


def _timing_summary(samples: list[float]) -> Dict[str, Any]:
    values = sorted(samples)
    return {
        "count": len(values),
        "min_seconds": round(values[0], 4),
        "max_seconds": round(values[-1], 4),
        "mean_seconds": round(statistics.mean(values), 4),
        "median_seconds": round(statistics.median(values), 4),
        "p95_seconds": round(values[max(0, math.ceil(len(values) * 0.95) - 1)], 4),
    }


def _repetitions(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 10:
        raise argparse.ArgumentTypeError("repetitions must be between 1 and 10")
    return number


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
                cancel_check=lambda: time.perf_counter() - started >= timeout,
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


def _model_benchmark(
    model_name: str, device: str, compute_type: str, *, repetitions: int = 1, allow_download: bool = False
) -> Dict[str, Any]:
    if model_name not in MODEL_CATALOG:
        return {"status": "failed", "error": "Only supported Whisper model names can be benchmarked"}
    if not 1 <= repetitions <= 10:
        return {"status": "failed", "error": "repetitions must be between 1 and 10"}
    snapshot = cached_snapshot(model_name)
    cache_hit = snapshot is not None
    download_seconds = 0.0
    if snapshot is None and not allow_download:
        return {"status": "unavailable", "error": "Complete model cache not found; download it in Settings or use --allow-download",
                "model": model_name, "cache_hit": False, "network_allowed": False}
    if snapshot is None:
        download_started = time.perf_counter()
        try:
            snapshot = _download_snapshot(model_name)
            download_seconds = round(time.perf_counter() - download_started, 4)
        except Exception as exc:
            return {"status": "failed", "error": _error(exc), "model": model_name, "cache_hit": False,
                    "download_seconds": round(time.perf_counter() - download_started, 4)}
    try:
        from faster_whisper import WhisperModel
    except (ImportError, OSError) as exc:
        return {"status": "unavailable", "error": _error(exc)}
    samples = []
    details = {"model": model_name, "device": device, "compute_type": compute_type,
               "cache_hit": cache_hit, "network_allowed": allow_download, "download_seconds": download_seconds}
    try:
        for _ in range(repetitions):
            started = time.perf_counter()
            # A complete snapshot path bypasses the model-name resolution and
            # hidden tokenizer fallback downloads of the normal loader.
            model = WhisperModel(str(snapshot), device=device, compute_type=compute_type, local_files_only=True)
            samples.append(round(time.perf_counter() - started, 4))
            del model
        return {
            "status": "measured",
            "load_seconds": samples[0],
            "samples_seconds": samples,
            "summary": _timing_summary(samples),
            **details,
        }
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        return {
            "status": "failed",
            "samples_seconds": samples,
            **details,
            "error": _error(exc),
        }


def _render_samples(ffmpeg: Optional[str], timeout: float, repetitions: int) -> Dict[str, Any]:
    if not 1 <= repetitions <= 10:
        return {"status": "failed", "error": "repetitions must be between 1 and 10"}
    samples = []
    first: Dict[str, Any] = {}
    for _ in range(repetitions):
        measured = _render_benchmark(ffmpeg, timeout)
        if measured["status"] != "measured":
            return {**measured, "samples_seconds": samples}
        if not first:
            first = measured
        samples.append(measured["first_render_seconds"])
    return {**first, "samples_seconds": samples, "summary": _timing_summary(samples)}


def _inference_worker(settings: Dict[str, Any]) -> Dict[str, Any]:
    from faster_whisper import WhisperModel

    model = WhisperModel(settings["snapshot"], device=settings["device"],
                         compute_type=settings["compute_type"], local_files_only=True)
    samples = []
    counts = []
    for _ in range(settings["repetitions"]):
        started = time.perf_counter()
        segments, info = model.transcribe(settings["audio"], language="en", beam_size=5,
                                          vad_filter=False, condition_on_previous_text=False)
        # Decoding is lazy: exhaust the iterator inside the timer. Never emit text.
        counts.append(sum(1 for _segment in segments))
        samples.append(round(time.perf_counter() - started, 4))
    return {"status": "measured", "samples_seconds": samples, "summary": _timing_summary(samples),
            "first_decode_seconds": samples[0], "warm_summary": _timing_summary(samples[1:]) if len(samples) > 1 else None,
            "audio_seconds": round(info.duration, 4), "segment_counts": counts,
            "beam_size": 5, "language": "en", "vad_filter": False,
            "real_time_factor": round(statistics.median(samples) / max(info.duration, 0.001), 4)}


def _inference_benchmark(model_name: str, device: str, compute_type: str, ffmpeg: Optional[str],
                         timeout: float, repetitions: int, media: Path | None = None,
                         cuda_library_dir: Path | None = None) -> Dict[str, Any]:
    snapshot = cached_snapshot(model_name)
    if snapshot is None or not ffmpeg:
        return {"status": "unavailable", "error": "Inference requires a complete cached model and FFmpeg"}
    if media is not None and not media.is_file():
        return {"status": "failed", "error": "Inference media must be an existing local file"}
    if cuda_library_dir is not None and not cuda_library_dir.is_dir():
        return {"status": "failed", "error": "CUDA library directory does not exist"}
    if not 1 <= repetitions <= 10 or not math.isfinite(timeout) or not 5 <= timeout <= 300:
        return {"status": "failed", "error": "Invalid inference resource budget"}
    with tempfile.TemporaryDirectory(prefix="shorts-inference-") as raw:
        audio = Path(raw) / "sample.wav"
        inputs = ["-i", str(media.resolve())] if media else ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000"]
        try:
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *inputs,
                            "-t", "30" if media else "2", "-vn", "-ac", "1", "-ar", "16000", str(audio)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            settings = {"snapshot": str(snapshot), "audio": str(audio), "device": device,
                        "compute_type": compute_type, "repetitions": repetitions}
            environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
            if cuda_library_dir:
                environment["PATH"] = str(cuda_library_dir.resolve()) + os.pathsep + environment.get("PATH", "")
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--inference-worker"],
                                       input=json.dumps(settings), capture_output=True, text=True, check=True,
                                       timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                       env=environment)
            result = json.loads(completed.stdout)
            return {**result, "source_kind": "local-media" if media else "synthetic-tone",
                    "accuracy_measured": False, "model": model_name, "device": device,
                    "compute_type": compute_type, "worker_timeout_seconds": timeout}
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return {"status": "failed", "error": _error(exc)}


def main() -> int:
    if sys.argv[1:] == ["--inference-worker"]:
        try:
            print(json.dumps(_inference_worker(json.loads(sys.stdin.read()))))
            return 0
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": _error(exc)}))
            return 1
    parser = argparse.ArgumentParser(description=__doc__)
    configured_model = os.getenv("LOCAL_WHISPER_MODEL", "tiny").strip().lower()
    parser.add_argument("--model", choices=tuple(MODEL_CATALOG),
                        default=configured_model if configured_model in MODEL_CATALOG else "tiny", help="Supported Whisper model name")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--compute-type", default=None, help="Override faster-whisper compute type")
    parser.add_argument("--skip-model", action="store_true", help="Only measure the synthetic first-render path")
    parser.add_argument("--inference", action="store_true", help="Also measure bounded offline transcription in an isolated worker")
    parser.add_argument("--inference-media", type=Path, help="Use the first 30 seconds of a local file instead of a generated tone")
    parser.add_argument("--cuda-library-dir", type=Path, help="Explicit CUDA DLL directory for the isolated inference worker only")
    parser.add_argument("--allow-download", action="store_true", help="Allow a missing supported model to be downloaded anonymously")
    parser.add_argument("--repetitions", type=_repetitions, default=3, help="Number of model-load/render samples (1–10)")
    parser.add_argument("--timeout", type=float, default=120.0, help="Synthetic FFmpeg timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("release") / "benchmark-v2.json")
    args = parser.parse_args()
    if args.inference_media and not args.inference:
        parser.error("--inference-media requires --inference")
    if args.inference and args.skip_model:
        parser.error("--inference cannot be combined with --skip-model")
    if args.cuda_library_dir and (not args.inference or args.device != "cuda"):
        parser.error("--cuda-library-dir requires --inference --device cuda")
    if not math.isfinite(args.timeout):
        parser.error("--timeout must be finite")

    selected_device = _resolve_device(args.device)
    compute_type = args.compute_type or ("float16" if selected_device == "cuda" else "int8")
    report: Dict[str, Any] = {
        "schema": "shorts-studio-v2-benchmark-3",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor()[:160],
        "requested_device": args.device,
        "selected_device": selected_device,
        "model": args.model,
        "repetitions": args.repetitions,
        "network_allowed": args.allow_download,
        "model_load": {"status": "skipped"} if args.skip_model else _model_benchmark(
            args.model, selected_device, compute_type, repetitions=args.repetitions, allow_download=args.allow_download
        ),
        "first_render": _render_samples(_resolve_ffmpeg(), max(5.0, min(args.timeout, 300.0)), args.repetitions),
    }
    if args.inference:
        report["inference"] = _inference_benchmark(args.model, selected_device, compute_type, _resolve_ffmpeg(),
                                                  max(5.0, min(args.timeout, 300.0)), args.repetitions, args.inference_media,
                                                  args.cuda_library_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    stages = [report["model_load"], report["first_render"]]
    if args.inference:
        stages.append(report["inference"])
    return 0 if all(item.get("status") in {"measured", "skipped"} for item in stages) else 1


if __name__ == "__main__":
    raise SystemExit(main())
