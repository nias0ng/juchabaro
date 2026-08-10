"""실제 모델 없이 OCR pipeline의 공개 결과와 주요 흐름을 검증한다."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import fields, replace
import unittest

import numpy as np

from src.ocr import (
    InvalidBurstError,
    OcrPipelineError,
    OcrRuntimeError,
)
from src.ocr.errors import OcrComponentError
from src.ocr.pipeline import OcrPipelinePolicy, PlateOcrPipeline
from src.ocr.postprocessing.aggregator import PlateAggregator
from src.ocr.postprocessing.plate_text import build_ocr_candidate
from src.ocr.types import (
    AnchorSelection,
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    OcrCandidate,
    PlateReadResult,
    PreparedPlate,
    Quad,
    QuadSource,
    RawOcrResult,
    ReadStatus,
    RectifiedPlate,
)
from src.ocr.vision.geometry import GeometryError, PlateGeometry


PLATE_NUMBER = "12가3456"
OTHER_PLATE_NUMBER = "34나5678"
PLATE_QUAD: Quad = (
    (5.0, 5.0),
    (25.0, 5.0),
    (25.0, 15.0),
    (5.0, 15.0),
)
INVALID_PLATE_QUAD: Quad = (
    (5.0, 5.0),
    (5.0, 5.0),
    (5.0, 5.0),
    (5.0, 5.0),
)


def _frames(count: int = 6) -> tuple[CapturedFrame, ...]:
    return tuple(
        CapturedFrame(
            frame_index=index,
            image=np.full((24, 40, 3), index, dtype=np.uint8),
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


class FakeSelector:
    def __init__(
        self,
        error: BaseException | None = None,
        *,
        earlier_frame_index: object = 1,
        later_frame_index: object | None = None,
    ) -> None:
        self.error = error
        self.earlier_frame_index = earlier_frame_index
        self.later_frame_index = later_frame_index
        self.calls = 0

    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        self.calls += 1
        if self.error is not None:
            raise self.error

        return AnchorSelection(
            earlier_frame_index=self.earlier_frame_index,
            later_frame_index=(
                frames[-1].frame_index
                if self.later_frame_index is None
                else self.later_frame_index
            ),
        )


class FakeDetector:
    def __init__(
        self,
        responses: dict[
            int,
            tuple[DetectedPlate, ...] | BaseException,
        ]
        | None = None,
    ) -> None:
        self.responses = responses
        self.calls: list[int] = []

    def detect(
        self,
        frame: CapturedFrame,
    ) -> tuple[DetectedPlate, ...]:
        self.calls.append(frame.frame_index)
        if self.responses is None:
            return (_detection(frame.frame_index),)

        response = self.responses.get(frame.frame_index, ())
        if isinstance(response, BaseException):
            raise response
        return response


class FakeGeometry:
    def __init__(
        self,
        *,
        estimated_indices: Sequence[int] | None = None,
        estimate_error: BaseException | None = None,
        rectify_errors: dict[int, BaseException] | None = None,
    ) -> None:
        self.estimated_indices = (
            tuple(estimated_indices)
            if estimated_indices is not None
            else None
        )
        self.estimate_error = estimate_error
        self.rectify_errors = rectify_errors or {}
        self.estimate_calls: list[tuple[int, ...]] = []
        self.estimate_inputs: list[tuple[DetectedPlate, ...]] = []
        self.rectify_calls: list[int] = []

    def estimate_quads(
        self,
        frames: Sequence[CapturedFrame],
        detections: Sequence[DetectedPlate],
    ) -> tuple[EstimatedQuad, ...]:
        candidate_tuple = tuple(detections)
        self.estimate_inputs.append(candidate_tuple)
        candidate_indices = tuple(
            detection.frame_index
            for detection in candidate_tuple
        )
        self.estimate_calls.append(candidate_indices)
        anchor_indices = tuple(dict.fromkeys(candidate_indices))

        if self.estimate_error is not None:
            raise self.estimate_error

        indices = (
            self.estimated_indices
            if self.estimated_indices is not None
            else tuple(frame.frame_index for frame in frames)
        )
        return tuple(
            EstimatedQuad(
                frame_index=index,
                quad=PLATE_QUAD,
                source=(
                    QuadSource.DETECTED
                    if index in anchor_indices
                    else (
                        QuadSource.REUSED
                        if len(anchor_indices) == 1
                        else QuadSource.INTERPOLATED
                    )
                ),
                source_anchor_indices=anchor_indices,
            )
            for index in indices
        )

    def rectify(
        self,
        frame: CapturedFrame,
        _estimate: EstimatedQuad,
    ) -> RectifiedPlate:
        self.rectify_calls.append(frame.frame_index)
        error = self.rectify_errors.get(frame.frame_index)
        if error is not None:
            raise error
        return RectifiedPlate(
            frame_index=frame.frame_index,
            image=frame.image,
        )


class FakePreprocessor:
    def process(
        self,
        plate: RectifiedPlate,
    ) -> PreparedPlate:
        return PreparedPlate(
            frame_index=plate.frame_index,
            image=plate.image,
        )


class FakeReader:
    def __init__(
        self,
        *,
        texts: dict[int, str] | None = None,
        scores: dict[int, float] | None = None,
        error: BaseException | None = None,
        result_indices: Sequence[int] | None = None,
    ) -> None:
        self.texts = texts or {}
        self.scores = scores or {}
        self.error = error
        self.result_indices = (
            tuple(result_indices)
            if result_indices is not None
            else None
        )
        self.calls: list[tuple[int, ...]] = []

    def recognize(
        self,
        plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        input_indices = tuple(plate.frame_index for plate in plates)
        self.calls.append(input_indices)
        if self.error is not None:
            raise self.error

        result_indices = self.result_indices or input_indices
        return tuple(
            RawOcrResult(
                frame_index=frame_index,
                raw_text=self.texts.get(frame_index, PLATE_NUMBER),
                rec_score=self.scores.get(frame_index, 0.9),
            )
            for frame_index in result_indices
        )


class UnexpectedProgrammerError(RuntimeError):
    """Known component 오류로 분류되지 않은 테스트용 예외."""


def _pipeline(
    *,
    selector: FakeSelector | None = None,
    detector: FakeDetector | None = None,
    geometry: FakeGeometry | PlateGeometry | None = None,
    reader: FakeReader | None = None,
    text_processor: Callable[
        [RawOcrResult],
        OcrCandidate,
    ] = build_ocr_candidate,
    policy: OcrPipelinePolicy | None = None,
) -> tuple[
    PlateOcrPipeline,
    FakeSelector,
    FakeDetector,
    FakeGeometry | PlateGeometry,
    FakeReader,
]:
    selected_selector = selector or FakeSelector()
    selected_detector = detector or FakeDetector()
    selected_geometry = geometry or FakeGeometry()
    selected_reader = reader or FakeReader()

    return (
        PlateOcrPipeline(
            selector=selected_selector,
            detector=selected_detector,
            geometry=selected_geometry,
            preprocessor=FakePreprocessor(),
            reader=selected_reader,
            aggregator=PlateAggregator(),
            text_processor=text_processor,
            policy=policy,
        ),
        selected_selector,
        selected_detector,
        selected_geometry,
        selected_reader,
    )


class PlateOcrPipelineTests(unittest.TestCase):
    def test_public_result_and_error_contract(self) -> None:
        self.assertEqual(
            tuple(ReadStatus),
            (
                ReadStatus.SUCCESS,
                ReadStatus.NO_PLATE_REGION,
                ReadStatus.OCR_EMPTY,
                ReadStatus.INVALID_FORMAT,
                ReadStatus.LOW_SCORE,
                ReadStatus.AMBIGUOUS,
            ),
        )
        self.assertEqual(
            tuple(field.name for field in fields(PlateReadResult)),
            ("status", "plate_number", "rec_score"),
        )
        self.assertTrue(issubclass(InvalidBurstError, OcrPipelineError))
        self.assertTrue(issubclass(OcrRuntimeError, OcrPipelineError))
        self.assertTrue(issubclass(OcrComponentError, OcrRuntimeError))

    def test_six_frame_success_runs_pipeline_in_order(self) -> None:
        pipeline, selector, detector, geometry, reader = _pipeline()

        result = pipeline.read_plate(_frames())

        self.assertEqual(
            result,
            PlateReadResult(
                status=ReadStatus.SUCCESS,
                plate_number=PLATE_NUMBER,
                rec_score=0.9,
            ),
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(selector.calls, 1)
        self.assertEqual(detector.calls, [1, 5])
        self.assertEqual(geometry.estimate_calls, [(1, 5)])
        self.assertEqual(reader.calls, [(0, 1, 2, 3, 4, 5)])

    def test_detector_candidates_keep_anchor_and_batch_order(self) -> None:
        earlier = (
            _detection(1, score=0.95),
            _detection(1, score=0.80),
        )
        later = (
            _detection(5, score=0.90),
            _detection(5, score=0.70),
        )
        geometry = FakeGeometry()
        pipeline, _, detector, _, _ = _pipeline(
            detector=FakeDetector({1: earlier, 5: later}),
            geometry=geometry,
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [1, 5])
        self.assertEqual(
            geometry.estimate_inputs,
            [(*earlier, *later)],
        )

    def test_pipeline_supports_configured_frame_counts(self) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                pipeline, _, detector, geometry, reader = _pipeline(
                    policy=OcrPipelinePolicy(frame_count=frame_count),
                )

                result = pipeline.read_plate(_frames(frame_count))

                self.assertEqual(result.status, ReadStatus.SUCCESS)
                self.assertEqual(
                    detector.calls,
                    [1, frame_count - 1],
                )
                self.assertEqual(
                    geometry.estimate_calls,
                    [(1, frame_count - 1)],
                )
                self.assertEqual(
                    reader.calls,
                    [tuple(range(frame_count))],
                )

    def test_custom_early_anchor_candidate_count(self) -> None:
        pipeline, _, detector, geometry, _ = _pipeline(
            selector=FakeSelector(earlier_frame_index=2),
            policy=OcrPipelinePolicy(
                frame_count=6,
                early_anchor_candidate_count=3,
            ),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [2, 5])
        self.assertEqual(geometry.estimate_calls, [(2, 5)])

    def test_non_integer_selector_indices_are_rejected(self) -> None:
        cases = (
            ("earlier_bool", FakeSelector(earlier_frame_index=True)),
            ("earlier_float", FakeSelector(earlier_frame_index=1.0)),
            ("later_bool", FakeSelector(later_frame_index=True)),
            ("later_float", FakeSelector(later_frame_index=5.0)),
        )

        for name, selector in cases:
            with self.subTest(name=name):
                pipeline, _, detector, _, _ = _pipeline(
                    selector=selector,
                )

                with self.assertRaises(OcrRuntimeError):
                    pipeline.read_plate(_frames())

                self.assertEqual(detector.calls, [])

    def test_non_integer_geometry_indices_are_rejected(self) -> None:
        for frame_index in (True, 1.0):
            with self.subTest(frame_index=frame_index):
                pipeline, *_ = _pipeline(
                    geometry=FakeGeometry(
                        estimated_indices=(frame_index,)
                    )
                )

                with self.assertRaises(OcrRuntimeError):
                    pipeline.read_plate(_frames())

    def test_policy_mismatch_fails_before_components(self) -> None:
        pipeline, selector, detector, geometry, reader = _pipeline(
            policy=OcrPipelinePolicy(frame_count=3),
        )

        with self.assertRaises(InvalidBurstError):
            pipeline.read_plate(_frames(6))

        self.assertEqual(selector.calls, 0)
        self.assertEqual(detector.calls, [])
        self.assertEqual(geometry.estimate_calls, [])
        self.assertEqual(reader.calls, [])

    def test_malformed_burst_raises_invalid_burst(self) -> None:
        valid = list(_frames())
        wrong_indices = valid.copy()
        wrong_indices[2] = CapturedFrame(
            frame_index=3,
            image=wrong_indices[2].image,
        )
        wrong_dtype = valid.copy()
        wrong_dtype[0] = CapturedFrame(
            frame_index=0,
            image=np.zeros((24, 40, 3), dtype=np.float32),
        )
        wrong_channels = valid.copy()
        wrong_channels[0] = CapturedFrame(
            frame_index=0,
            image=np.zeros((24, 40), dtype=np.uint8),
        )
        mixed_resolution = valid.copy()
        mixed_resolution[-1] = CapturedFrame(
            frame_index=5,
            image=np.zeros((25, 40, 3), dtype=np.uint8),
        )

        cases: tuple[tuple[str, object], ...] = (
            ("not_iterable", None),
            ("wrong_type", (object(), *valid[1:])),
            ("wrong_indices", tuple(wrong_indices)),
            ("wrong_dtype", tuple(wrong_dtype)),
            ("wrong_channels", tuple(wrong_channels)),
            ("mixed_resolution", tuple(mixed_resolution)),
        )
        for name, frames in cases:
            with self.subTest(name=name):
                pipeline, *_ = _pipeline()
                with self.assertRaises(InvalidBurstError):
                    pipeline.read_plate(frames)  # type: ignore[arg-type]

    def test_reader_result_order_mismatch_is_rejected(self) -> None:
        pipeline, *_ = _pipeline(
            reader=FakeReader(
                result_indices=(5, 4, 3, 2, 1, 0)
            )
        )

        with self.assertRaises(OcrRuntimeError):
            pipeline.read_plate(_frames())

    def test_text_processor_frame_index_mismatch_is_rejected(self) -> None:
        pipeline, *_ = _pipeline(
            text_processor=lambda result: replace(
                build_ocr_candidate(result),
                frame_index=result.frame_index + 100,
            )
        )

        with self.assertRaises(OcrRuntimeError):
            pipeline.read_plate(_frames())

    def test_known_component_error_keeps_identity_at_runtime_boundary(
        self,
    ) -> None:
        component_error = OcrComponentError("known failure")
        pipeline, *_ = _pipeline(
            selector=FakeSelector(component_error)
        )

        with self.assertRaises(OcrRuntimeError) as caught:
            pipeline.read_plate(_frames())

        self.assertIs(caught.exception, component_error)

    def test_unknown_error_propagates_as_same_object(self) -> None:
        programmer_error = UnexpectedProgrammerError("unexpected failure")
        pipeline, *_ = _pipeline(
            selector=FakeSelector(programmer_error)
        )

        with self.assertRaises(UnexpectedProgrammerError) as caught:
            pipeline.read_plate(_frames())

        self.assertIs(caught.exception, programmer_error)

    def test_pipeline_continues_with_one_detected_anchor(self) -> None:
        cases = (
            ({1: (_detection(1),), 5: ()}, (1,), [1, 5]),
            ({1: (), 5: (_detection(5),)}, (5,), [1, 0, 5]),
        )
        for responses, expected_indices, expected_calls in cases:
            with self.subTest(detected_indices=expected_indices):
                geometry = FakeGeometry()
                pipeline, _, detector, _, _ = _pipeline(
                    detector=FakeDetector(responses),
                    geometry=geometry,
                )

                result = pipeline.read_plate(_frames())

                self.assertEqual(result.status, ReadStatus.SUCCESS)
                self.assertEqual(detector.calls, expected_calls)
                self.assertEqual(
                    geometry.estimate_calls,
                    [expected_indices],
                )

    def test_failed_earlier_frame_one_falls_back_to_zero(self) -> None:
        geometry = FakeGeometry()
        pipeline, _, detector, _, _ = _pipeline(
            detector=FakeDetector(
                {
                    1: (),
                    0: (_detection(0),),
                    5: (),
                }
            ),
            geometry=geometry,
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [1, 0, 5])
        self.assertEqual(geometry.estimate_calls, [(0,)])

    def test_geometry_can_omit_one_frame(self) -> None:
        pipeline, _, _, _, reader = _pipeline(
            geometry=FakeGeometry(
                estimated_indices=(0, 1, 3, 4, 5)
            ),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(reader.calls, [(0, 1, 3, 4, 5)])

    def test_scene_geometry_failure_excludes_only_that_frame(self) -> None:
        pipeline, _, _, _, reader = _pipeline(
            geometry=FakeGeometry(
                rectify_errors={
                    2: GeometryError("사용할 수 없는 장면 좌표")
                }
            ),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(reader.calls, [(0, 1, 3, 4, 5)])

    def test_all_invalid_anchor_quads_return_no_plate_region(self) -> None:
        pipeline, *_ = _pipeline(
            detector=FakeDetector(
                {
                    1: (_detection(1, quad=INVALID_PLATE_QUAD),),
                    5: (_detection(5, quad=INVALID_PLATE_QUAD),),
                }
            ),
            geometry=PlateGeometry(),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.NO_PLATE_REGION)
        self.assertIsNone(result.plate_number)

    def test_invalid_top_candidate_does_not_hide_valid_candidate(
        self,
    ) -> None:
        pipeline, _, detector, _, reader = _pipeline(
            detector=FakeDetector(
                {
                    1: (
                        _detection(
                            1,
                            quad=INVALID_PLATE_QUAD,
                            score=0.95,
                        ),
                        _detection(1, score=0.90),
                    ),
                    5: (),
                }
            ),
            geometry=PlateGeometry(),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(result.plate_number, PLATE_NUMBER)
        self.assertEqual(detector.calls, [1, 5])
        self.assertEqual(reader.calls, [(0, 1, 2)])

    def test_no_detection_returns_no_plate_region(self) -> None:
        geometry = FakeGeometry()
        pipeline, _, detector, _, _ = _pipeline(
            detector=FakeDetector({1: (), 5: ()}),
            geometry=geometry,
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.NO_PLATE_REGION)
        self.assertIsNone(result.plate_number)
        self.assertFalse(result.succeeded)
        self.assertEqual(detector.calls, [1, 0, 5])
        self.assertEqual(geometry.estimate_calls, [])

    def test_later_single_anchor_succeeds_with_matching_frames(
        self,
    ) -> None:
        pipeline, _, _, _, reader = _pipeline(
            detector=FakeDetector(
                {1: (), 5: (_detection(5),)}
            ),
            geometry=PlateGeometry(),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(result.plate_number, PLATE_NUMBER)
        self.assertEqual(reader.calls, [(4, 5)])

    def test_later_single_anchor_is_ambiguous_on_disagreement(
        self,
    ) -> None:
        pipeline, *_ = _pipeline(
            detector=FakeDetector(
                {1: (), 5: (_detection(5),)}
            ),
            geometry=PlateGeometry(),
            reader=FakeReader(
                texts={
                    4: PLATE_NUMBER,
                    5: OTHER_PLATE_NUMBER,
                }
            ),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.AMBIGUOUS)
        self.assertIsNone(result.plate_number)

    def test_known_read_failures_remain_normal_results(self) -> None:
        cases = (
            (
                FakeReader(
                    texts={index: "..." for index in range(6)}
                ),
                ReadStatus.OCR_EMPTY,
            ),
            (
                FakeReader(
                    texts={index: "1234" for index in range(6)}
                ),
                ReadStatus.INVALID_FORMAT,
            ),
            (
                FakeReader(
                    scores={index: 0.39 for index in range(6)}
                ),
                ReadStatus.LOW_SCORE,
            ),
            (
                FakeReader(
                    texts={
                        **{
                            index: PLATE_NUMBER
                            for index in range(3)
                        },
                        **{
                            index: OTHER_PLATE_NUMBER
                            for index in range(3, 6)
                        },
                    }
                ),
                ReadStatus.AMBIGUOUS,
            ),
        )
        for reader, expected_status in cases:
            with self.subTest(status=expected_status):
                pipeline, *_ = _pipeline(reader=reader)

                result = pipeline.read_plate(_frames())

                self.assertEqual(
                    result,
                    PlateReadResult(
                        status=expected_status,
                        plate_number=None,
                        rec_score=None,
                    ),
                )

    def test_pipeline_does_not_mutate_input_images(self) -> None:
        frames = _frames()
        originals = tuple(frame.image.copy() for frame in frames)
        pipeline, *_ = _pipeline()

        result = pipeline.read_plate(frames)

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        for frame, original in zip(frames, originals, strict=True):
            np.testing.assert_array_equal(frame.image, original)


if __name__ == "__main__":
    unittest.main()
