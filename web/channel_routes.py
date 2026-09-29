"""Bounded YouTube channel/playlist discovery and batch queue routes."""

from __future__ import annotations

import importlib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from shorts_generator.local.downloader import validate_remote_source
from web.models import ChannelBatchRequest, JobRequest
from web.security import JOB_SUBMISSION_PATH, rate_limit_key


router = APIRouter(tags=["projects"])


def _studio() -> Any:
    return importlib.import_module("web.app")


def extract_channel_entries(source: str, max_items: int) -> List[Dict[str, str]]:
    """Return safe YouTube watch URLs without downloading any media."""
    validated = validate_remote_source(source)
    try:
        yt_dlp = importlib.import_module("yt_dlp")
    except ImportError as exc:
        raise RuntimeError("yt-dlp is required to inspect a channel or playlist") from exc
    options = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "playlistend": int(max_items),
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(validated, download=False)
    except Exception as exc:
        raise RuntimeError(f"could not inspect channel or playlist: {exc}") from exc
    values = info.get("entries") if isinstance(info, dict) else None
    if not isinstance(values, list):
        values = [info] if isinstance(info, dict) else []
    entries: List[Dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        url = str(value.get("webpage_url") or value.get("original_url") or "").strip()
        video_id = str(value.get("id") or "").strip()
        if not url and video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
        if not url or ("youtube.com/" not in url and "youtu.be/" not in url):
            continue
        try:
            safe_url = validate_remote_source(url)
        except ValueError:
            continue
        if safe_url in seen:
            continue
        seen.add(safe_url)
        entries.append({"url": safe_url, "title": " ".join(str(value.get("title") or "").split())[:160]})
        if len(entries) >= max_items:
            break
    if not entries:
        raise RuntimeError("the source did not contain any accessible YouTube videos")
    return entries


def _credentials(
    x_muapi_key: Optional[str],
    x_openai_key: Optional[str],
    x_gemini_key: Optional[str],
    x_llm_provider: Optional[str],
) -> Dict[str, str]:
    return _studio()._runtime_credentials_from_headers(x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider)


@router.post("/api/channel/preview")
def preview_channel(request: ChannelBatchRequest) -> Dict[str, Any]:
    try:
        entries = extract_channel_entries(request.source, request.max_items)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, {"error": str(exc), "code": "source_unavailable"}) from exc
    return {"source": request.source, "count": len(entries), "entries": entries}


@router.post("/api/channel/batch")
def queue_channel(
    request: ChannelBatchRequest,
    http_request: Request,
    x_muapi_key: Optional[str] = Header(default=None, alias="X-MuAPI-Key"),
    x_openai_key: Optional[str] = Header(default=None, alias="X-OpenAI-Key"),
    x_gemini_key: Optional[str] = Header(default=None, alias="X-Gemini-Key"),
    x_llm_provider: Optional[str] = Header(default=None, alias="X-LLM-Provider"),
) -> Dict[str, Any]:
    try:
        entries = extract_channel_entries(request.source, request.max_items)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, {"error": str(exc), "code": "source_unavailable"}) from exc
    studio = _studio()
    limiter, limit = studio._job_budget()
    bucket = rate_limit_key(studio.client_key(http_request), JOB_SUBMISSION_PATH)
    if limiter.remaining(bucket, limit) < len(entries):
        raise HTTPException(429, f"Channel batch of {len(entries)} exceeds the remaining job budget")
    credentials = _credentials(x_muapi_key, x_openai_key, x_gemini_key, x_llm_provider)
    jobs: List[Dict[str, Any]] = []
    prefix = " ".join(str(request.name_prefix or "").split())[:60]
    for index, entry in enumerate(entries, start=1):
        allowed, _retry_after = limiter.allow(bucket, limit)
        if not allowed:
            raise HTTPException(429, "Job budget was exhausted while queuing the channel")
        name = f"{prefix} {index}".strip() if prefix else entry.get("title") or f"Channel video {index}"
        job_request = JobRequest(
            url=entry["url"],
            name=name[:80],
            mode=request.mode,
            num_clips=request.num_clips,
            aspect_ratio=request.aspect_ratio,
            download_format=request.download_format,
            language=request.language,
        )
        jobs.append(studio._enqueue_job(job_request, credentials, factory_mode=request.factory_mode))
    return {
        "source": request.source,
        "count": len(jobs),
        "entries": entries,
        "jobs": jobs,
        "factory_mode": request.factory_mode,
    }
