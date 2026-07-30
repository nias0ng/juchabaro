"""가변 frame_count와 Paddle recognition batch 설정의 독립성을 검증한다."""

from __future__ import annotations

import unittest

import numpy as np

from src.ocr.inference.plate_reader import PaddlePlateReader
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


if __name__ == "__main__":
    unittest.main()
