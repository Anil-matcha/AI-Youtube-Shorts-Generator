"""Lightweight local visual-event analysis for highlight ranking."""

from __future__ import annotations

import math
import os
from importlib import import_module
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .face_detection import create_face_detector


def analyze_video(
    media_path: str, sample_seconds: float = 1.0, *, cancel_check: Optional[Callable[[], bool]] = None
) -> List[Dict]:
    """Find scene-change and face/reaction signals without a second ML model."""
    try:
        cv2 = import_module("cv2")
    except ImportError:
        return []

    if not media_path or not os.path.isfile(media_path):
        return []
    cap = cv2.VideoCapture(str(Path(media_path)))
    if not cap.isOpened():
        return []
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
    except (TypeError, ValueError, OverflowError):
        fps = 30.0
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    try:
        frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    except (TypeError, ValueError, OverflowError):
        frame_count = 0.0
    if not math.isfinite(frame_count) or frame_count < 0:
        frame_count = 0.0
    duration = frame_count / fps if frame_count else 0.0
    try:
        sample_interval = float(sample_seconds)
    except (TypeError, ValueError, OverflowError):
        sample_interval = 1.0
    if not math.isfinite(sample_interval):
        sample_interval = 1.0
    step = max(1, int(fps * max(0.25, sample_interval)))
    face_detector = create_face_detector(cv2)
    previous = None
    events: List[Dict] = []
    frame_index = 0
    try:
        while True:
            if cancel_check and cancel_check():
                raise RuntimeError("Job cancelled")
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % step:
                frame_index += 1
                continue
            timestamp = frame_index / fps
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (160, 90))
            face_count = len(face_detector(frame)) if face_detector is not None else 0
            if previous is not None:
                change = float(cv2.absdiff(small, previous).mean())
                if change >= 24.0:
                    events.append(
                        {
                            "time": round(timestamp, 2),
                            "type": "scene_change",
                            "score": round(min(1.0, change / 80.0), 3),
                        }
                    )
            if face_count >= 2:
                events.append(
                    {"time": round(timestamp, 2), "type": "multiple_speakers", "score": min(1.0, face_count / 4.0)}
                )
            elif face_count == 1:
                events.append({"time": round(timestamp, 2), "type": "speaker_visible", "score": 0.35})
            previous = small
            frame_index += 1
            if duration and timestamp >= duration:
                break
    finally:
        cap.release()
    return events


def extract_thumbnail(media_path: str, timestamp: float, out_path: str, text: str = "") -> str:
    """Extract a high-quality JPG frame for a short's thumbnail."""
    try:
        cv2 = import_module("cv2")
    except ImportError as exc:
        raise RuntimeError("opencv-python is required for thumbnail extraction") from exc
    if not media_path or not os.path.isfile(media_path):
        raise RuntimeError(f"could not open {media_path}")
    if not out_path:
        raise RuntimeError("thumbnail output path is required")
    cap = cv2.VideoCapture(str(Path(media_path)))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {media_path}")
    try:
        timestamp_value = float(timestamp)
    except (TypeError, ValueError, OverflowError):
        timestamp_value = 0.0
    if not math.isfinite(timestamp_value):
        timestamp_value = 0.0
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp_value) * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read thumbnail frame at {timestamp_value:.1f}s")
    if text:
        import textwrap

        lines = textwrap.wrap(" ".join(str(text).split()), width=22)[:3]
        y = max(60, frame.shape[0] - 80 * len(lines))
        for line in lines:
            cv2.putText(frame, line, (32, y), cv2.FONT_HERSHEY_DUPLEX, 1.4, (0, 0, 0), 8, cv2.LINE_AA)
            cv2.putText(frame, line, (32, y), cv2.FONT_HERSHEY_DUPLEX, 1.4, (255, 255, 255), 2, cv2.LINE_AA)
            y += 72
    output_path = Path(str(out_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
        raise RuntimeError(f"could not write thumbnail {out_path}")
    return str(output_path)
