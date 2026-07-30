"""확정된 OCR 후보 집계 임계값과 투표 경계를 검증한다."""

from __future__ import annotations

import math
import unittest

from src.ocr.postprocessing.aggregator import (
    AggregationError,
    AggregationPolicy,
    PlateAggregator,
)
from src.ocr.types import OcrCandidate, ReadStatus


def _candidate(
    frame_index: int,
    plate_number: str,
    *,
    score: float = 0.9,
) -> OcrCandidate:
    return OcrCandidate(
        frame_index=frame_index,
        raw_text=plate_number,
        normalized_text=plate_number,
        rec_score=score,
        valid_format=True,
    )


class AggregationPolicyTests(unittest.TestCase):
    def test_default_policy_uses_confirmed_thresholds(self) -> None:
        policy = AggregationPolicy()

        self.assertEqual(policy.min_rec_score, 0.40)
        self.assertEqual(policy.min_valid_frames, 2)
        self.assertEqual(policy.min_vote_ratio, 0.60)
        self.assertEqual(policy.min_margin_ratio, 0.20)
        self.assertFalse(hasattr(policy, "min_vote_count"))

    def test_policy_rejects_invalid_probability_values(self) -> None:
        invalid_values = (
            -0.1,
            1.1,
            math.nan,
            math.inf,
            -math.inf,
            True,
            "0.5",
        )

        for field_name in (
            "min_rec_score",
            "min_vote_ratio",
            "min_margin_ratio",
        ):
            for value in invalid_values:
                with self.subTest(field=field_name, value=value):
                    with self.assertRaises(AggregationError):
                        AggregationPolicy(
                            **{field_name: value}
                        )

    def test_policy_rejects_invalid_min_valid_frames(self) -> None:
        for value in (0, -1, True, 2.0, "2"):
            with self.subTest(value=value):
                with self.assertRaises(AggregationError):
                    AggregationPolicy(min_valid_frames=value)

class PlateAggregatorDecisionTests(unittest.TestCase):
    def test_duplicate_frame_candidate_is_rejected(self) -> None:
        with self.assertRaises(AggregationError):
            PlateAggregator().aggregate(
                (
                    _candidate(0, "12가3456"),
                    _candidate(0, "12가3456"),
                )
            )

    def test_empty_normalized_candidates_return_ocr_empty(self) -> None:
        decision = PlateAggregator().aggregate(
            (
                OcrCandidate(
                    frame_index=0,
                    raw_text="---",
                    normalized_text="",
                    rec_score=0.9,
                    valid_format=False,
                ),
            )
        )

        self.assertEqual(decision.status, ReadStatus.OCR_EMPTY)
        self.assertEqual(decision.valid_frames, 0)

    def test_nonempty_invalid_candidates_return_invalid_format(self) -> None:
        decision = PlateAggregator().aggregate(
            (
                OcrCandidate(
                    frame_index=0,
                    raw_text="ABC",
                    normalized_text="ABC",
                    rec_score=0.9,
                    valid_format=False,
                ),
            )
        )

        self.assertEqual(decision.status, ReadStatus.INVALID_FORMAT)
        self.assertEqual(decision.valid_frames, 0)

    def test_two_matching_candidates_at_score_boundary_succeed(
        self,
    ) -> None:
        decision = PlateAggregator().aggregate(
            (
                _candidate(0, "12가3456", score=0.40),
                _candidate(1, "12가3456", score=0.40),
            )
        )

        self.assertEqual(decision.status, ReadStatus.SUCCESS)
        self.assertEqual(decision.plate_number, "12가3456")
        self.assertEqual(decision.valid_frames, 2)
        self.assertEqual(decision.vote_count, 2)
        self.assertEqual(decision.vote_ratio, 1.0)

    def test_candidates_below_score_boundary_return_low_score(
        self,
    ) -> None:
        decision = PlateAggregator().aggregate(
            (
                _candidate(0, "12가3456", score=0.399),
                _candidate(1, "12가3456", score=0.399),
            )
        )

        self.assertEqual(decision.status, ReadStatus.LOW_SCORE)
        self.assertIsNone(decision.plate_number)

    def test_one_valid_candidate_is_ambiguous(self) -> None:
        decision = PlateAggregator().aggregate(
            (_candidate(0, "12가3456"),)
        )

        self.assertEqual(decision.status, ReadStatus.AMBIGUOUS)
        self.assertEqual(decision.valid_frames, 1)
        self.assertEqual(decision.vote_count, 1)
        self.assertIsNone(decision.plate_number)

    def test_two_different_candidates_are_ambiguous(self) -> None:
        decision = PlateAggregator().aggregate(
            (
                _candidate(0, "12가3456"),
                _candidate(1, "34나5678"),
            )
        )

        self.assertEqual(decision.status, ReadStatus.AMBIGUOUS)
        self.assertEqual(decision.vote_count, 1)
        self.assertEqual(decision.vote_ratio, 0.5)

    def test_three_of_five_succeeds_at_ratio_and_margin_boundary(
        self,
    ) -> None:
        decision = PlateAggregator().aggregate(
            (
                _candidate(0, "12가3456"),
                _candidate(1, "12가3456"),
                _candidate(2, "12가3456"),
                _candidate(3, "34나5678"),
                _candidate(4, "34나5678"),
            )
        )

        self.assertEqual(decision.status, ReadStatus.SUCCESS)
        self.assertEqual(decision.vote_count, 3)
        self.assertEqual(decision.vote_ratio, 0.6)

    def test_winner_mean_score_uses_only_winning_candidates(self) -> None:
        decision = PlateAggregator().aggregate(
            (
                _candidate(0, "12가3456", score=0.4),
                _candidate(1, "12가3456", score=0.8),
                _candidate(2, "34나5678", score=1.0),
            )
        )

        self.assertEqual(decision.status, ReadStatus.SUCCESS)
        self.assertAlmostEqual(decision.mean_rec_score, 0.6)

    def test_half_of_four_is_rejected_by_vote_ratio(self) -> None:
        decision = PlateAggregator().aggregate(
            (
                _candidate(0, "12가3456"),
                _candidate(1, "12가3456"),
                _candidate(2, "34나5678"),
                _candidate(3, "56다9012"),
            )
        )

        self.assertEqual(decision.status, ReadStatus.AMBIGUOUS)
        self.assertEqual(decision.vote_count, 2)
        self.assertEqual(decision.vote_ratio, 0.5)

    def test_custom_policy_can_reject_insufficient_margin(self) -> None:
        aggregator = PlateAggregator(
            AggregationPolicy(
                min_vote_ratio=0.50,
                min_margin_ratio=0.20,
            )
        )

        decision = aggregator.aggregate(
            (
                _candidate(0, "12가3456"),
                _candidate(1, "12가3456"),
                _candidate(2, "12가3456"),
                _candidate(3, "34나5678"),
                _candidate(4, "34나5678"),
                _candidate(5, "56다9012"),
            )
        )

        self.assertEqual(decision.status, ReadStatus.AMBIGUOUS)
        self.assertEqual(decision.vote_count, 3)
        self.assertEqual(decision.vote_ratio, 0.5)


if __name__ == "__main__":
    unittest.main()
