"""Editor and media routes for Shorts Studio.

Rendering state remains in web.app; this module owns HTTP translation for
clip editing, timeline data, exports, and local media streams.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from web.models import ClipUpdate
from web.security import redact_structure
from shorts_generator.config import LOCAL_THUMBNAIL_POSITION, runtime_job_control
from web.feature_routes import _safe_backup_value


def _safe_export_short(studio: Any, value: Dict[str, Any]) -> Dict[str, Any]:
    """Keep export manifests portable without shipping signed media URLs."""
    return _safe_backup_value(redact_structure(value))


router = APIRouter()


def _studio() -> Any:
    """Resolve the stateful app module only when a request is handled."""
    import importlib

    return importlib.import_module("web.app")


def _local_asset(studio: Any, job: Dict[str, Any], value: Any, label: str) -> Optional[str]:
    """Resolve a persisted local asset through the same trust boundary as sources."""
    if not value:
        return None
    path = studio._job_source_path(job, value)
    if not path:
        raise HTTPException(400, f"{label} is unavailable for this job")
    return str(path)


@router.post("/api/jobs/{job_id}/clips/{index}")
def update_clip(job_id: str, index: int, update: ClipUpdate) -> Dict[str, Any]:
    """Regenerate one clip after a manual timestamp/style adjustment."""
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        raw_shorts = studio._dict_items(job.get("raw_shorts"))
        if index < 0 or index >= len(raw_shorts):
            raise HTTPException(404, "clip not found")
        request = studio._dict_value(job.get("request"))
        transcript = job.get("raw_transcript")
        transcript = dict(transcript) if isinstance(transcript, dict) else {}
        source = job.get("raw_source_video_url")
        mode = str(studio._dict_value(job.get("result")).get("mode") or request.get("mode") or "local")

    duration = studio._safe_transcript_duration(transcript)
    if duration and update.start_time >= duration:
        raise HTTPException(400, f"start_time must be before the {duration:.1f}s source")
    if duration and update.end_time > duration + 0.25:
        raise HTTPException(400, f"end_time must be within the {duration:.1f}s source")
    if update.end_time <= update.start_time + 0.1:
        raise HTTPException(400, "end_time must be at least 0.1s after start_time")
    style = (update.caption_style or request.get("caption_style") or "bold").strip().lower()
    if style not in {"clean", "bold", "boxed", "karaoke"}:
        raise HTTPException(400, "caption_style must be clean, bold, boxed, or karaoke")
    if mode == "local":
        safe_source = studio._job_source_path(job, source)
        if not safe_source:
            raise HTTPException(400, "source video is unavailable for this job")
        source = str(safe_source)
    elif source and not str(source).startswith(("http://", "https://")):
        safe_source = studio._job_source_path(job, source)
        if not safe_source:
            raise HTTPException(400, "source video is unavailable for this job")
        source = str(safe_source)
    if not source:
        raise HTTPException(400, "source video is unavailable for this job")

    old = dict(raw_shorts[index])
    try:
        if mode == "local":
            from shorts_generator.local.clipper import _media_duration, _output_filename, crop_clip_local

            old_path = str(old.get("clip_url") or "")
            safe_old_path = studio._job_media_path(job, old_path)
            if safe_old_path and safe_old_path.is_file():
                out_path = str(safe_old_path)
            else:
                job_output_dir = str(studio._job_output_dir(job))
                out_path = str(Path(job_output_dir).expanduser().resolve() / _output_filename(index + 1))
            undo_path = out_path + ".undo.mp4"
            render_path = out_path + ".regenerate.mp4"
            timeline_map = []
            background_music = _local_asset(studio, job, request.get("background_music"), "background music")
            watermark = _local_asset(studio, job, request.get("watermark"), "watermark")
            intro = _local_asset(studio, job, request.get("intro"), "intro")
            outro = _local_asset(studio, job, request.get("outro"), "outro")
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            with studio._media_operation(job_id), runtime_job_control(
                cancel_check=lambda: studio._job_cancelled(job_id),
                register_process=lambda process: studio._register_job_process(job_id, process),
                unregister_process=lambda process: studio._unregister_job_process(job_id, process),
            ):
                crop_clip_local(
                    str(source),
                    update.start_time,
                    update.end_time,
                    str(request.get("aspect_ratio") or "9:16"),
                    render_path,
                    caption_segments=studio._dict_items(transcript.get("segments")),
                    burn_captions=studio.LOCAL_BURN_CAPTIONS,
                    caption_style=style,
                    remove_silence=bool(request.get("remove_silence")),
                    normalize_audio=bool(request.get("normalize_audio")),
                    denoise_audio=bool(request.get("denoise_audio")),
                    remove_filler_words=bool(request.get("remove_filler_words")),
                    caption_position=update.caption_position,
                    caption_font=update.caption_font,
                    caption_size=update.caption_size,
                    caption_color=update.caption_color,
                    background_music=background_music,
                    watermark=watermark,
                    auto_reframe=bool(request.get("auto_reframe", True)),
                    crop_position=update.crop_position,
                    fit_mode=update.fit_mode,
                    zoom=update.zoom,
                    layout=update.layout,
                    output_height=update.output_height,
                    intro=intro,
                    outro=outro,
                    jump_cuts=bool(request.get("jump_cuts")),
                    cuts=[cut.model_dump() for cut in update.cuts],
                    music_volume=update.music_volume if update.music_volume is not None else float(request.get("music_volume", 0.18)),
                    music_fade_in=update.music_fade_in if update.music_fade_in is not None else float(request.get("music_fade_in", 0.0)),
                    music_fade_out=update.music_fade_out if update.music_fade_out is not None else float(request.get("music_fade_out", 0.0)),
                    timeline_map=timeline_map,
                )
            if not os.path.isfile(render_path):
                raise RuntimeError("clip renderer did not produce an output file")
            # Keep the current clip and its previous undo snapshot untouched
            # until the replacement render has completed successfully.
            if os.path.isfile(out_path):
                shutil.copyfile(out_path, undo_path)
            os.replace(render_path, out_path)
            replacement = {
                **old,
                "start_time": update.start_time,
                "end_time": update.end_time,
                "clip_url": out_path,
                "captions_burned": bool(studio.LOCAL_BURN_CAPTIONS and transcript.get("segments")),
                "fit_mode": update.fit_mode,
                "zoom": update.zoom,
                "crop_position": update.crop_position,
                "caption_style": style,
                "caption_position": update.caption_position,
                "caption_font": update.caption_font,
                "caption_size": update.caption_size,
                "caption_color": update.caption_color,
                "layout": update.layout,
                "output_height": update.output_height,
                "cuts": [cut.model_dump() for cut in update.cuts],
                "music_volume": update.music_volume,
                "music_fade_in": update.music_fade_in,
                "music_fade_out": update.music_fade_out,
                "caption_offset": round(_media_duration(intro), 6) if intro else 0.0,
                "timeline_ranges": [
                    {"start_time": round(left, 6), "end_time": round(right, 6)}
                    for left, right in timeline_map
                ],
            }
            replacement["undo_path"] = undo_path if os.path.isfile(undo_path) else None
            replacement["undo_metadata"] = {
                key: value for key, value in old.items() if key not in {"undo_path", "undo_metadata"}
            }
            try:
                from shorts_generator.local.visual import extract_thumbnail

                thumb = str(Path(out_path).with_suffix(".jpg"))
                extract_thumbnail(out_path, LOCAL_THUMBNAIL_POSITION, thumb)
                replacement["thumbnail_path"] = thumb
            except Exception:
                pass
        elif mode == "api":
            unsupported_api_edit = (
                update.cuts
                or update.caption_style not in {None, "bold"}
                or update.caption_position != "bottom"
                or update.caption_font != "Arial"
                or update.caption_size
                or update.caption_color
                or update.layout != "single"
                or update.fit_mode != "crop"
                or update.zoom != 1.0
                or update.crop_position != 0.5
                or update.output_height not in {0, 1920}
                or update.music_volume != 0.18
                or update.music_fade_in
                or update.music_fade_out
            )
            if unsupported_api_edit:
                raise HTTPException(400, "API clips support only start/end timestamps; use Local mode for editor controls")
            from shorts_generator.clipper import crop_clip

            replacement = {
                **old,
                "start_time": update.start_time,
                "end_time": update.end_time,
                "fit_mode": update.fit_mode,
                "zoom": update.zoom,
                "crop_position": update.crop_position,
                "caption_style": style,
                "caption_position": update.caption_position,
                "caption_font": update.caption_font,
                "caption_size": update.caption_size,
                "caption_color": update.caption_color,
                "layout": update.layout,
                "output_height": update.output_height,
                "clip_url": crop_clip(
                    str(source),
                    update.start_time,
                    update.end_time,
                    aspect_ratio=str(request.get("aspect_ratio") or "9:16"),
                ),
            }
        else:
            raise HTTPException(400, f"unsupported job mode: {mode}")
    except HTTPException:
        raise
    except Exception as exc:
        if mode == "local":
            render_path = locals().get("render_path")
            if render_path and os.path.isfile(render_path):
                try:
                    os.remove(render_path)
                except OSError:
                    pass
        raise HTTPException(500, f"could not regenerate clip: {exc}") from exc

    with studio._lock:
        job = studio._jobs[job_id]
        current = studio._dict_items(job.get("raw_shorts"))
        if index >= len(current):
            raise HTTPException(409, "job clips changed while regenerating")
        current[index] = replacement
        job["raw_shorts"] = current
        result = studio._dict_value(job.get("result"))
        result["shorts"] = studio._public_shorts(current, job_id)
        job["result"] = result
        job["message"] = f"Regenerated clip {index + 1}"
        studio._append_job_log(job, "edit", job["message"])
        studio._persist_job_locked(job)
        return studio._job_snapshot(job)


@router.post("/api/jobs/{job_id}/clips/{index}/undo")
def undo_clip(job_id: str, index: int) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
        if index < 0 or index >= len(shorts):
            raise HTTPException(404, "clip not found")
        item = dict(shorts[index])
        undo_path = studio._job_media_path(job, item.get("undo_path"))
        clip_path = studio._job_media_path(job, item.get("clip_url"))
        if not undo_path or not undo_path.is_file() or not clip_path:
            raise HTTPException(400, "no previous clip version is available")
        shutil.copyfile(undo_path, clip_path)
        restored = studio._dict_value(item.get("undo_metadata")) or dict(item)
        restored["clip_url"] = str(clip_path)
        restored.pop("undo_path", None)
        restored.pop("undo_metadata", None)
        # The thumbnail filename is intentionally stable across edits.  Undo
        # restores the media bytes, then re-extracts that thumbnail from the
        # restored video so the card cannot show the newer frame.
        thumbnail = studio._job_media_path(job, restored.get("thumbnail_path"))
        if thumbnail:
            try:
                from shorts_generator.local.visual import extract_thumbnail

                extract_thumbnail(
                    str(clip_path),
                    LOCAL_THUMBNAIL_POSITION,
                    str(thumbnail),
                    text=restored.get("hook_sentence") or restored.get("title") or "",
                )
                restored["thumbnail_path"] = str(thumbnail)
            except Exception:
                # A missing optional OpenCV dependency must not make a valid
                # video undo fail; the existing thumbnail path is retained.
                pass
        shorts[index] = restored
        job["raw_shorts"] = shorts
        result = studio._dict_value(job.get("result"))
        if result:
            result["shorts"] = studio._public_shorts(shorts, job_id)
            job["result"] = result
        studio._persist_job_locked(job)
        return studio._job_snapshot(job)


@router.get("/api/jobs/{job_id}/timeline")
def get_timeline(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        transcript = job.get("raw_transcript")
        if not isinstance(transcript, dict):
            transcript = {}
        return {
            "duration": studio._safe_transcript_duration(transcript),
            "segments": studio._dict_items(transcript.get("segments")),
            "visual_events": studio._dict_items(transcript.get("visual_events")),
        }


@router.get("/api/jobs/{job_id}/waveform")
def get_waveform(job_id: str, bins: int = 240) -> Dict[str, Any]:
    """Return cached audio peaks for a lightweight timeline waveform."""
    studio = _studio()
    bins = max(32, min(600, int(bins or 240)))
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        source = job.get("raw_source_video_url")
        output_dir = studio._job_output_dir(job)
    source_path = studio._job_source_path(job, source)
    if not source_path:
        return {
            "duration": 0.0,
            "peaks": [],
            "available": False,
            "error": "Source audio is unavailable",
            "code": "source_unavailable",
        }
    cache_path = output_dir / "waveform.json"
    try:
        signature = [source_path.stat().st_size, source_path.stat().st_mtime_ns, bins]
    except OSError:
        signature = []
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached.get("signature") == signature and isinstance(cached.get("peaks"), list):
            return {
                "duration": float(cached.get("duration") or 0.0),
                "peaks": cached["peaks"],
                "available": True,
                "cached": True,
            }
    except (OSError, ValueError, TypeError):
        pass
    try:
        from shorts_generator.local.clipper import _find_ffmpeg

        ffmpeg = _find_ffmpeg()
        probe = studio._run_media_command(
            job_id,
            [
                ffmpeg,
                "-hide_banner",
                "-i",
                str(source_path),
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "2000",
                "-v",
                "error",
                "-",
            ],
            timeout=90,
        )
        raw = probe.stdout or b""
        samples = array("h")
        samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
        if not samples:
            return {
                "duration": 0.0,
                "peaks": [],
                "available": False,
                "error": "No audio samples found",
                "code": "audio_unavailable",
            }
        step = max(1, len(samples) // bins)
        peaks = []
        for start in range(0, len(samples), step):
            window = samples[start : start + step]
            peak = max((abs(value) for value in window), default=0) / 32768.0
            peaks.append(round(min(1.0, peak), 4))
            if len(peaks) >= bins:
                break
        duration = len(samples) / 2000.0
        output_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"signature": signature, "duration": duration, "peaks": peaks}), encoding="utf-8"
        )
        return {"duration": duration, "peaks": peaks, "available": True, "cached": False}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, TimeoutError) as exc:
        return {"duration": 0.0, "peaks": [], "available": False, "error": str(exc), "code": "waveform_unavailable"}


@router.get("/api/jobs/{job_id}/export")
def export_job(job_id: str):
    """Download a ZIP containing local clips and creator metadata."""
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        result = studio._dict_value(job.get("result"))
        raw_shorts = studio._dict_items(job.get("raw_shorts"))
        request = studio._dict_value(job.get("request"))

    manifest = {
        "job_id": job_id,
        "request": _safe_backup_value(redact_structure(request)),
        "mode": result.get("mode"),
        "source_video_url": None,
        "shorts": [
            _safe_export_short(studio, {
                **{key: value for key, value in short.items() if key != "clip_url"},
                "creator_metadata": studio._creator_metadata(short),
            })
            for short in raw_shorts
        ],
    }
    # Keep small exports in memory but spill large clip bundles to the system
    # temp directory instead of retaining an unbounded BytesIO allocation.
    archive = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("metadata.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        bundle.writestr(
            "publishing/youtube_shorts.json",
            json.dumps(
                {"platform": "youtube_shorts", "items": [s["creator_metadata"] for s in manifest["shorts"]]},
                ensure_ascii=False,
                indent=2,
            ),
        )
        bundle.writestr(
            "publishing/tiktok.json",
            json.dumps(
                {"platform": "tiktok", "items": [s["creator_metadata"] for s in manifest["shorts"]]},
                ensure_ascii=False,
                indent=2,
            ),
        )
        bundle.writestr(
            "publishing/instagram_reels.json",
            json.dumps(
                {"platform": "instagram_reels", "items": [s["creator_metadata"] for s in manifest["shorts"]]},
                ensure_ascii=False,
                indent=2,
            ),
        )
        for index, short in enumerate(raw_shorts, 1):
            path = studio._job_media_path(job, short.get("clip_url"))
            if path and path.is_file():
                bundle.write(path, arcname=f"clips/short_{index:02d}.mp4")
            elif str(short.get("clip_url") or "").startswith(("http://", "https://")):
                bundle.writestr(
                    f"clips/short_{index:02d}.remote.txt",
                    "Remote media URL intentionally omitted from this export for privacy.\n",
                )
            thumbnail = studio._job_media_path(job, short.get("thumbnail_path"))
            if thumbnail and thumbnail.is_file():
                bundle.write(thumbnail, arcname=f"thumbnails/short_{index:02d}.jpg")
            for caption_format in ("srt", "vtt"):
                caption_text = _captions_for_short(short, job.get("raw_transcript"), caption_format)
                if caption_text:
                    bundle.writestr(f"captions/short_{index:02d}.{caption_format}", caption_text)
    archive.seek(0)

    def archive_stream():
        try:
            while True:
                chunk = archive.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(
        archive_stream(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="shorts_{job_id}.zip"'},
    )


def _subtitle_timestamp(seconds: object, vtt: bool = False) -> str:
    try:
        value = float(seconds)
        if not math.isfinite(value) or value < 0:
            value = 0.0
    except (TypeError, ValueError, OverflowError):
        value = 0.0
    milliseconds = max(0, int(round(value * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_int, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d}{separator}{millis:03d}"


def _captions_for_short(short: Dict[str, Any], transcript: Any, format_name: str = "srt") -> str:
    studio = _studio()
    if not isinstance(short, dict) or not isinstance(transcript, dict):
        return ""
    try:
        clip_start = float(short.get("start_time"))
        clip_end = float(short.get("end_time"))
        if not math.isfinite(clip_start) or not math.isfinite(clip_end) or clip_end <= clip_start:
            return ""
    except (TypeError, ValueError, OverflowError):
        return ""
    vtt = str(format_name).lower() == "vtt"
    lines = ["WEBVTT", ""] if vtt else []
    count = 0
    try:
        caption_offset = float(short.get("caption_offset") or 0.0)
        if not math.isfinite(caption_offset) or caption_offset < 0:
            caption_offset = 0.0
    except (TypeError, ValueError, OverflowError):
        caption_offset = 0.0
    segments = studio._dict_items(transcript.get("segments"))
    cuts = short.get("timeline_ranges") or short.get("cuts")
    if isinstance(cuts, list) and cuts:
        try:
            from shorts_generator.local.clipper import _normalise_cut_ranges, _remap_caption_segments

            ranges = _normalise_cut_ranges(clip_start, clip_end, cuts)
            segments = _remap_caption_segments(segments, ranges)
            clip_start = 0.0
            clip_end = sum(right - left for left, right in ranges)
        except Exception:
            segments = studio._dict_items(transcript.get("segments"))
    for segment in segments:
        try:
            start = float(segment.get("start"))
            end = float(segment.get("end"))
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        left = max(start, clip_start)
        right = min(end, clip_end)
        text = " ".join(str(segment.get("text") or "").split())
        if right <= left or not text:
            continue
        count += 1
        lines.append(f"{count}" if not vtt else "")
        lines.append(
            f"{_subtitle_timestamp(left - clip_start + caption_offset, vtt)} --> "
            f"{_subtitle_timestamp(right - clip_start + caption_offset, vtt)}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines) if count else ""


@router.get("/api/jobs/{job_id}/clip/{index}/captions")
def download_clip_captions(job_id: str, index: int, format: str = "srt"):
    studio = _studio()
    format_name = str(format or "srt").strip().lower()
    if format_name not in {"srt", "vtt"}:
        raise HTTPException(400, "format must be srt or vtt")
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
        transcript = job.get("raw_transcript")
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "clip not found")
    text = _captions_for_short(shorts[index], transcript, format_name)
    if not text:
        raise HTTPException(404, "no captions available for this clip")
    return PlainTextResponse(
        text,
        media_type="text/vtt" if format_name == "vtt" else "application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="short_{index + 1:02d}.{format_name}"'},
    )


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return studio._job_snapshot(job)


@router.get("/api/jobs/{job_id}/clip/{index}")
def get_clip(job_id: str, index: int):
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "clip not found")
    path = shorts[index].get("clip_url")
    if not path or str(path).startswith("http"):
        raise HTTPException(400, "clip is not a local file")
    p = studio._job_media_path(job, path)
    if not p or not p.is_file():
        raise HTTPException(404, f"file missing: {path}")
    return FileResponse(p, media_type="video/mp4", filename=p.name)


@router.post("/api/jobs/{job_id}/preview")
def preview_clip(job_id: str, update: ClipUpdate) -> Dict[str, Any]:
    """Render a lightweight preview using the exact crop settings requested."""
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        request = studio._dict_value(job.get("request"))
        source = job.get("raw_source_video_url")
        transcript = job.get("raw_transcript")
        transcript = dict(transcript) if isinstance(transcript, dict) else {}
        output_dir = str(studio._job_output_dir(job))
    source_path = studio._job_source_path(job, source)
    if not source_path:
        raise HTTPException(400, "a completed local job is required for preview")
    duration = studio._safe_transcript_duration(transcript)
    if duration and update.start_time >= duration:
        raise HTTPException(400, f"start_time must be before the {duration:.1f}s source")
    if duration and update.end_time > duration + 0.25:
        raise HTTPException(400, f"end_time must be within the {duration:.1f}s source")
    if update.end_time <= update.start_time + 0.1:
        raise HTTPException(400, "end_time must be at least 0.1s after start_time")
    style = (update.caption_style or str(request.get("caption_style") or "bold")).strip().lower()
    if style not in {"clean", "bold", "boxed", "karaoke"}:
        raise HTTPException(400, "caption_style must be clean, bold, boxed, or karaoke")
    from shorts_generator.local.clipper import crop_clip_local

    background_music = _local_asset(studio, job, request.get("background_music"), "background music")
    watermark = _local_asset(studio, job, request.get("watermark"), "watermark")
    intro = _local_asset(studio, job, request.get("intro"), "intro")
    outro = _local_asset(studio, job, request.get("outro"), "outro")

    preview_dir = Path(output_dir) / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_stat = source_path.stat()
        source_stamp = [source_stat.st_size, source_stat.st_mtime_ns]
    except OSError:
        source_stamp = []
    preview_payload = {
        "source": source_stamp,
        "start": update.start_time,
        "end": update.end_time,
        "caption_style": style,
        "caption_position": update.caption_position,
        "caption_font": update.caption_font,
        "caption_size": update.caption_size,
        "caption_color": update.caption_color,
        "crop_position": update.crop_position,
        "zoom": update.zoom,
        "fit_mode": update.fit_mode,
        "layout": update.layout,
        "output_height": min(960, update.output_height or 1920),
        "cuts": [cut.model_dump() for cut in update.cuts],
        "music_volume": update.music_volume,
        "music_fade_in": update.music_fade_in,
        "music_fade_out": update.music_fade_out,
    }
    preview_key = hashlib.sha256(json.dumps(preview_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[
        :20
    ]
    cached = preview_dir / f"preview_{preview_key}.mp4"
    preview = Path(output_dir) / "preview.mp4"
    if cached.is_file():
        shutil.copyfile(cached, preview)
        return {
            "preview_url": f"/api/jobs/{job_id}/preview.mp4?key={preview_key}",
            "path": str(preview),
            "cached": True,
        }
    render_path = preview_dir / f"preview_{preview_key}.render.mp4"
    try:
        with studio._media_operation(job_id), runtime_job_control(
            cancel_check=lambda: studio._job_cancelled(job_id),
            register_process=lambda process: studio._register_job_process(job_id, process),
            unregister_process=lambda process: studio._unregister_job_process(job_id, process),
        ):
            crop_clip_local(
                str(source_path),
                update.start_time,
                update.end_time,
                str(request.get("aspect_ratio") or "9:16"),
                str(render_path),
                caption_segments=studio._dict_items(transcript.get("segments")),
                burn_captions=studio.LOCAL_BURN_CAPTIONS,
                caption_style=style,
                caption_position=update.caption_position,
                caption_font=update.caption_font,
                caption_size=update.caption_size,
                caption_color=update.caption_color,
                remove_silence=bool(request.get("remove_silence")),
                normalize_audio=bool(request.get("normalize_audio")),
                denoise_audio=bool(request.get("denoise_audio")),
                remove_filler_words=bool(request.get("remove_filler_words")),
                background_music=background_music,
                watermark=watermark,
                auto_reframe=bool(request.get("auto_reframe", True)),
                crop_position=update.crop_position,
                fit_mode=update.fit_mode,
                zoom=update.zoom,
                layout=update.layout,
                output_height=min(960, update.output_height or 1920),
                intro=intro,
                outro=outro,
                jump_cuts=bool(request.get("jump_cuts")),
                cuts=[cut.model_dump() for cut in update.cuts],
                music_volume=update.music_volume,
                music_fade_in=update.music_fade_in,
                music_fade_out=update.music_fade_out,
            )
        if not render_path.is_file():
            raise RuntimeError("preview renderer did not produce an output file")
        os.replace(render_path, cached)
        shutil.copyfile(cached, preview)
    finally:
        if render_path.is_file():
            try:
                render_path.unlink()
            except OSError:
                pass
    return {"preview_url": f"/api/jobs/{job_id}/preview.mp4?key={preview_key}", "path": str(preview), "cached": False}


@router.get("/api/jobs/{job_id}/preview.mp4")
def get_preview(job_id: str):
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        output_dir = Path(str(job.get("output_dir") or (studio._jobs_dir / job_id)))
        path = studio._job_media_path(job, output_dir / "preview.mp4")
    if not path or not path.is_file():
        raise HTTPException(404, "preview not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/api/jobs/{job_id}/thumbnail/{index}")
def get_thumbnail(job_id: str, index: int):
    studio = _studio()
    with studio._lock:
        job = studio._jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        shorts = studio._dict_items(job.get("raw_shorts"))
    if index < 0 or index >= len(shorts):
        raise HTTPException(404, "thumbnail not found")
    path = shorts[index].get("thumbnail_path")
    safe_path = studio._job_media_path(job, path)
    if not safe_path or not safe_path.is_file():
        raise HTTPException(404, "thumbnail not found")
    return FileResponse(safe_path, media_type="image/jpeg", filename=safe_path.name)
