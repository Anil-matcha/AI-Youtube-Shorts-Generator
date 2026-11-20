"""Guarded Temporal Non-Maximum Suppression (T-NMS) and archetype diversity engine.

Enforces:
- Strict zero-overlap temporal separation with configurable guard bands (default >= 45s).
- Balanced representation across canonical narrative archetypes.
- Semantic redundancy suppression via n-gram Jaccard similarity.
- Monotonic annealing relaxation when candidate pools are tightly constrained.
"""

import math
from typing import Dict, List, Optional, Set, Tuple

from .diversity_types import CandidateHighlight, HighlightArchetype


class GuardedTNMSDiversityEngine:
    """Non-Maximum Suppression engine optimizing temporal spacing and content diversity."""

    def __init__(
        self,
        guard_band: float = 45.0,
        min_guard_band: float = 15.0,
        annealing_gamma: float = 0.75,
        max_similarity_threshold: float = 0.35,
    ):
        """Initialize diversity engine with temporal and semantic parameters.

        Args:
            guard_band: Initial temporal separation buffer in seconds between clips.
            min_guard_band: Absolute minimum guard band floor in seconds.
            annealing_gamma: Decay factor applied per annealing iteration.
            max_similarity_threshold: Maximum allowable hook text Jaccard similarity.
        """
        self.default_guard_band = guard_band
        self.min_guard_band = min_guard_band
        self.annealing_gamma = annealing_gamma
        self.max_similarity_threshold = max_similarity_threshold

    @staticmethod
    def compute_jaccard_similarity(text_a: str, text_b: str) -> float:
        """Compute word tri-gram Jaccard similarity between two hook sentences.

        Args:
            text_a: First hook sentence.
            text_b: Second hook sentence.

        Returns:
            Jaccard similarity coefficient (0.0 to 1.0).
        """
        tokens_a = (text_a or "").lower().split()
        tokens_b = (text_b or "").lower().split()

        if len(tokens_a) < 3 or len(tokens_b) < 3:
            set_a = set(tokens_a)
            set_b = set(tokens_b)
        else:
            set_a = set(zip(tokens_a, tokens_a[1:], tokens_a[2:]))
            set_b = set(zip(tokens_b, tokens_b[1:], tokens_b[2:]))

        intersection = len(set_a.intersection(set_b))
        union = len(set_a.union(set_b))
        return float(intersection / union) if union > 0 else 0.0

    @staticmethod
    def is_temporally_disjoint(
        candidate_interval: Tuple[float, float],
        occupied_intervals: List[Tuple[float, float]],
        guard_band: float,
    ) -> bool:
        """Verify candidate interval respects guard band against all occupied intervals.

        Args:
            candidate_interval: Tuple of (start, end) for candidate.
            occupied_intervals: List of already claimed (start, end) intervals.
            guard_band: Required temporal clearance buffer in seconds.

        Returns:
            True if candidate is strictly non-overlapping and beyond guard buffer.
        """
        c_start, c_end = candidate_interval
        for o_start, o_end in occupied_intervals:
            latest_start = max(c_start, o_start)
            earliest_end = min(c_end, o_end)
            if earliest_end > latest_start:
                return False

            if c_start >= o_end:
                gap = c_start - o_end
            else:
                gap = o_start - c_end

            if gap < guard_band:
                return False

        return True

    def select_diverse_highlights(
        self,
        candidates: List[CandidateHighlight],
        target_count: int,
        historical_intervals: Optional[List[Tuple[float, float]]] = None,
    ) -> List[CandidateHighlight]:
        """Greedy Guarded T-NMS with Archetype Quotas and Monotonic Annealing.

        Args:
            candidates: List of CandidateHighlight instances.
            target_count: Desired number of distinct highlights.
            historical_intervals: Exclusion intervals from prior extraction runs.

        Returns:
            Optimized, non-overlapping, archetype-diverse list of CandidateHighlights.
        """
        pool = sorted(candidates, key=lambda c: c.score, reverse=True)
        current_guard = self.default_guard_band
        selected: List[CandidateHighlight] = []
        occupied: List[Tuple[float, float]] = list(historical_intervals or [])
        archetype_counts: Dict[str, int] = {}

        num_archetypes = len(HighlightArchetype)
        max_per_archetype = max(1, math.ceil(target_count / num_archetypes))

        max_passes = 4
        current_pass = 0

        while len(selected) < target_count and current_pass < max_passes:
            for cand in pool:
                if cand in selected:
                    continue

                start = cand.snapped_start if cand.is_snapped else cand.raw_start
                end = cand.snapped_end if cand.is_snapped else cand.raw_end
                c_interval = (start, end)

                if not self.is_temporally_disjoint(c_interval, occupied, current_guard):
                    continue

                arch_key = cand.archetype.value
                current_count = archetype_counts.get(arch_key, 0)
                if current_count >= max_per_archetype and len(selected) < (num_archetypes * max_per_archetype):
                    continue

                is_redundant = False
                for s in selected:
                    sim = self.compute_jaccard_similarity(cand.hook_sentence, s.hook_sentence)
                    if sim > self.max_similarity_threshold:
                        is_redundant = True
                        break
                if is_redundant:
                    continue

                selected.append(cand)
                occupied.append(c_interval)
                archetype_counts[arch_key] = current_count + 1

                if len(selected) == target_count:
                    break

            if len(selected) < target_count:
                current_pass += 1
                current_guard = max(self.min_guard_band, current_guard * self.annealing_gamma)
                max_per_archetype += 1

        return selected
