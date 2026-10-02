"""Safe local Whisper model discovery and download controls."""

from __future__ import annotations

import json
import errno
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "tiny": {"label": "Tiny", "size_gb": 0.08, "description": "Fastest startup; lowest accuracy."},
    "base": {"label": "Base", "size_gb": 0.15, "description": "Balanced default for most clips."},
    "small": {"label": "Small", "size_gb": 0.5, "description": "Higher accuracy with more memory."},
    "medium": {"label": "Medium", "size_gb": 1.5, "description": "High accuracy; slower on CPU."},
    "large-v3": {"label": "Large v3", "size_gb": 3.1, "description": "Best accuracy; needs substantial memory/GPU."},
}

# Official Systran repository commits, verified 2026-09-30 through the public
# Hub model API. Review and update these immutable pins when changing supported
# model artifacts; existing complete refs/main caches remain usable offline.
MODEL_REVISIONS: Dict[str, str] = {
    "tiny": "d90ca5fe260221311c53c58e660288d3deb8d356",
    "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    "small": "536b0662742c02347bc0e980a01041f333bce120",
    "medium": "08e178d48790749d25932bbc082711ddcfdfbc4f",
    "large-v3": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
}

_lock = threading.RLock()
_states: Dict[str, Dict[str, Any]] = {}
_MAX_ACTIVE_DOWNLOADS = 2
_DOWNLOAD_FILES = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*")


def _download_workers() -> int:
    """Bound file concurrency even when an environment value is malformed."""
    try:
        return max(1, min(8, int(os.getenv("SHORTS_MODEL_DOWNLOAD_WORKERS", "4"))))
    except ValueError:
        return 4


def valid_model(name: str) -> bool:
    return str(name or "").strip().lower() in MODEL_CATALOG


def _cache_roots() -> List[Path]:
    roots: List[Path] = []
    for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        value = os.getenv(env_name, "").strip()
        if value:
            path = Path(value).expanduser()
            roots.append(path)
    hf_home = os.getenv("HF_HOME", "").strip()
    if hf_home:
        roots.append(Path(hf_home).expanduser() / "hub")
    cache_home = os.getenv("XDG_CACHE_HOME", "").strip()
    roots.append((Path(cache_home).expanduser() if cache_home else Path.home() / ".cache") / "huggingface" / "hub")
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots.append(Path(local_app_data) / "huggingface" / "hub")
    unique: List[Path] = []
    seen = set()
    for root in roots:
        resolved = root.expanduser()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _model_dirs(name: str) -> List[Path]:
    token = f"models--Systran--faster-whisper-{name}"
    return [root / token for root in _cache_roots()]


def _snapshot_bytes(snapshot: Path, model_dir: Path) -> Optional[int]:
    """Validate every runtime artifact, including resolved HF blob links.

    A repository directory alone is also created for interrupted downloads.
    Missing tokenizer files can trigger hidden downloads during transcription,
    so they must be present before the manager advertises an offline-ready cache.
    This checks completeness, not the integrity of the model's binary weights.
    """
    try:
        root = model_dir.resolve()
        snapshot.resolve().relative_to(root)
        required = [snapshot / filename for filename in ("model.bin", "config.json", "tokenizer.json")]
        vocabulary = [snapshot / "vocabulary.json", snapshot / "vocabulary.txt"]
        present = [path for path in vocabulary if path.is_file() and path.stat().st_size > 0]
        if not present:
            return None
        required.append(present[0])
        preprocessor = snapshot / "preprocessor_config.json"
        if preprocessor.exists():
            required.append(preprocessor)
        total = 0
        for path in required:
            resolved = path.resolve()
            resolved.relative_to(root)
            if resolved.name.endswith(".incomplete") or not resolved.is_file() or resolved.stat().st_size <= 0:
                return None
            total += resolved.stat().st_size
            if path.suffix == ".json":
                if resolved.stat().st_size > 16 * 1024 * 1024:
                    return None
                value = json.loads(resolved.read_text(encoding="utf-8"))
                if not value or not isinstance(value, (dict, list)):
                    return None
                if path.name in {"config.json", "tokenizer.json", "preprocessor_config.json"} and not isinstance(value, dict):
                    return None
        return total
    except (OSError, RuntimeError, ValueError):
        return None


def cached_snapshot(name: str, *, pinned_only: bool = False) -> Optional[Path]:
    """Find complete pinned or legacy snapshots without SDK imports/networking."""
    model = str(name or "").strip().lower()
    if not valid_model(model):
        return None
    # A download at a SHA does not create refs/main. Prefer this reproducible
    # snapshot across every configured root before considering legacy caches.
    revision = MODEL_REVISIONS[model]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return None
    for model_dir in _model_dirs(model):
        snapshot = model_dir / "snapshots" / revision
        if _snapshot_bytes(snapshot, model_dir) is not None:
            return snapshot
    if pinned_only:
        return None
    for model_dir in _model_dirs(model):
        try:
            # Legacy symbolic downloads resolve refs/main. Do not select an
            # arbitrary historical snapshot when that reference is incomplete.
            revision_file = model_dir / "refs" / "main"
            revision_file.resolve().relative_to(model_dir.resolve())
            if revision_file.stat().st_size > 128:
                continue
            revision = revision_file.read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                continue
            snapshot = model_dir / "snapshots" / revision
            if _snapshot_bytes(snapshot, model_dir) is not None:
                return snapshot
        except (OSError, RuntimeError, ValueError):
            continue
    return None


def installed(name: str) -> bool:
    return cached_snapshot(name) is not None


def _state(name: str) -> Dict[str, Any]:
    with _lock:
        current = dict(_states.get(name) or {})
    snapshot = cached_snapshot(name)
    ready = snapshot is not None
    status = current.get("status") or ("ready" if ready else "not_installed")
    # A cache removed externally must never remain ready in an old in-memory state.
    if status == "ready" and not ready:
        status = "not_installed"
        current = {}
    elapsed = current.get("duration_seconds")
    if status == "downloading" and current.get("started_monotonic") is not None:
        elapsed = round(max(0.0, time.monotonic() - current["started_monotonic"]), 1)
    return {
        "name": name,
        "status": status,
        "progress": float(current.get("progress", 100 if ready else 0)),
        "message": str(current.get("message") or ("Ready" if ready else "Not installed")),
        "updated_at": current.get("updated_at"),
        "error": current.get("error"),
        "duration_seconds": current.get("duration_seconds"),
        "cached_bytes": _snapshot_bytes(snapshot, snapshot.parent.parent) if snapshot else 0,
        "cache_hit": current.get("cache_hit"),
        "download_workers": current.get("download_workers", _download_workers()),
        "phase": current.get("phase", status),
        "elapsed_seconds": elapsed,
        "error_code": current.get("error_code"),
        "retryable": status == "error",
        "progress_measured": status == "ready",
    }


def list_models() -> List[Dict[str, Any]]:
    return [
        {
            "name": name,
            **spec,
            "installed": installed(name),
            "state": _state(name),
        }
        for name, spec in MODEL_CATALOG.items()
    ]


def _set_state(name: str, **values: Any) -> Dict[str, Any]:
    with _lock:
        state = dict(_states.get(name) or {})
        state.update(values)
        state["updated_at"] = time.time()
        _states[name] = state
    return _state(name)


def download(name: str) -> Dict[str, Any]:
    model = str(name or "").strip().lower()
    if not valid_model(model):
        raise ValueError("unknown Whisper model")
    with _lock:
        current = _states.get(model) or {}
        if current.get("status") == "downloading":
            return _state(model)
        if installed(model):
            return _set_state(model, status="ready", progress=100, message="Already installed", error=None,
                              cache_hit=True, duration_seconds=0.0, phase="ready", error_code=None)
        if sum(state.get("status") == "downloading" for state in _states.values()) >= _MAX_ACTIVE_DOWNLOADS:
            raise ValueError("Two model downloads are already active; wait for one to finish")
        _states[model] = {"status": "downloading", "progress": 0, "message": "Starting model download", "error": None,
                          "updated_at": time.time(), "cache_hit": False, "download_workers": _download_workers(),
                          "duration_seconds": None, "started_monotonic": time.monotonic(), "phase": "preparing", "error_code": None}
    thread = threading.Thread(target=_download_worker, args=(model,), name=f"shorts-model-{model}", daemon=True)
    try:
        thread.start()
    except RuntimeError:
        return _set_state(model, status="error", progress=0, message="Model download could not be started",
                          error="A model download worker could not be started; try again", duration_seconds=0.0,
                          phase="error", error_code="worker_unavailable")
    return _state(model)


def _download_worker(model: str) -> None:
    started = time.perf_counter()
    try:
        def phase_changed(phase: str) -> None:
            messages = {"downloading": "Downloading required model files", "validating": "Checking offline cache completeness"}
            _set_state(model, phase=phase, message=messages[phase])

        _download_snapshot(model, workers=int(_state(model)["download_workers"]), phase_callback=phase_changed)
        _set_state(model, status="ready", progress=100, message="Model installed", error=None,
                   duration_seconds=round(time.perf_counter() - started, 4), phase="ready", error_code=None)
    except Exception as exc:
        # SDK errors can contain signed URLs, credentials, or local paths.
        code, error = _download_error(exc)
        _set_state(model, status="error", progress=0, message="Model download failed", error=error,
                   duration_seconds=round(time.perf_counter() - started, 4), phase="error", error_code=code)


def _download_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, ImportError):
        return "dependencies_missing", "Install local dependencies to enable model downloads"
    if isinstance(exc, PermissionError):
        return "cache_permission_denied", "The model cache is not writable; check folder permissions before retrying"
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "disk_full", "Not enough disk space for the model; free space before retrying"
    if isinstance(exc, TimeoutError) or type(exc).__name__ in {"ConnectError", "ConnectTimeout", "ReadTimeout", "ProxyError", "OfflineModeIsEnabled"}:
        return "network_unavailable", "Could not reach the model provider; check connectivity and offline/proxy settings before retrying"
    return "download_failed", "The model download failed or the cache is incomplete; check connectivity and available disk space"


def _download_snapshot(model: str, *, workers: Optional[int] = None, cache_dir: Optional[Path] = None,
                       phase_callback: Optional[Callable[[str], None]] = None) -> Path:
    """Shared explicit-download boundary for the manager and benchmark CLI."""
    if not valid_model(model) or model not in MODEL_CATALOG:
        raise ValueError("unknown Whisper model")
    revision = MODEL_REVISIONS[model]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("supported model revision must be an immutable commit")
    from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

    root = cache_dir if cache_dir is not None else _cache_roots()[0]
    if phase_callback:
        phase_callback("downloading")
    snapshot_download(
        repo_id=f"Systran/faster-whisper-{model}",
        revision=MODEL_REVISIONS[model],
        cache_dir=str(root),
        allow_patterns=list(_DOWNLOAD_FILES),
        max_workers=max(1, min(8, workers)) if workers is not None else _download_workers(),
        token=False,
        endpoint="https://huggingface.co",
        etag_timeout=10,
    )
    model_dir = root / f"models--Systran--faster-whisper-{model}"
    snapshot = model_dir / "snapshots" / revision
    if phase_callback:
        phase_callback("validating")
    if _snapshot_bytes(snapshot, model_dir) is None:
        raise RuntimeError("download did not create a complete model snapshot")
    return snapshot


def delete(name: str) -> Dict[str, Any]:
    model = str(name or "").strip().lower()
    if not valid_model(model):
        raise ValueError("unknown Whisper model")
    with _lock:
        if (_states.get(model) or {}).get("status") == "downloading":
            raise ValueError("Wait for the model download to finish before removing its cache")
        removed = 0
        failed = False
        for path in _model_dirs(model):
            try:
                resolved = path.expanduser().resolve()
                root = path.parent.expanduser().resolve()
                resolved.relative_to(root)
                if resolved != root / path.name or path.is_symlink():
                    failed = True
                    continue
                if not resolved.is_dir():
                    continue
                if resolved.name != f"models--Systran--faster-whisper-{model}":
                    continue
                size = sum(item.lstat().st_size for item in resolved.rglob("*") if item.is_file())
                shutil.rmtree(resolved)
                removed += size
            except (OSError, RuntimeError, ValueError):
                failed = True
        _set_state(model, status="error" if failed else "not_installed", progress=0,
                   message="Some cache files could not be removed" if failed else "Model cache removed",
                   error="Cache removal failed" if failed else None, cache_hit=None, duration_seconds=None,
                   phase="error" if failed else "not_installed", error_code="cache_removal_failed" if failed else None)
        return {"name": model, "removed_bytes": removed, "state": _state(model)}
