"""가변 frame_count와 Paddle recognition batch 설정의 독립성을 검증한다."""

from __future__ import annotations

import unittest

import numpy as np

from src.ocr.inference.plate_reader import (
    PaddlePlateReader,
    PaddleResultError,
    _parse_paddle_result,
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
