"""가변 frame_count와 Paddle recognition batch 설정의 독립성을 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest
from unittest.mock import patch

import numpy as np

from src.ocr.inference.plate_reader import (
    DEFAULT_RECOGNITION_BATCH_SIZE,
    PaddlePlateReader,
    PaddleResultError,
    _parse_paddle_result,
    load_paddle_plate_reader,
)
from src.ocr.types import (
    EstimatedQuad,
    PreparedPlate,
    Quad,
    QuadSource,
)


PLATE_QUAD: Quad = (
    (0.0, 0.0),
    (11.0, 0.0),
    (11.0, 7.0),
    (0.0, 7.0),
)


class FakePaddleResult:
    def __init__(self, frame_index: int) -> None:
        self.json = {
            "res": {
                "rec_text": f"12가{frame_index:04d}",
                "rec_score": 0.9,
            }
        }


class PayloadPaddleResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self.json = {"res": payload}


class FakePaddleModel:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def predict(
        self,
        *,
        input: list[np.ndarray],
        batch_size: int,
    ) -> list[FakePaddleResult]:
        self.calls.append((len(input), batch_size))
        return [
            FakePaddleResult(index)
            for index in range(len(input))
        ]


class FailingPaddleModel:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def predict(
        self,
        *,
        input: list[np.ndarray],
        batch_size: int,
    ) -> list[FakePaddleResult]:
        raise self.error


class LoaderTextRecognitionModel:
    """Loader의 constructor와 warm-up predict 횟수를 기록하는 fake."""

    instances: list[LoaderTextRecognitionModel] = []

    def __init__(
        self,
        *,
        model_name: str,
        model_dir: str,
        device: str,
    ) -> None:
        self.model_name = model_name
        self.model_dir = model_dir
        self.device = device
        self.calls: list[tuple[int, int]] = []
        self.instances.append(self)

    def predict(
        self,
        *,
        input: list[np.ndarray],
        batch_size: int,
    ) -> list[object]:
        self.calls.append((len(input), batch_size))
        return [object() for _ in input]


def _plates(count: int) -> tuple[PreparedPlate, ...]:
    return tuple(
        PreparedPlate(
            frame_index=index,
            image=np.zeros((8, 12, 3), dtype=np.uint8),
            quad_estimate=EstimatedQuad(
                frame_index=index,
                quad=PLATE_QUAD,
                source=QuadSource.INTERPOLATED,
                source_anchor_indices=(0, count - 1),
            ),
            preprocessing_applied=True,
        )
        for index in range(count)
    )


class PaddlePlateReaderBatchTests(unittest.TestCase):
    def test_eight_inputs_are_passed_with_independent_batch_size(
        self,
    ) -> None:
        model = FakePaddleModel()
        reader = PaddlePlateReader(model, batch_size=6)

        results = reader.recognize(_plates(8))

        self.assertEqual(model.calls, [(8, 6)])
        self.assertEqual(
            tuple(result.frame_index for result in results),
            tuple(range(8)),
        )

    def test_model_failure_is_typed_and_preserves_cause(self) -> None:
        model_error = RuntimeError("의도한 PaddleOCR predict 실패")
        reader = PaddlePlateReader(
            FailingPaddleModel(model_error),
            batch_size=6,
        )

        with self.assertRaises(PaddleResultError) as raised:
            reader.recognize(_plates(1))

        self.assertIs(raised.exception.__cause__, model_error)

    def test_loader_performs_optional_warm_up_exactly_once(self) -> None:
        fake_module = ModuleType("paddleocr")
        fake_module.TextRecognition = (  # type: ignore[attr-defined]
            LoaderTextRecognitionModel
        )

        with TemporaryDirectory() as temporary_directory:
            model_dir = Path(temporary_directory)
            for filename in (
                "inference.json",
                "inference.pdiparams",
                "inference.yml",
            ):
                (model_dir / filename).write_bytes(b"fake model")

            for warm_up, expected_calls in (
                (True, [(1, DEFAULT_RECOGNITION_BATCH_SIZE)]),
                (False, []),
            ):
                with self.subTest(warm_up=warm_up):
                    LoaderTextRecognitionModel.instances.clear()
                    with patch.dict(
                        sys.modules,
                        {"paddleocr": fake_module},
                    ):
                        reader = load_paddle_plate_reader(
                            model_dir,
                            device="cpu",
                            warm_up=warm_up,
                        )

                    self.assertEqual(
                        len(LoaderTextRecognitionModel.instances),
                        1,
                    )
                    model = LoaderTextRecognitionModel.instances[0]
                    self.assertIs(reader._model, model)
                    self.assertEqual(
                        model.model_dir,
                        str(model_dir.resolve()),
                    )
                    self.assertEqual(model.device, "cpu")
                    self.assertEqual(model.calls, expected_calls)

    def test_empty_text_may_omit_score(self) -> None:
        self.assertEqual(
            _parse_paddle_result(
                PayloadPaddleResult({"rec_text": ""})
            ),
            ("", 0.0),
        )

    def test_malformed_result_fields_are_rejected(self) -> None:
        payloads = (
            {},
            {"rec_text": None, "rec_score": 0.9},
            {"rec_text": 123, "rec_score": 0.9},
            {"rec_text": "12가3456"},
            {"rec_text": "12가3456", "rec_score": "0.9"},
            {"rec_text": "12가3456", "rec_score": True},
        )

        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(PaddleResultError):
                    _parse_paddle_result(
                        PayloadPaddleResult(payload)
                    )


if __name__ == "__main__":
    unittest.main()
