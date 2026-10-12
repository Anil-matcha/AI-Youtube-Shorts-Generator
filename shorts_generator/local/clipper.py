"""Local clipping: ffmpeg subclip + OpenCV face-aware vertical crop.

Two stages per highlight:
  1. Cut the source video to [start, end] with ffmpeg (re-encoded, audio kept).
  2. Reframe the cut to the target aspect ratio. For 9:16 we slide a vertical
     window horizontally across the frame to keep faces centred (Haar
     cascade — same approach as the original repo, no external models).
"""
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from ..config import LOCAL_OUTPUT_DIR


def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' → 9/16, '1:1' → 1.0."""
    try:
        w, h = aspect_ratio.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 9.0 / 16.0


def _load_face_cascade():
    """Load the bundled Haar face cascade.

    On Windows OpenCV opens cascade XML through a narrow-char API, so a path
    containing non-ASCII characters (e.g. a project under 下载资源文件/) fails
    to load. Stage a copy under the ASCII-only temp dir when that happens.
    """
    import cv2  # type: ignore

    src = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(src)
    if not cascade.empty():
        return cascade

    staged = os.path.join(tempfile.gettempdir(), os.path.basename(src))
    if not os.path.exists(staged):
        shutil.copyfile(src, staged)
    return cv2.CascadeClassifier(staged)


def _cut_subclip(source_path: str, start: float, end: float, out_path: str) -> str:
    """ffmpeg -ss start -to end → re-encoded mp4 with audio."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", source_path,
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _probe_size(in_path: str) -> Tuple[int, int, float]:
    """Return (width, height, fps), failing with a friendly message if OpenCV is absent."""
    try:
        import cv2  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "opencv-python is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open {in_path}")
    size = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        cap.get(cv2.CAP_PROP_FPS) or 30.0,
    )
    cap.release()
    return size


def _target_size(src_w: int, src_h: int, target_ratio: float) -> Tuple[int, int]:
    """Largest frame at the target ratio that fits inside the source."""
    if target_ratio < src_w / src_h:
        w, h = int(src_h * target_ratio), src_h
    else:
        w, h = src_w, int(src_w / target_ratio)
    return max(2, w - (w % 2)), max(2, h - (h % 2))


def _reframe_fit(in_path: str, out_path: str, target_ratio: float, fit: str) -> str:
    """Letterbox the whole frame into the target ratio — nothing is cropped away.

    Face-tracked cropping keeps the speaker large, but it slides a window only
    ~1/3 as wide as the source across the frame, so anything spanning the full
    source width (slides, burned-in subtitles) gets cut off. These modes shrink
    the whole frame to fit instead, at the cost of a smaller subject.
    """
    src_w, src_h, _ = _probe_size(in_path)
    w, h = _target_size(src_w, src_h, target_ratio)

    if fit == "blur":
        graph = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=18:3[bg];"
            f"[0:v]scale={w}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
    else:
        graph = f"[0:v]scale={w}:-2,pad={w}:{h}:0:(oh-ih)/2:black[v]"

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", in_path,
        "-filter_complex", graph,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _reframe_crop(in_path: str, out_path: str, target_ratio: float) -> str:
    """Crop the cut clip to the target aspect ratio, tracking faces if possible."""
    import cv2  # type: ignore

    src_w, src_h, fps = _probe_size(in_path)
    crop_w, crop_h = _target_size(src_w, src_h, target_ratio)

    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open {in_path}")

    face_cascade = _load_face_cascade()
    detect_faces = not face_cascade.empty()
    if not detect_faces:
        print("[clip/local] face detector unavailable — falling back to centre crop", flush=True)

    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (crop_w, crop_h))

    last_center: Optional[Tuple[int, int]] = None
    smoothing = 0.15  # how aggressively to chase a new face position
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = (
            face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
            if detect_faces
            else []
        )
        if len(faces) > 0:
            # Pick the largest face — usually the speaker.
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx = x + w // 2
            cy = y + h // 2
            if last_center is None:
                last_center = (cx, cy)
            else:
                lx, ly = last_center
                last_center = (
                    int(lx + (cx - lx) * smoothing),
                    int(ly + (cy - ly) * smoothing),
                )
        if last_center is None:
            last_center = (src_w // 2, src_h // 2)

        cx, cy = last_center
        x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
        y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))
        cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
        writer.write(cropped)

    cap.release()
    writer.release()

    # Mux audio from the cut clip back onto the silent reframed video.
    # Re-encode rather than stream-copy: OpenCV's mp4v writer produces MPEG-4
    # Part 2, which Chromium-based players (and most browsers) cannot decode —
    # the clip plays audio-only there. H.264 plays everywhere.
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", silent_path,
        "-i", in_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0?",
        "-movflags", "+faststart",
        "-shortest",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    os.remove(silent_path)
    return out_path


def _reframe_vertical(in_path: str, out_path: str, aspect_ratio: str, fit: str = "crop") -> str:
    """Reframe the cut clip to the target aspect ratio using the requested strategy."""
    target_ratio = _ratio(aspect_ratio)
    if fit == "crop":
        return _reframe_crop(in_path, out_path, target_ratio)
    if fit in ("blur", "letterbox"):
        return _reframe_fit(in_path, out_path, target_ratio, fit)
    raise ValueError(f"Unknown fit={fit!r}. Use 'crop', 'blur' or 'letterbox'.")


def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    aspect_ratio: str,
    out_path: str,
    fit: str = "crop",
) -> str:
    """Cut + reframe one highlight, returning the local mp4 path."""
    cut_path = out_path + ".cut.mp4"
    try:
        _cut_subclip(source_path, start_time, end_time, cut_path)
        _reframe_vertical(cut_path, out_path, aspect_ratio, fit=fit)
    finally:
        if os.path.exists(cut_path):
            os.remove(cut_path)
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    fit: str = "crop",
) -> List[Dict]:
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict] = []
    for i, h in enumerate(highlights, 1):
        out_path = os.path.join(out_dir, f"short_{i:02d}.mp4")
        print(f"[clip/local] {i}/{len(highlights)}: {h.get('title', '(untitled)')}", flush=True)
        try:
            crop_clip_local(
                source_path,
                float(h["start_time"]),
                float(h["end_time"]),
                aspect_ratio,
                out_path,
                fit=fit,
            )
            results.append({**h, "clip_url": out_path})
        except Exception as e:
            print(f"[clip/local] {i} failed: {e}", flush=True)
            results.append({**h, "clip_url": None, "error": str(e)})
    return results
