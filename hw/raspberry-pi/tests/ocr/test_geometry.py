"""후보별 geometry 선택, 두 anchor 보간과 single-anchor 재사용을 검증한다."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from src.ocr.vision import geometry as geometry_module
from src.ocr.types import (
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    Quad,
    QuadSource,
)
from src.ocr.vision.geometry import (
    GeometryError,
    GeometryProcessingError,
    PlateGeometry,
)


PLATE_QUAD: Quad = (
    (5.0, 5.0),
    (25.0, 5.0),
    (25.0, 15.0),
    (5.0, 15.0),
)
ALTERNATE_PLATE_QUAD: Quad = (
    (6.0, 6.0),
    (26.0, 6.0),
    (26.0, 16.0),
    (6.0, 16.0),
)


def _frames(count: int = 6) -> tuple[CapturedFrame, ...]:
    return tuple(
        CapturedFrame(
            frame_index=index,
            image=np.zeros((24, 40, 3), dtype=np.uint8),
        )
        for index in range(count)
    )


def _detection(
    frame_index: int,
    *,
    quad: Quad = PLATE_QUAD,
    score: float = 0.9,
) -> DetectedPlate:
    return DetectedPlate(
        frame_index=frame_index,
        bbox_xyxy=(5.0, 5.0, 25.0, 15.0),
        quad=quad,
        detector_score=score,
    )


def _invalid_scene_detection(
    frame_index: int,
    *,
    score: float = 0.9,
) -> DetectedPlate:
    return DetectedPlate(
        frame_index=frame_index,
        bbox_xyxy=(-10.0, -10.0, -1.0, -1.0),
        quad=(
            (-10.0, -10.0),
            (-1.0, -10.0),
            (-1.0, -1.0),
            (-10.0, -1.0),
        ),
        detector_score=score,
    )


class PlateGeometryCharacterizationTests(unittest.TestCase):
    """가변 프레임 정책에서 geometry의 실제 출력 범위를 기록한다."""

    def test_later_single_anchor_produces_last_two_frames(self) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                last_index = frame_count - 1
                estimates = PlateGeometry().estimate_quads(
                    _frames(frame_count),
                    (_detection(last_index),),
                )

                self.assertEqual(
                    tuple(
                        estimate.frame_index
                        for estimate in estimates
                    ),
                    (last_index - 1, last_index),
                )
                self.assertEqual(
                    tuple(estimate.source for estimate in estimates),
                    (QuadSource.REUSED, QuadSource.DETECTED),
                )

    def test_earlier_single_anchor_produces_three_nearby_frames(
        self,
    ) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                estimates = PlateGeometry().estimate_quads(
                    _frames(frame_count),
                    (_detection(1),),
                )

                self.assertEqual(
                    tuple(
                        estimate.frame_index
                        for estimate in estimates
                    ),
                    (0, 1, 2),
                )
                self.assertEqual(
                    tuple(estimate.source for estimate in estimates),
                    (
                        QuadSource.REUSED,
                        QuadSource.DETECTED,
                        QuadSource.REUSED,
                    ),
                )

    def test_two_anchors_cover_three_six_and_eight_frames(self) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                last_index = frame_count - 1
                estimates = PlateGeometry().estimate_quads(
                    _frames(frame_count),
                    (_detection(1), _detection(last_index)),
                )

                self.assertEqual(
                    tuple(
                        estimate.frame_index
                        for estimate in estimates
                    ),
                    tuple(range(frame_count)),
                )
                self.assertEqual(
                    tuple(estimate.source for estimate in estimates),
                    (
                        QuadSource.EXTRAPOLATED,
                        QuadSource.DETECTED,
                        *(
                            QuadSource.INTERPOLATED
                            for _ in range(frame_count - 3)
                        ),
                        QuadSource.DETECTED,
                    ),
                )

    def test_rectify_rejects_invalid_standalone_frame_image(
        self,
    ) -> None:
        estimate = EstimatedQuad(
            frame_index=0,
            quad=PLATE_QUAD,
            source=QuadSource.DETECTED,
            source_anchor_indices=(0,),
        )
        frame = CapturedFrame(
            frame_index=0,
            image=object(),
        )

        with self.assertRaises(GeometryProcessingError):
            PlateGeometry().rectify(frame, estimate)

    def test_scene_invalid_anchor_preserves_rejection_reason(self) -> None:
        with self.assertRaises(GeometryError) as raised:
            PlateGeometry().estimate_quads(
                _frames(),
                (
                    _invalid_scene_detection(1, score=0.95),
                    _invalid_scene_detection(1, score=0.90),
                ),
            )

        self.assertIn("frame_index=1", str(raised.exception))
        self.assertIn("candidate_rank=1", str(raised.exception))
        self.assertIn("candidate_rank=2", str(raised.exception))
        self.assertIn("경계를 벗어납니다", str(raised.exception))

    def test_lower_ranked_geometry_valid_candidate_is_selected(self) -> None:
        estimates = PlateGeometry().estimate_quads(
            _frames(),
            (
                _invalid_scene_detection(1, score=0.95),
                _detection(
                    1,
                    quad=ALTERNATE_PLATE_QUAD,
                    score=0.90,
                ),
            ),
        )

        selected = next(
            estimate
            for estimate in estimates
            if estimate.frame_index == 1
        )
        self.assertEqual(selected.quad, ALTERNATE_PLATE_QUAD)
        self.assertEqual(selected.source, QuadSource.DETECTED)
        self.assertEqual(selected.source_anchor_indices, (1,))

    def test_first_geometry_valid_candidate_keeps_detector_priority(
        self,
    ) -> None:
        estimates = PlateGeometry().estimate_quads(
            _frames(),
            (
                _detection(1, quad=ALTERNATE_PLATE_QUAD, score=0.95),
                _detection(1, quad=PLATE_QUAD, score=0.90),
            ),
        )

        selected = next(
            estimate
            for estimate in estimates
            if estimate.frame_index == 1
        )
        self.assertEqual(selected.quad, ALTERNATE_PLATE_QUAD)

    def test_invalid_candidate_group_falls_back_to_other_anchor(
        self,
    ) -> None:
        estimates = PlateGeometry().estimate_quads(
            _frames(),
            (
                _invalid_scene_detection(1),
                _detection(5),
            ),
        )

        self.assertEqual(
            tuple(estimate.frame_index for estimate in estimates),
            (4, 5),
        )
        self.assertTrue(
            all(
                estimate.source_anchor_indices == (5,)
                for estimate in estimates
            )
        )

    def test_candidates_from_more_than_two_anchor_frames_are_rejected(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            GeometryProcessingError,
            "최대 2개 anchor",
        ):
            PlateGeometry().estimate_quads(
                _frames(),
                (
                    _detection(0),
                    _detection(1),
                    _detection(5),
                ),
            )

    def test_malformed_anchor_quad_is_runtime_contract_error(self) -> None:
        detection = DetectedPlate(
            frame_index=1,
            bbox_xyxy=(5.0, 5.0, 25.0, 15.0),
            quad=((5.0, 5.0),),  # type: ignore[arg-type]
            detector_score=0.9,
        )

        with self.assertRaises(GeometryProcessingError):
            PlateGeometry().estimate_quads(
                _frames(),
                (detection,),
            )

    def test_non_finite_anchor_quad_is_runtime_contract_error(self) -> None:
        with self.assertRaises(GeometryProcessingError):
            PlateGeometry().estimate_quads(
                _frames(),
                (
                    _detection(
                        1,
                        quad=(
                            (5.0, 5.0),
                            (float("nan"), 5.0),
                            (25.0, 15.0),
                            (5.0, 15.0),
                        ),
                    ),
                ),
            )

    def test_bounds_tolerance_clips_small_coordinate_error(self) -> None:
        estimates = PlateGeometry().estimate_quads(
            _frames(),
            (
                _detection(
                    1,
                    quad=(
                        (-1.0, 5.0),
                        (25.0, 5.0),
                        (25.0, 15.0),
                        (-1.0, 15.0),
                    ),
                ),
            ),
        )

        detected = next(
            estimate
            for estimate in estimates
            if estimate.frame_index == 1
        )
        self.assertEqual(detected.quad[0], (0.0, 5.0))
        self.assertEqual(detected.quad[3], (0.0, 15.0))

    def test_wrong_quad_order_is_scene_rejection(self) -> None:
        with self.assertRaises(GeometryError) as raised:
            PlateGeometry().estimate_quads(
                _frames(),
                (
                    _detection(
                        1,
                        quad=(
                            (5.0, 5.0),
                            (25.0, 15.0),
                            (25.0, 5.0),
                            (5.0, 15.0),
                        ),
                    ),
                ),
            )

        self.assertIn("frame_index=1", str(raised.exception))

    def test_too_small_quad_is_scene_rejection(self) -> None:
        with self.assertRaises(GeometryError) as raised:
            PlateGeometry().estimate_quads(
                _frames(),
                (
                    _detection(
                        1,
                        quad=(
                            (5.0, 5.0),
                            (10.0, 5.0),
                            (10.0, 7.0),
                            (5.0, 7.0),
                        ),
                    ),
                ),
            )

        self.assertIn("면적", str(raised.exception))

    def test_opencv_failure_is_runtime_error_and_preserves_cause(
        self,
    ) -> None:
        frame = _frames(1)[0]
        estimate = EstimatedQuad(
            frame_index=0,
            quad=PLATE_QUAD,
            source=QuadSource.DETECTED,
            source_anchor_indices=(0,),
        )
        opencv_error = geometry_module.cv2.error(
            "의도한 perspective transform 실패"
        )

        with patch.object(
            geometry_module.cv2,
            "getPerspectiveTransform",
            side_effect=opencv_error,
        ):
            with self.assertRaises(GeometryProcessingError) as raised:
                PlateGeometry().rectify(frame, estimate)

        self.assertIs(raised.exception.__cause__, opencv_error)


if __name__ == "__main__":
    unittest.main()
