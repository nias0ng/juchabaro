"""실제 OpenCV 번호판 전처리의 최소 출력·오류 계약을 검증한다."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from src.ocr.types import RectifiedPlate
from src.ocr.vision import plate_preprocessor as preprocessor_module
from src.ocr.vision.plate_preprocessor import (
    PlatePreprocessError,
    PlatePreprocessor,
)


class PlatePreprocessorTests(unittest.TestCase):
    def test_process_returns_independent_bgr_image_at_fixed_height(
        self,
    ) -> None:
        image = np.arange(
            40 * 100 * 3,
            dtype=np.uint8,
        ).reshape(40, 100, 3)
        original = image.copy()

        prepared = PlatePreprocessor().process(
            RectifiedPlate(
                frame_index=2,
                image=image,
            )
        )

        self.assertEqual(prepared.frame_index, 2)
        self.assertEqual(prepared.image.shape[0], 64)
        self.assertEqual(prepared.image.shape[2], 3)
        self.assertEqual(prepared.image.dtype, np.uint8)
        self.assertFalse(np.shares_memory(prepared.image, image))
        np.testing.assert_array_equal(image, original)

    def test_invalid_images_are_rejected(self) -> None:
        invalid_images = (
            np.zeros((0, 10, 3), dtype=np.uint8),
            np.zeros((10, 10, 3), dtype=np.float32),
            np.zeros((10, 10), dtype=np.uint8),
        )

        for image in invalid_images:
            with self.subTest(shape=image.shape, dtype=image.dtype):
                with self.assertRaises(PlatePreprocessError):
                    PlatePreprocessor().process(
                        RectifiedPlate(
                            frame_index=0,
                            image=image,
                        )
                    )

    def test_opencv_failure_preserves_cause(self) -> None:
        opencv_error = preprocessor_module.cv2.error(
            "의도한 전처리 실패"
        )
        image = np.zeros((10, 20, 3), dtype=np.uint8)

        with patch.object(
            preprocessor_module.cv2,
            "cvtColor",
            side_effect=opencv_error,
        ):
            with self.assertRaises(PlatePreprocessError) as raised:
                PlatePreprocessor().process(
                    RectifiedPlate(
                        frame_index=3,
                        image=image,
                    )
                )

        self.assertIs(raised.exception.__cause__, opencv_error)


if __name__ == "__main__":
    unittest.main()
