"""Unit and integration test suite for video highlight diversity engine.

Covers:
- AudioBoundarySnapper: Microsecond silence snapping and sentence alignment.
- GuardedTNMSDiversityEngine: Zero-overlap, guard band enforcement, archetype quotas, and annealing.
- ClipRegistry: Atomic cross-run persistence and exclusion zone enforcement.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import List

from shorts_generator.boundary_snapper import AudioBoundarySnapper
from shorts_generator.clip_registry import ClipRegistry
from shorts_generator.diversity_types import CandidateHighlight, HighlightArchetype, WhisperWord
from shorts_generator.tnms_engine import GuardedTNMSDiversityEngine


class TestAudioBoundarySnapper(unittest.TestCase):
    """Test suite for Whisper word acoustic boundary snapping."""

    def setUp(self) -> None:
        """Construct synthetic Whisper word stream with pauses and punctuation."""
        self.words = [
            WhisperWord(word="Hello", start=10.0, end=10.4, probability=0.98),
            WhisperWord(word="world.", start=10.5, end=11.0, probability=0.99),
            WhisperWord(word="We", start=12.0, end=12.2, probability=0.95),
            WhisperWord(word="are", start=12.3, end=12.5, probability=0.97),
            WhisperWord(word="live!", start=12.6, end=13.0, probability=0.99),
            WhisperWord(word="Next", start=40.0, end=40.4, probability=0.95),
            WhisperWord(word="scene", start=40.5, end=40.9, probability=0.97),
            WhisperWord(word="starts", start=41.0, end=41.5, probability=0.96),
            WhisperWord(word="here.", start=41.6, end=42.0, probability=0.99),
        ]
        self.snapper = AudioBoundarySnapper(self.words, min_duration=5.0, max_duration=60.0)

    def test_snap_start_to_sentence_beginning(self) -> None:
        """Verify snapping start timestamp to sentence start with 80ms lead-in."""
        snapped_start = self.snapper.snap_start_boundary(12.1)
        expected_start = round(12.0 - 0.080, 3)
        self.assertAlmostEqual(snapped_start, expected_start, places=2)

    def test_snap_end_to_terminal_punctuation(self) -> None:
        """Verify snapping end timestamp to terminal punctuation with 150ms ring-out."""
        snapped_end = self.snapper.snap_end_boundary(12.8)
        expected_end = round(13.0 + 0.150, 3)
        self.assertAlmostEqual(snapped_end, expected_end, places=2)

    def test_empty_words_graceful_fallback(self) -> None:
        """Verify fallback behavior when word list is empty."""
        empty_snapper = AudioBoundarySnapper([])
        self.assertEqual(empty_snapper.snap_start_boundary(15.5), 15.5)
        self.assertEqual(empty_snapper.snap_end_boundary(45.5), 45.5)

    def test_snap_highlight_object(self) -> None:
        """Verify CandidateHighlight object is correctly mutated and marked as snapped."""
        cand = CandidateHighlight(
            title="Intro Scene",
            raw_start=11.9,
            raw_end=41.9,
            score=90,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
        )
        snapped = self.snapper.snap_highlight(cand)
        self.assertTrue(snapped.is_snapped)
        self.assertLess(snapped.snapped_start, 12.1)
        self.assertGreater(snapped.snapped_end, 41.8)


class TestGuardedTNMSDiversityEngine(unittest.TestCase):
    """Test suite for Guarded T-NMS temporal separation and archetype quotas."""

    def setUp(self) -> None:
        """Initialize diversity engine with standard parameters."""
        self.engine = GuardedTNMSDiversityEngine(
            guard_band=45.0,
            min_guard_band=15.0,
            annealing_gamma=0.75,
            max_similarity_threshold=0.35,
        )

    def test_positive_well_spaced_candidates(self) -> None:
        """Verify well-spaced non-overlapping candidates are preserved in rank order."""
        c1 = CandidateHighlight(
            title="Clip 1",
            raw_start=10.0,
            raw_end=40.0,
            score=95,
            archetype=HighlightArchetype.ACTION_HEIST,
            hook_sentence="This is the craziest heist in the city.",
        )
        c2 = CandidateHighlight(
            title="Clip 2",
            raw_start=120.0,
            raw_end=150.0,
            score=90,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
            hook_sentence="Why are you always driving like a maniac?",
        )
        selected = self.engine.select_diverse_highlights([c1, c2], target_count=2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].title, "Clip 1")
        self.assertEqual(selected[1].title, "Clip 2")

    def test_negative_overlapping_candidate_rejected(self) -> None:
        """Verify candidate with direct temporal overlap is rejected."""
        c1 = CandidateHighlight(
            title="Clip 1",
            raw_start=100.0,
            raw_end=130.0,
            score=95,
            archetype=HighlightArchetype.ACTION_HEIST,
        )
        c2 = CandidateHighlight(
            title="Clip 2 (Overlap)",
            raw_start=115.0,
            raw_end=145.0,
            score=92,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
        )
        selected = self.engine.select_diverse_highlights([c1, c2], target_count=2)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].title, "Clip 1")

    def test_negative_guard_band_violation_rejected(self) -> None:
        """Verify candidate violating 45s guard band is rejected when alternatives exist."""
        c1 = CandidateHighlight(
            title="Clip 1",
            raw_start=100.0,
            raw_end=130.0,
            score=95,
            archetype=HighlightArchetype.ACTION_HEIST,
        )
        c2_too_close = CandidateHighlight(
            title="Clip 2 (Too Close, gap 20s < 45s)",
            raw_start=150.0,
            raw_end=180.0,
            score=92,
            archetype=HighlightArchetype.SATIRE_COMMERCIAL,
        )
        c3_far_enough = CandidateHighlight(
            title="Clip 3 (Clear, gap 70s > 45s)",
            raw_start=200.0,
            raw_end=230.0,
            score=88,
            archetype=HighlightArchetype.LORE_BACKSTORY,
        )
        selected = self.engine.select_diverse_highlights([c1, c2_too_close, c3_far_enough], target_count=2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].title, "Clip 1")
        self.assertEqual(selected[1].title, "Clip 3 (Clear, gap 70s > 45s)")

    def test_edge_case_annealing_relaxes_guard_band_without_overlap(self) -> None:
        """Verify guard band relaxes when candidate pool is tight, while 0% overlap holds."""
        c1 = CandidateHighlight(
            title="Clip 1",
            raw_start=100.0,
            raw_end=130.0,
            score=95,
            archetype=HighlightArchetype.ACTION_HEIST,
        )
        c2_close = CandidateHighlight(
            title="Clip 2 (Gap 25s)",
            raw_start=155.0,
            raw_end=185.0,
            score=90,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
        )
        selected = self.engine.select_diverse_highlights([c1, c2_close], target_count=2)
        self.assertEqual(len(selected), 2)
        self.assertGreater(selected[1].raw_start, selected[0].raw_end)

    def test_archetype_quota_balancing(self) -> None:
        """Verify diverse archetypes are favored over duplicate archetypes."""
        c1 = CandidateHighlight(
            title="Action 1",
            raw_start=10.0,
            raw_end=40.0,
            score=98,
            archetype=HighlightArchetype.ACTION_HEIST,
        )
        c2 = CandidateHighlight(
            title="Action 2",
            raw_start=100.0,
            raw_end=130.0,
            score=96,
            archetype=HighlightArchetype.ACTION_HEIST,
        )
        c3 = CandidateHighlight(
            title="Commercial 1",
            raw_start=200.0,
            raw_end=230.0,
            score=92,
            archetype=HighlightArchetype.SATIRE_COMMERCIAL,
        )
        c4 = CandidateHighlight(
            title="Banter 1",
            raw_start=300.0,
            raw_end=330.0,
            score=90,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
        )
        selected = self.engine.select_diverse_highlights([c1, c2, c3, c4], target_count=3)
        selected_archetypes = [s.archetype for s in selected]
        self.assertEqual(len(selected), 3)
        self.assertIn(HighlightArchetype.ACTION_HEIST, selected_archetypes)
        self.assertIn(HighlightArchetype.SATIRE_COMMERCIAL, selected_archetypes)
        self.assertIn(HighlightArchetype.DIALOGUE_BANTER, selected_archetypes)

    def test_semantic_redundancy_suppression(self) -> None:
        """Verify clips with nearly identical hook text are suppressed."""
        c1 = CandidateHighlight(
            title="First Hook",
            raw_start=10.0,
            raw_end=40.0,
            score=95,
            archetype=HighlightArchetype.ACTION_HEIST,
            hook_sentence="You will not believe what happens to this secret safe in the underground bunker.",
        )
        c2_similar = CandidateHighlight(
            title="Duplicate Hook",
            raw_start=100.0,
            raw_end=130.0,
            score=93,
            archetype=HighlightArchetype.LORE_BACKSTORY,
            hook_sentence="You will not believe what happens inside this secret safe in the underground vault.",
        )
        c3_different = CandidateHighlight(
            title="Unique Hook",
            raw_start=200.0,
            raw_end=230.0,
            score=89,
            archetype=HighlightArchetype.SATIRE_COMMERCIAL,
            hook_sentence="Looking for the best funeral deals in Vice City? Call Hopper Crematory today.",
        )
        selected = self.engine.select_diverse_highlights([c1, c2_similar, c3_different], target_count=2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].title, "First Hook")
        self.assertEqual(selected[1].title, "Unique Hook")


class TestClipRegistryMultiRun(unittest.TestCase):
    """Test suite for atomic registry persistence and cross-run non-repetition."""

    def setUp(self) -> None:
        """Create temporary workspace directory for test registry."""
        self.test_dir = tempfile.mkdtemp()
        self.registry_file = Path(self.test_dir) / "test_registry.json"
        self.registry = ClipRegistry(str(self.registry_file))

    def tearDown(self) -> None:
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_persistence_and_sequence_increment(self) -> None:
        """Verify sequential clip registration increments index and saves atomically."""
        r1 = self.registry.register_clip(
            video_id="test_ep",
            start_time=10.0,
            end_time=40.0,
            guard_band=45.0,
            archetype="ACTION_HEIST",
            score=95,
            title="First Action",
            hook_sentence="Action starts now.",
            file_path="/tmp/short_1.mp4",
        )
        self.assertEqual(r1.seq, 1)
        self.assertEqual(r1.clip_id, "short_test_ep_001_ACTION_HEIST")

        r2 = self.registry.register_clip(
            video_id="test_ep",
            start_time=100.0,
            end_time=130.0,
            guard_band=45.0,
            archetype="SATIRE_COMMERCIAL",
            score=90,
            title="Second Commercial",
            hook_sentence="Commercial break.",
            file_path="/tmp/short_2.mp4",
        )
        self.assertEqual(r2.seq, 2)
        self.assertEqual(r2.clip_id, "short_test_ep_002_SATIRE_COMMERCIAL")

        reloaded = ClipRegistry(str(self.registry_file))
        self.assertEqual(reloaded.get_next_sequence_number("test_ep"), 3)

    def test_multi_run_exclusion_zones(self) -> None:
        """Verify multi-run scenario where Run 2 respects Run 1 exclusion zones."""
        self.registry.register_clip(
            video_id="vid_123",
            start_time=100.0,
            end_time=130.0,
            guard_band=45.0,
            archetype="ACTION_HEIST",
            score=95,
            title="Run 1 Clip",
            hook_sentence="Hook from run 1.",
            file_path="/tmp/r1.mp4",
        )

        hist_intervals = self.registry.get_existing_intervals("vid_123", guard_band=45.0)
        self.assertEqual(len(hist_intervals), 1)
        self.assertEqual(hist_intervals[0], (55.0, 175.0))

        engine = GuardedTNMSDiversityEngine(guard_band=45.0)
        c_colliding = CandidateHighlight(
            title="Colliding Candidate",
            raw_start=110.0,
            raw_end=140.0,
            score=99,
            archetype=HighlightArchetype.ACTION_HEIST,
        )
        c_fresh = CandidateHighlight(
            title="Fresh Candidate",
            raw_start=250.0,
            raw_end=280.0,
            score=85,
            archetype=HighlightArchetype.DIALOGUE_BANTER,
        )
        run_2_selected = engine.select_diverse_highlights(
            [c_colliding, c_fresh],
            target_count=1,
            historical_intervals=hist_intervals,
        )
        self.assertEqual(len(run_2_selected), 1)
        self.assertEqual(run_2_selected[0].title, "Fresh Candidate")


if __name__ == "__main__":
    unittest.main()
