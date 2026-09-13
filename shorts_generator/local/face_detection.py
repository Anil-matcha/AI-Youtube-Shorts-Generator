"""Optional modern face detection for local reframing and visual analysis.

The OpenCV SSD detector is preferred when its model files are available.  The
model is intentionally optional so the application remains self-contained and
offline-friendly; ``auto`` falls back to OpenCV's bundled Haar cascade.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from ..config import FACE_DETECTOR, FACE_DNN_CONFIG, FACE_DNN_MODEL

FaceBox = Tuple[int, int, int, int]
FaceDetector = Callable[[Any], List[FaceBox]]


def _model_paths() -> Tuple[Path, Path]:
    """Resolve optional DNN model/config paths for source and frozen builds."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    model = (
        Path(FACE_DNN_MODEL).expanduser()
        if FACE_DNN_MODEL
        else root / "assets" / "face_detector" / "res10_300x300_ssd_iter_140000.caffemodel"
    )
    config = (
        Path(FACE_DNN_CONFIG).expanduser() if FACE_DNN_CONFIG else root / "assets" / "face_detector" / "deploy.prototxt"
    )
    return model, config


def _haar_detector(cv2: Any) -> Optional[FaceDetector]:
    """Build the bundled Haar detector used when no DNN model is installed."""
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except Exception:
        return None
    if cascade.empty():
        return None

    def detect(frame: Any) -> List[FaceBox]:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            values = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
            return [(int(box[0]), int(box[1]), int(box[2]), int(box[3])) for box in values]
        except Exception:
            return []

    return detect


def _dnn_detector(cv2: Any, model_path: Path, config_path: Path) -> Optional[FaceDetector]:
    """Build an OpenCV SSD detector when both model files exist."""
    if not model_path.is_file() or not config_path.is_file():
        return None
    try:
        net = cv2.dnn.readNetFromCaffe(str(config_path), str(model_path))
    except Exception:
        return None

    def detect(frame: Any) -> List[FaceBox]:
        try:
            height, width = frame.shape[:2]
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)),
                1.0,
                (300, 300),
                (104.0, 177.0, 123.0),
            )
            net.setInput(blob)
            detections = net.forward()
            boxes: List[FaceBox] = []
            for index in range(detections.shape[2]):
                confidence = float(detections[0, 0, index, 2])
                if confidence < 0.45:
                    continue
                x1, y1, x2, y2 = (detections[0, 0, index, 3:7] * [width, height, width, height]).astype("int")
                left, top = max(0, x1), max(0, y1)
                right, bottom = min(width, x2), min(height, y2)
                if right - left >= 2 and bottom - top >= 2:
                    boxes.append((left, top, right - left, bottom - top))
            return boxes
        except Exception:
            return []

    return detect


def create_face_detector(cv2: Any) -> Optional[FaceDetector]:
    """Return a configured detector, or ``None`` when tracking is unavailable.

    ``SHORTS_FACE_DETECTOR=dnn`` requires the SSD files and raises a clear
    error when they are missing.  ``auto`` uses DNN when present and otherwise
    falls back to the bundled Haar implementation for backwards compatibility.
    """
    mode = str(FACE_DETECTOR or "auto").strip().lower()
    if mode not in {"auto", "dnn", "haar", "off", "none"}:
        mode = "auto"
    if mode in {"off", "none"}:
        return None
    model_path, config_path = _model_paths()
    if mode in {"auto", "dnn"}:
        detector = _dnn_detector(cv2, model_path, config_path)
        if detector is not None:
            return detector
        if mode == "dnn":
            raise RuntimeError(
                "OpenCV DNN face detector requested, but its model files are missing. "
                "Set SHORTS_FACE_DNN_MODEL and SHORTS_FACE_DNN_CONFIG or use SHORTS_FACE_DETECTOR=auto."
            )
    return _haar_detector(cv2)
