"""YOLO adapter가 모델 실행 오류를 typed contract error로 보존하는지 검증한다."""

from __future__ import annotations

import unittest

import numpy as np

from src.ocr.inference.plate_detector import (
    DetectorContractError,
    YoloPlateDetector,
)
from src.ocr.types import CapturedFrame


class FailingYoloModel:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def predict(self, **kwargs: object) -> list[object]:
        raise self.error


class ReturningYoloModel:
    def __init__(self, result: object) -> None:
        self.result = result

    def predict(self, **kwargs: object) -> list[object]:
        return [self.result]


class EmptyBoxes:
    def __len__(self) -> int:
        return 0


class EmptyYoloResult:
    boxes = EmptyBoxes()
    keypoints = None


class YoloPlateDetectorErrorTests(unittest.TestCase):
    @staticmethod
    def _frame() -> CapturedFrame:
        return CapturedFrame(
            frame_index=0,
            image=np.zeros((24, 40, 3), dtype=np.uint8),
        )

    def test_model_failure_is_typed_and_preserves_cause(self) -> None:
        model_error = RuntimeError("의도한 YOLO predict 실패")
        detector = YoloPlateDetector(FailingYoloModel(model_error))

        with self.assertRaises(DetectorContractError) as raised:
            detector.detect(self._frame())

        self.assertIs(raised.exception.__cause__, model_error)

    def test_missing_result_schema_is_not_normal_no_detection(self) -> None:
        detector = YoloPlateDetector(ReturningYoloModel(object()))

        with self.assertRaises(DetectorContractError):
            detector.detect(self._frame())

    def test_empty_boxes_are_normal_no_detection(self) -> None:
        detector = YoloPlateDetector(
            ReturningYoloModel(EmptyYoloResult())
        )

        self.assertIsNone(detector.detect(self._frame()))


if __name__ == "__main__":
    unittest.main()
