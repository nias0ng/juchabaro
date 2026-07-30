"""가변 burst 정책과 실제 frame selector 연결을 검증한다."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from src.ocr import OcrPipelinePolicy
from src.ocr.types import CapturedFrame
from src.ocr.vision import frame_selector as frame_selector_module
from src.ocr.vision.frame_selector import (
    FrameSelectionError,
    QualityFrameSelector,
)


def _frames(count: int) -> tuple[CapturedFrame, ...]:
    return tuple(
        CapturedFrame(
            frame_index=index,
            image=np.zeros((8, 12, 3), dtype=np.uint8),
        )
        for index in range(count)
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


class QualityFrameSelectorPolicyTests(unittest.TestCase):
    def test_opencv_score_stays_in_unit_interval(self) -> None:
        images = (
            np.zeros((8, 12, 3), dtype=np.uint8),
            np.full((8, 12, 3), 127, dtype=np.uint8),
            np.full((8, 12, 3), 255, dtype=np.uint8),
        )

        for frame_index, image in enumerate(images):
            with self.subTest(frame_index=frame_index):
                score = frame_selector_module._score_frame(
                    CapturedFrame(
                        frame_index=frame_index,
                        image=image,
                    )
                )

                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_selector_supports_three_six_and_eight_frames(self) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                scores = [0.1] * frame_count
                scores[1] = 0.8
                scores[2] = 1.0
                policy = OcrPipelinePolicy(frame_count=frame_count)
                with patch.object(
                    frame_selector_module,
                    "_score_frame",
                    side_effect=lambda frame: scores[frame.frame_index],
                ) as score_frame:
                    selection = QualityFrameSelector(
                        policy=policy,
                    ).select_anchors(_frames(frame_count))

                self.assertEqual(selection.earlier_frame_index, 1)
                self.assertEqual(
                    selection.later_frame_index,
                    frame_count - 1,
                )
                self.assertEqual(
                    tuple(
                        call.args[0].frame_index
                        for call in score_frame.call_args_list
                    ),
                    (0, 1),
                )

    def test_early_candidate_count_changes_selection_pool(self) -> None:
        frames = _frames(6)
        scores = (0.2, 0.8, 0.9, 1.0, 0.1, 0.1)

        for early_count, expected_index in ((1, 0), (3, 2)):
            with self.subTest(early_count=early_count):
                with patch.object(
                    frame_selector_module,
                    "_score_frame",
                    side_effect=lambda frame: scores[frame.frame_index],
                ) as score_frame:
                    selection = QualityFrameSelector(
                        policy=OcrPipelinePolicy(
                            frame_count=6,
                            early_anchor_candidate_count=early_count,
                        ),
                    ).select_anchors(frames)

                self.assertEqual(
                    selection.earlier_frame_index,
                    expected_index,
                )
                self.assertEqual(
                    tuple(
                        call.args[0].frame_index
                        for call in score_frame.call_args_list
                    ),
                    tuple(range(early_count)),
                )

    def test_equal_quality_prefers_later_frame_within_early_pool(
        self,
    ) -> None:
        scores = (0.5, 0.5, 1.0)
        with patch.object(
            frame_selector_module,
            "_score_frame",
            side_effect=lambda frame: scores[frame.frame_index],
        ):
            selection = QualityFrameSelector(
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
