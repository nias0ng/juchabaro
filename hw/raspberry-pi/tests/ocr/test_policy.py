"""가변 burst 정책과 실제 frame selector 연결을 검증한다."""

from __future__ import annotations

from collections.abc import Sequence
import unittest
from unittest.mock import patch

import numpy as np

from src.ocr import OcrPipelinePolicy
from src.ocr.policy import validate_ocr_policy_compatibility
from src.ocr.postprocessing.aggregator import AggregationPolicy
from src.ocr.types import CapturedFrame, FrameQuality
from src.ocr.vision import frame_selector as frame_selector_module
from src.ocr.vision.frame_selector import (
    FrameSelectionError,
    OpenCvFrameQualityEvaluator,
    QualityFrameSelector,
)
from src.ocr.vision.geometry import GeometryConfig


def _frames(count: int) -> tuple[CapturedFrame, ...]:
    return tuple(
        CapturedFrame(
            frame_index=index,
            image=np.zeros((8, 12, 3), dtype=np.uint8),
        )
        for index in range(count)
    )


class StubQualityEvaluator:
    def __init__(self, scores: Sequence[float]) -> None:
        self._scores = tuple(scores)
        self.calls: list[tuple[int, ...]] = []

    def evaluate(
        self,
        frames: Sequence[CapturedFrame],
    ) -> tuple[FrameQuality, ...]:
        self.calls.append(
            tuple(frame.frame_index for frame in frames)
        )
        return tuple(
            FrameQuality(
                frame_index=frame.frame_index,
                sharpness=score,
                contrast=0.0,
                mean_brightness=127.0,
                dark_ratio=0.0,
                bright_ratio=0.0,
                score=score,
            )
            for frame, score in zip(
                frames,
                self._scores,
                strict=True,
            )
        )


class OcrPipelinePolicyTests(unittest.TestCase):
    def test_default_policy_preserves_six_frame_behavior(self) -> None:
        policy = OcrPipelinePolicy()

        self.assertEqual(policy.frame_count, 6)
        self.assertEqual(policy.early_anchor_candidate_count, 2)

    def test_policy_accepts_supported_boundary_values(self) -> None:
        cases = (
            (3, 1),
            (3, 2),
            (6, 1),
            (6, 5),
            (8, 7),
        )

        for frame_count, early_count in cases:
            with self.subTest(
                frame_count=frame_count,
                early_count=early_count,
            ):
                policy = OcrPipelinePolicy(
                    frame_count=frame_count,
                    early_anchor_candidate_count=early_count,
                )

                self.assertEqual(policy.frame_count, frame_count)
                self.assertEqual(
                    policy.early_anchor_candidate_count,
                    early_count,
                )

    def test_policy_rejects_invalid_frame_count(self) -> None:
        for frame_count in (2, 0, -1, True, 3.0, "3"):
            with self.subTest(frame_count=frame_count):
                with self.assertRaises(ValueError):
                    OcrPipelinePolicy(frame_count=frame_count)

    def test_policy_rejects_invalid_early_candidate_count(self) -> None:
        for early_count in (0, -1, 6, 7, True, 2.0, "2"):
            with self.subTest(early_count=early_count):
                with self.assertRaises(ValueError):
                    OcrPipelinePolicy(
                        frame_count=6,
                        early_anchor_candidate_count=early_count,
                    )

    def test_compatible_single_anchor_and_aggregation_policy(self) -> None:
        validate_ocr_policy_compatibility(
            OcrPipelinePolicy(frame_count=3),
            AggregationPolicy(min_valid_frames=2),
            GeometryConfig(single_anchor_reuse_radius=1),
        )

    def test_min_valid_frames_cannot_exceed_frame_count(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "min_valid_frames는 frame_count보다 클 수 없습니다",
        ):
            validate_ocr_policy_compatibility(
                OcrPipelinePolicy(frame_count=3),
                AggregationPolicy(min_valid_frames=4),
                GeometryConfig(single_anchor_reuse_radius=4),
            )

    def test_single_anchor_must_supply_minimum_valid_frames(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "single-anchor fallback",
        ):
            validate_ocr_policy_compatibility(
                OcrPipelinePolicy(frame_count=6),
                AggregationPolicy(min_valid_frames=3),
                GeometryConfig(single_anchor_reuse_radius=1),
            )

    def test_two_anchors_must_supply_minimum_valid_frames(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "two-anchor geometry",
        ):
            validate_ocr_policy_compatibility(
                OcrPipelinePolicy(
                    frame_count=8,
                    early_anchor_candidate_count=7,
                ),
                AggregationPolicy(min_valid_frames=4),
                GeometryConfig(
                    max_extrapolation_frames=0,
                    single_anchor_reuse_radius=3,
                ),
            )

    def test_two_anchor_capacity_boundary_is_compatible(
        self,
    ) -> None:
        validate_ocr_policy_compatibility(
            OcrPipelinePolicy(
                frame_count=8,
                early_anchor_candidate_count=7,
            ),
            AggregationPolicy(min_valid_frames=4),
            GeometryConfig(
                max_extrapolation_frames=2,
                single_anchor_reuse_radius=3,
            ),
        )


class QualityFrameSelectorPolicyTests(unittest.TestCase):
    def test_opencv_evaluator_accepts_variable_frame_sequences(
        self,
    ) -> None:
        evaluator = OpenCvFrameQualityEvaluator()

        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                qualities = evaluator.evaluate(_frames(frame_count))

                self.assertEqual(len(qualities), frame_count)
                self.assertEqual(
                    tuple(
                        quality.frame_index
                        for quality in qualities
                    ),
                    tuple(range(frame_count)),
                )

    def test_selector_supports_three_six_and_eight_frames(self) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                scores = [0.1] * frame_count
                scores[1] = 0.8
                scores[2] = 1.0
                evaluator = StubQualityEvaluator(scores)
                policy = OcrPipelinePolicy(frame_count=frame_count)
                selector = QualityFrameSelector(
                    evaluator,
                    policy=policy,
                )

                selection = selector.select_anchors(
                    _frames(frame_count)
                )

                self.assertEqual(selection.earlier_frame_index, 1)
                self.assertEqual(
                    selection.later_frame_index,
                    frame_count - 1,
                )
                self.assertEqual(
                    evaluator.calls,
                    [tuple(range(frame_count))],
                )

    def test_early_candidate_count_changes_selection_pool(self) -> None:
        frames = _frames(6)
        scores = (0.2, 0.8, 0.9, 1.0, 0.1, 0.1)

        first_only = QualityFrameSelector(
            StubQualityEvaluator(scores),
            policy=OcrPipelinePolicy(
                frame_count=6,
                early_anchor_candidate_count=1,
            ),
        ).select_anchors(frames)
        first_three = QualityFrameSelector(
            StubQualityEvaluator(scores),
            policy=OcrPipelinePolicy(
                frame_count=6,
                early_anchor_candidate_count=3,
            ),
        ).select_anchors(frames)

        self.assertEqual(first_only.earlier_frame_index, 0)
        self.assertEqual(first_three.earlier_frame_index, 2)

    def test_equal_quality_prefers_later_frame_within_early_pool(
        self,
    ) -> None:
        selection = QualityFrameSelector(
            StubQualityEvaluator((0.5, 0.5, 1.0)),
            policy=OcrPipelinePolicy(frame_count=3),
        ).select_anchors(_frames(3))

        self.assertEqual(selection.earlier_frame_index, 1)
        self.assertEqual(selection.later_frame_index, 2)

    def test_opencv_failure_is_typed_and_preserves_cause(self) -> None:
        selector = QualityFrameSelector(
            policy=OcrPipelinePolicy(frame_count=3),
        )
        opencv_error = frame_selector_module.cv2.error(
            "의도한 frame quality 평가 실패"
        )

        with patch.object(
            frame_selector_module.cv2,
            "cvtColor",
            side_effect=opencv_error,
        ):
            with self.assertRaises(FrameSelectionError) as raised:
                selector.select_anchors(_frames(3))

        self.assertIs(raised.exception.__cause__, opencv_error)


if __name__ == "__main__":
    unittest.main()
