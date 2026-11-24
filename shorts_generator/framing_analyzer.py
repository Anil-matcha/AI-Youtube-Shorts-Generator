"""Automated spatial framing analysis and recommendation engine for vertical video generation.

Categorizes and evaluates framing strategies (split_stack, smart_focus, center,
fit_blur, zoom_blur, strip_letterbox) across narrative archetypes, conversational
cadence, and spatial composition.
"""

import math
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

from .diversity_types import (
    CandidateHighlight,
    FramingMode,
    FramingRecommendation,
    HighlightArchetype,
)


def detect_letterbox_borders(
    image_input: Union[str, Image.Image],
    threshold: int = 18,
    sample_columns: int = 20,
) -> Tuple[bool, int, int, int]:
    """Detect black letterbox borders on top and bottom rows of a frame.

    Args:
        image_input: File path to image or PIL Image object.
        threshold: Maximum luminance value considered black padding (0-255).
        sample_columns: Number of evenly distributed columns to sample for robustness.

    Returns:
        Tuple of (has_letterbox, top_border_height, bottom_border_height, active_height).
    """
    img = Image.open(image_input) if isinstance(image_input, str) else image_input
    img = img.convert("L")
    w, h = img.size

    step_x = max(1, w // sample_columns)
    xs = [min(w - 1, step_x * i) for i in range(sample_columns)]

    top_border = 0
    for y in range(h // 3):
        row_lum = sum(img.getpixel((x, y)) for x in xs) / len(xs)
        if row_lum <= threshold:
            top_border = y + 1
        else:
            break

    bottom_border = 0
    for y in range(h - 1, h - (h // 3), -1):
        row_lum = sum(img.getpixel((x, y)) for x in xs) / len(xs)
        if row_lum <= threshold:
            bottom_border = h - y
        else:
            break

    min_border_threshold = int(h * 0.04)
    has_letterbox = (top_border >= min_border_threshold) or (bottom_border >= min_border_threshold)
    active_height = max(2, h - top_border - bottom_border)
    return has_letterbox, top_border, bottom_border, active_height


def analyze_dialogue_exchanges(
    transcript_segments: List[Dict[str, Any]],
    start_time: float,
    end_time: float,
) -> Tuple[int, float]:
    """Analyze conversational cadence and turn-taking density within a temporal window.

    Args:
        transcript_segments: Full list of Whisper transcript segment dictionaries.
        start_time: Clip start timestamp in seconds.
        end_time: Clip end timestamp in seconds.

    Returns:
        Tuple of (turn_count, average_turn_duration_seconds).
    """
    in_range = [
        s for s in transcript_segments
        if s.get("end", 0.0) >= start_time and s.get("start", 0.0) <= end_time
    ]
    if not in_range:
        return 0, 0.0

    turns = len(in_range)
    total_duration = max(0.001, end_time - start_time)
    avg_turn = total_duration / turns
    return turns, avg_turn


def analyze_spatial_distribution(image_input: Union[str, Image.Image]) -> Dict[str, float]:
    """Analyze visual energy distribution across horizontal thirds of an image.

    Args:
        image_input: File path to image or PIL Image object.

    Returns:
        Dictionary with normalized energy scores: 'left', 'center', and 'right'.
    """
    img = Image.open(image_input) if isinstance(image_input, str) else image_input
    gray = img.convert("L").resize((240, 135))
    w, h = gray.size

    third_w = w // 3
    left_energy = 0.0
    center_energy = 0.0
    right_energy = 0.0

    for y in range(1, h - 1):
        for x in range(1, w - 1):
            gx = gray.getpixel((x + 1, y)) - gray.getpixel((x - 1, y))
            gy = gray.getpixel((x, y + 1)) - gray.getpixel((x, y - 1))
            grad = math.sqrt(gx * gx + gy * gy)
            if x < third_w:
                left_energy += grad
            elif x < 2 * third_w:
                center_energy += grad
            else:
                right_energy += grad

    total = max(1.0, left_energy + center_energy + right_energy)
    return {
        "left": left_energy / total,
        "center": center_energy / total,
        "right": right_energy / total,
    }


class FramingAnalyzer:
    """Intelligent automated scene framing recommender for vertical video production."""

    def __init__(self, target_resolution: str = "4k") -> None:
        """Initialize FramingAnalyzer with target resolution profile.

        Args:
            target_resolution: Target output resolution ('4k' for 2160x3840, '1080p' for 1080x1920).
        """
        self.is_4k = (target_resolution or "4k").lower() == "4k"
        self.target_w = 2160 if self.is_4k else 1080
        self.target_h = 3840 if self.is_4k else 1920

    def recommend_framing(
        self,
        highlight: CandidateHighlight,
        transcript_segments: Optional[List[Dict[str, Any]]] = None,
        keyframe: Optional[Union[str, Image.Image]] = None,
        source_dimensions: Optional[Tuple[int, int]] = None,
    ) -> FramingRecommendation:
        """Evaluate candidate moment features and produce optimal framing recommendation.

        Args:
            highlight: Candidate highlight containing archetype, score, timestamps, and hook.
            transcript_segments: Optional list of Whisper transcript segments.
            keyframe: Optional sample frame for visual composition and letterbox detection.
            source_dimensions: Optional (width, height) tuple of source video media.

        Returns:
            FramingRecommendation detailing mode, confidence, diagnostic reason, and parameters.
        """
        src_w, src_h = source_dimensions or (3840, 2160)
        start_t = highlight.snapped_start if highlight.is_snapped else highlight.raw_start
        end_t = highlight.snapped_end if highlight.is_snapped else highlight.raw_end

        has_letterbox = False
        top_b, bot_b, active_h = 0, 0, src_h
        if keyframe is not None:
            has_letterbox, top_b, bot_b, active_h = detect_letterbox_borders(keyframe)

        spatial_bias: Optional[Dict[str, float]] = None
        if keyframe is not None:
            spatial_bias = analyze_spatial_distribution(keyframe)

        turns = 0
        avg_turn = 0.0
        if transcript_segments:
            turns, avg_turn = analyze_dialogue_exchanges(transcript_segments, start_t, end_t)

        if highlight.archetype == HighlightArchetype.DIALOGUE_BANTER:
            if turns >= 2 and avg_turn <= 6.0:
                def_x_top = int(src_w * 0.47)
                def_x_bot = int(src_w * 0.13)
                if spatial_bias and spatial_bias["left"] > spatial_bias["right"]:
                    def_x_top = int(src_w * 0.12)
                    def_x_bot = int(src_w * 0.46)

                params = {
                    "sub_h_ratio": 0.72,
                    "x_top": def_x_top,
                    "y_top": top_b + int(active_h * 0.05),
                    "x_bot": def_x_bot,
                    "y_bot": top_b + int(active_h * 0.05),
                    "margin_v": 940 if self.is_4k else 470,
                }
                return FramingRecommendation(
                    mode=FramingMode.SPLIT_STACK.value,
                    confidence=0.92,
                    reason=(
                        f"High conversational banter density detected ({turns} dialogue turns, "
                        f"{avg_turn:.1f}s avg). Split stack provides optimal dual-speaker coverage."
                    ),
                    params=params,
                )

        if has_letterbox:
            params = {
                "strip_letterbox": True,
                "active_h": active_h,
                "y_offset": top_b,
                "x_ratio": 0.33,
                "margin_v": 520 if self.is_4k else 260,
            }
            return FramingRecommendation(
                mode=FramingMode.SMART_FOCUS.value,
                confidence=0.88,
                reason=(
                    f"Anamorphic letterbox detected (top border: {top_b}px, bottom border: {bot_b}px). "
                    "Smart focus with active strip avoids horizontal letterbox padding."
                ),
                params=params,
            )

        if highlight.archetype == HighlightArchetype.ACTION_HEIST:
            x_ratio = 0.33
            if spatial_bias:
                if spatial_bias["left"] > 0.45:
                    x_ratio = 0.18
                elif spatial_bias["right"] > 0.45:
                    x_ratio = 0.48

            params = {
                "x_ratio": x_ratio,
                "margin_v": 520 if self.is_4k else 260,
            }
            return FramingRecommendation(
                mode=FramingMode.SMART_FOCUS.value,
                confidence=0.86,
                reason="High-adrenaline action sequence reframed with dynamic rule-of-thirds smart focus.",
                params=params,
            )

        if highlight.archetype == HighlightArchetype.STUNT_FAIL:
            params = {
                "margin_v": 520 if self.is_4k else 260,
            }
            return FramingRecommendation(
                mode=FramingMode.CENTER.value,
                confidence=0.85,
                reason="Sudden physics stunt or crash climax centered for maximum visual punch.",
                params=params,
            )

        if highlight.archetype == HighlightArchetype.LORE_BACKSTORY:
            if spatial_bias and spatial_bias["center"] < 0.25:
                params = {
                    "margin_v": 520 if self.is_4k else 260,
                }
                return FramingRecommendation(
                    mode=FramingMode.FIT_BLUR.value,
                    confidence=0.82,
                    reason="Wide landscape lore/easter-egg scene preserved with ambient blurred canvas.",
                    params=params,
                )

        x_ratio = 0.30
        if spatial_bias:
            if spatial_bias["left"] > spatial_bias["right"] + 0.15:
                x_ratio = 0.18
            elif spatial_bias["right"] > spatial_bias["left"] + 0.15:
                x_ratio = 0.46

        params = {
            "x_ratio": x_ratio,
            "margin_v": 520 if self.is_4k else 260,
        }
        return FramingRecommendation(
            mode=FramingMode.SMART_FOCUS.value,
            confidence=0.80,
            reason="Standard single-subject monologue reframed using adaptive rule-of-thirds smart focus.",
            params=params,
        )


def smooth_speaker_tracking(
    detections: List[Dict],
    frame_width: int,
    deadband_ratio: float = 0.08,
    hold_seconds: float = 2.5
) -> List[Dict]:
    """Smooth detected active speaker centroids using deadband filtering and hysteresis hold.

    Addresses two-person podcast framing instability (Issue #81):
    1. Deadband zone: Suppresses camera pan jitter if speaker centroid drift is within
       the threshold (default 8% of frame width).
    2. Hysteresis hold: Suppresses erratic switching between two speakers by requiring
       the new speaker to persist for at least hold_seconds (default 2.5s) before panning.

    Args:
        detections: List of detection dictionaries containing 'timestamp', 'center_x',
            and optional 'speaker_id'.
        frame_width: Source video frame width in pixels.
        deadband_ratio: Fraction of frame width defining the deadband threshold.
        hold_seconds: Minimum duration before allowing a camera pan switch to another speaker.

    Returns:
        List of smoothed detection dictionaries with 'smoothed_x' and 'active_speaker'.
    """
    if not detections:
        return []

    deadband_px = frame_width * deadband_ratio
    first = detections[0]
    current_x = float(first.get("center_x", frame_width * 0.5))
    current_speaker = first.get("speaker_id", 0)
    last_switch_time = float(first.get("timestamp", 0.0))
    pending_speaker = current_speaker
    pending_speaker_start = last_switch_time

    smoothed: List[Dict] = []
    for det in detections:
        t = float(det.get("timestamp", 0.0))
        target_x = float(det.get("center_x", current_x))
        speaker = det.get("speaker_id", current_speaker)

        if speaker != current_speaker:
            if speaker != pending_speaker:
                pending_speaker = speaker
                pending_speaker_start = t
            elif t - pending_speaker_start >= hold_seconds:
                current_speaker = speaker
                last_switch_time = t
        else:
            pending_speaker = current_speaker

        if abs(target_x - current_x) > deadband_px:
            current_x = current_x + 0.35 * (target_x - current_x)

        smoothed.append({
            "timestamp": t,
            "center_x": target_x,
            "smoothed_x": round(current_x, 2),
            "speaker_id": speaker,
            "active_speaker": current_speaker,
        })

    return smoothed
