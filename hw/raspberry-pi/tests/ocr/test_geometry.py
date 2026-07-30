"""현재 두 anchor 보간과 single-anchor 재사용 범위를 고정한다."""

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


def _frames(count: int = 6) -> tuple[CapturedFrame, ...]:
    return tuple(
        CapturedFrame(
            frame_index=index,
            image=np.zeros((24, 40, 3), dtype=np.uint8),
        )
        for index in range(count)
    )


def _detection(frame_index: int) -> DetectedPlate:
    return DetectedPlate(
        frame_index=frame_index,
        bbox_xyxy=(5.0, 5.0, 25.0, 15.0),
        quad=PLATE_QUAD,
        detector_score=0.9,
    )


def _invalid_scene_detection(frame_index: int) -> DetectedPlate:
    return DetectedPlate(
        frame_index=frame_index,
        bbox_xyxy=(-10.0, -10.0, -1.0, -1.0),
        quad=(
            (-10.0, -10.0),
            (-1.0, -10.0),
            (-1.0, -1.0),
            (-10.0, -1.0),
        ),
        detector_score=0.9,
    )


class PlateGeometryCharacterizationTests(unittest.TestCase):
    """프레임 정책 변경 전 geometry의 실제 출력 범위를 기록한다."""

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
                (_invalid_scene_detection(1),),
            )

        self.assertIn("frame_index=1", str(raised.exception))
        self.assertIn("경계를 벗어납니다", str(raised.exception))

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
