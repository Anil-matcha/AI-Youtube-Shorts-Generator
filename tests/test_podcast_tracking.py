"""Triad unit tests for two-person podcast speaker tracking stability and deadband filtering."""
from typing import Dict, List

import pytest

from shorts_generator.framing_analyzer import smooth_speaker_tracking


def test_smooth_speaker_tracking_absorbs_micro_jitter() -> None:
    """Positive: Verify micro-movements within the 8% deadband threshold do not move the camera crop."""
    frame_width = 1920
    detections: List[Dict] = [
        {"timestamp": 0.0, "center_x": 500.0, "speaker_id": 0},
        {"timestamp": 0.1, "center_x": 520.0, "speaker_id": 0},
        {"timestamp": 0.2, "center_x": 490.0, "speaker_id": 0},
        {"timestamp": 0.3, "center_x": 510.0, "speaker_id": 0},
        {"timestamp": 0.4, "center_x": 530.0, "speaker_id": 0},
    ]

    smoothed = smooth_speaker_tracking(detections, frame_width=frame_width, deadband_ratio=0.08)

    assert len(smoothed) == 5
    for item in smoothed:
        assert item["smoothed_x"] == 500.0


def test_smooth_speaker_tracking_pans_on_large_shift() -> None:
    """Positive: Verify intentional subject repositioning exceeding deadband initiates smooth camera panning."""
    frame_width = 1920
    detections: List[Dict] = [
        {"timestamp": 0.0, "center_x": 500.0, "speaker_id": 0},
        {"timestamp": 0.5, "center_x": 1000.0, "speaker_id": 0},
        {"timestamp": 1.0, "center_x": 1000.0, "speaker_id": 0},
        {"timestamp": 1.5, "center_x": 1000.0, "speaker_id": 0},
    ]

    smoothed = smooth_speaker_tracking(detections, frame_width=frame_width, deadband_ratio=0.08)

    assert smoothed[0]["smoothed_x"] == 500.0
    assert smoothed[1]["smoothed_x"] > 500.0
    assert smoothed[2]["smoothed_x"] > smoothed[1]["smoothed_x"]
    assert smoothed[3]["smoothed_x"] > smoothed[2]["smoothed_x"]


def test_smooth_speaker_tracking_hysteresis_suppresses_rapid_flip_flop() -> None:
    """Positive: Verify alternating speaker banter below hold threshold suppresses whip-pan switching."""
    frame_width = 1920
    detections: List[Dict] = [
        {"timestamp": 0.0, "center_x": 400.0, "speaker_id": 0},
        {"timestamp": 0.5, "center_x": 1400.0, "speaker_id": 1},
        {"timestamp": 1.0, "center_x": 400.0, "speaker_id": 0},
        {"timestamp": 1.5, "center_x": 1400.0, "speaker_id": 1},
        {"timestamp": 2.0, "center_x": 400.0, "speaker_id": 0},
    ]

    smoothed = smooth_speaker_tracking(
        detections,
        frame_width=frame_width,
        deadband_ratio=0.08,
        hold_seconds=2.5
    )

    for item in smoothed:
        assert item["active_speaker"] == 0


def test_smooth_speaker_tracking_switches_after_hold_duration() -> None:
    """Positive: Verify continuous speech by a new speaker exceeding hold duration cleanly shifts active speaker."""
    frame_width = 1920
    detections: List[Dict] = [
        {"timestamp": 0.0, "center_x": 400.0, "speaker_id": 0},
        {"timestamp": 1.0, "center_x": 400.0, "speaker_id": 0},
        {"timestamp": 2.0, "center_x": 1400.0, "speaker_id": 1},
        {"timestamp": 3.0, "center_x": 1400.0, "speaker_id": 1},
        {"timestamp": 4.0, "center_x": 1400.0, "speaker_id": 1},
        {"timestamp": 5.0, "center_x": 1400.0, "speaker_id": 1},
    ]

    smoothed = smooth_speaker_tracking(
        detections,
        frame_width=frame_width,
        deadband_ratio=0.08,
        hold_seconds=2.5
    )

    assert smoothed[0]["active_speaker"] == 0
    assert smoothed[1]["active_speaker"] == 0
    assert smoothed[2]["active_speaker"] == 0
    assert smoothed[5]["active_speaker"] == 1


def test_smooth_speaker_tracking_empty_and_single_edge_cases() -> None:
    """Edge Case: Verify graceful handling of empty lists and single-detection inputs."""
    empty_result = smooth_speaker_tracking([], frame_width=1920)
    assert empty_result == []

    single = [{"timestamp": 0.0, "center_x": 750.0, "speaker_id": 2}]
    single_res = smooth_speaker_tracking(single, frame_width=1920)
    assert len(single_res) == 1
    assert single_res[0]["smoothed_x"] == 750.0
    assert single_res[0]["active_speaker"] == 2
