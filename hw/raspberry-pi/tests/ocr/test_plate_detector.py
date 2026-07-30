"""YOLO adapter의 출력 계약과 대표 후보 선택 규칙을 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import patch

import numpy as np

from src.ocr.inference.plate_detector import (
    DetectorContractError,
    YoloPlateDetector,
    load_yolo_plate_detector,
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


class ArrayBoxes:
    def __init__(
        self,
        xyxy: object,
        confidence: object,
    ) -> None:
        self.xyxy = np.asarray(xyxy)
        self.conf = np.asarray(confidence)

    def __len__(self) -> int:
        return len(self.xyxy)


class ArrayKeypoints:
    def __init__(self, xy: object) -> None:
        self.xy = np.asarray(xy)


class ArrayYoloResult:
    def __init__(
        self,
        *,
        boxes: object,
        confidence: object,
        keypoints: object,
    ) -> None:
        self.boxes = ArrayBoxes(boxes, confidence)
        self.keypoints = ArrayKeypoints(keypoints)


class LoaderYoloModel:
    """Loader의 constructor와 warm-up predict 횟수를 기록하는 fake."""

    instances: list[LoaderYoloModel] = []

    def __init__(
        self,
        model_path: str,
        *,
        task: str | None = None,
    ) -> None:
        self.model_path = model_path
        self.task = task
        self.predict_calls: list[dict[str, object]] = []
        self.instances.append(self)

    def predict(self, **kwargs: object) -> list[object]:
        self.predict_calls.append(kwargs)
        return [object()]


class YoloPlateDetectorTests(unittest.TestCase):
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

    def test_highest_confidence_candidate_keeps_keypoint_order(
        self,
    ) -> None:
        result = ArrayYoloResult(
            boxes=(
                (0.0, 0.0, 30.0, 20.0),
                (10.0, 10.0, 20.0, 15.0),
            ),
            confidence=(0.80, 0.90),
            keypoints=(
                (
                    (1.0, 2.0),
                    (3.0, 4.0),
                    (5.0, 6.0),
                    (7.0, 8.0),
                ),
                (
                    (11.0, 12.0),
                    (13.0, 14.0),
                    (15.0, 16.0),
                    (17.0, 18.0),
                ),
            ),
        )
        detector = YoloPlateDetector(ReturningYoloModel(result))

        selected = detector.detect(self._frame())

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(
            selected.bbox_xyxy,
            (10.0, 10.0, 20.0, 15.0),
        )
        self.assertEqual(
            selected.quad,
            (
                (11.0, 12.0),
                (13.0, 14.0),
                (15.0, 16.0),
                (17.0, 18.0),
            ),
        )
        self.assertEqual(selected.detector_score, 0.90)

    def test_equal_confidence_selects_larger_bbox_area(self) -> None:
        result = ArrayYoloResult(
            boxes=(
                (0.0, 0.0, 10.0, 10.0),
                (0.0, 0.0, 20.0, 10.0),
            ),
            confidence=(0.85, 0.85),
            keypoints=(
                (
                    (0.0, 0.0),
                    (10.0, 0.0),
                    (10.0, 10.0),
                    (0.0, 10.0),
                ),
                (
                    (0.0, 0.0),
                    (20.0, 0.0),
                    (20.0, 10.0),
                    (0.0, 10.0),
                ),
            ),
        )
        detector = YoloPlateDetector(ReturningYoloModel(result))

        selected = detector.detect(self._frame())

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(
            selected.bbox_xyxy,
            (0.0, 0.0, 20.0, 10.0),
        )

    def test_nan_and_invalid_keypoint_shape_are_contract_errors(
        self,
    ) -> None:
        cases = (
            (
                "nan",
                ArrayYoloResult(
                    boxes=((0.0, 0.0, 10.0, 10.0),),
                    confidence=(np.nan,),
                    keypoints=(
                        (
                            (0.0, 0.0),
                            (10.0, 0.0),
                            (10.0, 10.0),
                            (0.0, 10.0),
                        ),
                    ),
                ),
                "NaN",
            ),
            (
                "keypoint shape",
                ArrayYoloResult(
                    boxes=((0.0, 0.0, 10.0, 10.0),),
                    confidence=(0.90,),
                    keypoints=(
                        (
                            (0.0, 0.0),
                            (10.0, 0.0),
                            (10.0, 10.0),
                        ),
                    ),
                ),
                "네 점",
            ),
        )

        for name, result, message in cases:
            with self.subTest(name=name):
                detector = YoloPlateDetector(
                    ReturningYoloModel(result)
                )

                with self.assertRaisesRegex(
                    DetectorContractError,
                    message,
                ):
                    detector.detect(self._frame())

    def test_loader_performs_optional_warm_up_exactly_once(self) -> None:
        fake_module = ModuleType("ultralytics")
        fake_module.YOLO = LoaderYoloModel  # type: ignore[attr-defined]

        with TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "best.pt"
            model_path.write_bytes(b"fake model")

            for warm_up, expected_predict_calls in (
                (True, 1),
                (False, 0),
            ):
                with self.subTest(warm_up=warm_up):
                    LoaderYoloModel.instances.clear()
                    with patch.dict(
                        sys.modules,
                        {"ultralytics": fake_module},
                    ):
                        detector = load_yolo_plate_detector(
                            model_path,
                            device="cpu",
                            warm_up=warm_up,
                        )

                    self.assertEqual(len(LoaderYoloModel.instances), 1)
                    model = LoaderYoloModel.instances[0]
                    self.assertIs(detector._model, model)
                    self.assertEqual(
                        model.model_path,
                        str(model_path.resolve()),
                    )
                    self.assertEqual(model.task, "pose")
                    self.assertEqual(
                        len(model.predict_calls),
                        expected_predict_calls,
                    )


if __name__ == "__main__":
    unittest.main()
