"""Stateful clip registry for cross-run history persistence and zero collision.

Manages output/raw/extracted_clips_registry.json with atomic filesystem replacement,
enabling incremental multi-run extractions to respect prior exclusion zones and generate
collision-free monotonic media paths.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .diversity_types import ClipRecord
from .paths import get_raw_dir


class ClipRegistry:
    """Persistent catalog of previously generated shorts."""

    def __init__(self, registry_path: Optional[str] = None):
        """Initialize registry manager with target JSON path.

        Args:
            registry_path: Optional path to registry JSON file.
        """
        if registry_path:
            self.registry_path = Path(registry_path)
        else:
            self.registry_path = get_raw_dir() / "extracted_clips_registry.json"

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict = self._load()

    def _load(self) -> Dict:
        """Load persistent registry from disk or initialize empty state.

        Returns:
            Dictionary containing registry data.
        """
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {"registry_version": "1.0.0", "videos": {}}
        return {"registry_version": "1.0.0", "videos": {}}

    def save_atomic(self) -> None:
        """Atomically persist registry to disk via temporary file replacement."""
        tmp_path = self.registry_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.registry_path)

    def get_existing_intervals(self, video_id: str, guard_band: float = 45.0) -> List[Tuple[float, float]]:
        """Retrieve guarded exclusion intervals for all previously extracted clips.

        Args:
            video_id: Unique video identifier string.
            guard_band: Temporal padding in seconds to expand around prior intervals.

        Returns:
            List of (start, end) exclusion intervals.
        """
        video_entry = self._data.get("videos", {}).get(video_id, {})
        clips = video_entry.get("clips", [])
        intervals: List[Tuple[float, float]] = []
        for c in clips:
            s = float(c["start_time"])
            e = float(c["end_time"])
            intervals.append((max(0.0, s - guard_band), e + guard_band))
        return intervals

    def get_next_sequence_number(self, video_id: str) -> int:
        """Calculate next monotonic sequence index for a video.

        Args:
            video_id: Unique video identifier string.

        Returns:
            Positive integer sequence index.
        """
        video_entry = self._data.get("videos", {}).get(video_id, {})
        clips = video_entry.get("clips", [])
        return len(clips) + 1

    def register_clip(
        self,
        video_id: str,
        start_time: float,
        end_time: float,
        guard_band: float,
        archetype: str,
        score: int,
        title: str,
        hook_sentence: str,
        file_path: str,
    ) -> ClipRecord:
        """Record a newly rendered clip and atomically persist registry state.

        Args:
            video_id: Video identifier string.
            start_time: Rendered start timestamp in seconds.
            end_time: Rendered end timestamp in seconds.
            guard_band: Applied guard buffer in seconds.
            archetype: Narrative archetype string.
            score: Clip virality score.
            title: Headline title.
            hook_sentence: Spoken opening hook.
            file_path: Output file destination path.

        Returns:
            Constructed and persisted ClipRecord instance.
        """
        if "videos" not in self._data:
            self._data["videos"] = {}
        if video_id not in self._data["videos"]:
            self._data["videos"][video_id] = {
                "video_id": video_id,
                "total_clips_extracted": 0,
                "clips": [],
            }

        seq = self.get_next_sequence_number(video_id)
        clip_id = f"short_{video_id}_{seq:03d}_{archetype}"
        record = ClipRecord(
            clip_id=clip_id,
            seq=seq,
            start_time=round(start_time, 3),
            end_time=round(end_time, 3),
            exclusion_zone=(round(max(0.0, start_time - guard_band), 3), round(end_time + guard_band, 3)),
            archetype=archetype,
            score=score,
            title=title,
            hook_sentence=hook_sentence,
            file_path=file_path,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        self._data["videos"][video_id]["clips"].append(record.__dict__)
        self._data["videos"][video_id]["total_clips_extracted"] = seq
        self.save_atomic()
        return record
