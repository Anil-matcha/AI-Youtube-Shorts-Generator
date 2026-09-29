"""Safe local Whisper model discovery and download controls."""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List


MODEL_CATALOG: Dict[str, Dict[str, Any]] = {
    "tiny": {"label": "Tiny", "size_gb": 0.08, "description": "Fastest startup; lowest accuracy."},
    "base": {"label": "Base", "size_gb": 0.15, "description": "Balanced default for most clips."},
    "small": {"label": "Small", "size_gb": 0.5, "description": "Higher accuracy with more memory."},
    "medium": {"label": "Medium", "size_gb": 1.5, "description": "High accuracy; slower on CPU."},
    "large-v3": {"label": "Large v3", "size_gb": 3.1, "description": "Best accuracy; needs substantial memory/GPU."},
}

_lock = threading.RLock()
_states: Dict[str, Dict[str, Any]] = {}


def valid_model(name: str) -> bool:
    return str(name or "").strip().lower() in MODEL_CATALOG


def _cache_roots() -> List[Path]:
    roots: List[Path] = []
    for env_name in ("HF_HOME", "HUGGINGFACE_HUB_CACHE"):
        value = os.getenv(env_name, "").strip()
        if value:
            path = Path(value).expanduser()
            roots.extend([path / "hub", path])
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
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


def installed(name: str) -> bool:
    return valid_model(name) and any(path.is_dir() for path in _model_dirs(name))


def _state(name: str) -> Dict[str, Any]:
    with _lock:
        current = dict(_states.get(name) or {})
    return {
        "name": name,
        "status": current.get("status") or ("ready" if installed(name) else "not_installed"),
        "progress": float(current.get("progress") or (100 if installed(name) else 0)),
        "message": str(current.get("message") or ("Ready" if installed(name) else "Not installed")),
        "updated_at": current.get("updated_at"),
        "error": current.get("error"),
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
    if installed(model):
        return _set_state(model, status="ready", progress=100, message="Already installed", error=None)
    with _lock:
        current = _states.get(model) or {}
        if current.get("status") == "downloading":
            return _state(model)
        _states[model] = {"status": "downloading", "progress": 5, "message": "Starting model download", "error": None}
    thread = threading.Thread(target=_download_worker, args=(model,), name=f"shorts-model-{model}", daemon=True)
    thread.start()
    return _state(model)


def _download_worker(model: str) -> None:
    try:
        _set_state(model, progress=15, message="Loading faster-whisper; Hugging Face may download several files")
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        # CPU/int8 is intentionally used for the manager probe.  The selected
        # runtime device remains a separate render setting and can be CUDA.
        probe = WhisperModel(model, device="cpu", compute_type="int8")
        del probe
        if not installed(model):
            raise RuntimeError("model loader completed without creating a recognized cache entry")
        _set_state(model, status="ready", progress=100, message="Model installed", error=None)
    except Exception as exc:  # pragma: no cover - depends on optional downloads
        _set_state(model, status="error", progress=0, message="Model download failed", error=str(exc)[:500])


def delete(name: str) -> Dict[str, Any]:
    model = str(name or "").strip().lower()
    if not valid_model(model):
        raise ValueError("unknown Whisper model")
    removed = 0
    for path in _model_dirs(model):
        try:
            resolved = path.expanduser().resolve()
            root = path.parent.expanduser().resolve()
            resolved.relative_to(root)
            if resolved.name != f"models--Systran--faster-whisper-{model}" or not resolved.is_dir():
                continue
            removed += sum(item.stat().st_size for item in resolved.rglob("*") if item.is_file())
            shutil.rmtree(resolved)
        except (OSError, RuntimeError, ValueError):
            continue
    _set_state(model, status="not_installed", progress=0, message="Model cache removed", error=None)
    return {"name": model, "removed_bytes": removed, "state": _state(model)}
