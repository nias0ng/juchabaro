"""실제 모델 없이 현재 OCR pipeline orchestration 동작을 고정한다."""

from __future__ import annotations

from collections.abc import Sequence
import logging
import unittest

import numpy as np

from src.ocr.pipeline import OcrPipelinePolicy, PlateOcrPipeline
from src.ocr.postprocessing.aggregator import PlateAggregator
from src.ocr.types import (
    AnchorSelection,
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    FrameQuality,
    OcrCandidate,
    PreparedPlate,
    Quad,
    QuadSource,
    RawOcrResult,
    ReadStatus,
    RectifiedPlate,
)
from src.ocr.vision.geometry import PlateGeometry


PLATE_NUMBER = "12가3456"
OTHER_PLATE_NUMBER = "34나5678"
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
            image=np.full((24, 40, 3), index, dtype=np.uint8),
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


class FakeSelector:
    def __init__(
        self,
        error: BaseException | None = None,
        *,
        earlier_frame_index: int = 1,
        later_frame_index: int | None = None,
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

        qualities = tuple(
            FrameQuality(
                frame_index=frame.frame_index,
                sharpness=1.0,
                contrast=1.0,
                mean_brightness=127.0,
                dark_ratio=0.0,
                bright_ratio=0.0,
                score=1.0,
            )
            for frame in frames
        )
        return AnchorSelection(
            earlier_frame_index=self.earlier_frame_index,
            later_frame_index=(
                self.later_frame_index
                if self.later_frame_index is not None
                else frames[-1].frame_index
            ),
            qualities=qualities,
        )


class FakeDetector:
    def __init__(
        self,
        responses: dict[
            int,
            DetectedPlate | None | BaseException,
        ]
        | None = None,
    ) -> None:
        self.responses = responses
        self.calls: list[int] = []

    def detect(
        self,
        frame: CapturedFrame,
    ) -> DetectedPlate | None:
        self.calls.append(frame.frame_index)
        if self.responses is None:
            return _detection(frame.frame_index)

        response = self.responses.get(frame.frame_index)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeGeometry:
    def __init__(
        self,
        *,
        estimated_indices: Sequence[int] | None = None,
        rectify_failures: set[int] | None = None,
    ) -> None:
        self.estimated_indices = (
            tuple(estimated_indices)
            if estimated_indices is not None
            else None
        )
        self.rectify_failures = rectify_failures or set()
        self.estimate_calls: list[tuple[int, ...]] = []
        self.rectify_calls: list[int] = []

    def estimate_quads(
        self,
        frames: Sequence[CapturedFrame],
        detections: Sequence[DetectedPlate],
    ) -> tuple[EstimatedQuad, ...]:
        anchor_indices = tuple(
            detection.frame_index
            for detection in detections
        )
        self.estimate_calls.append(anchor_indices)
        indices = (
            self.estimated_indices
            if self.estimated_indices is not None
            else tuple(frame.frame_index for frame in frames)
        )

        estimates: list[EstimatedQuad] = []
        for index in indices:
            if index in anchor_indices:
                source = QuadSource.DETECTED
            elif len(anchor_indices) == 1:
                source = QuadSource.REUSED
            else:
                source = QuadSource.INTERPOLATED

            estimates.append(
                EstimatedQuad(
                    frame_index=index,
                    quad=PLATE_QUAD,
                    source=source,
                    source_anchor_indices=anchor_indices,
                )
            )
        return tuple(estimates)

    def rectify(
        self,
        frame: CapturedFrame,
        estimate: EstimatedQuad,
    ) -> RectifiedPlate:
        self.rectify_calls.append(frame.frame_index)
        if frame.frame_index in self.rectify_failures:
            raise ValueError("의도한 원근 보정 실패")
        return RectifiedPlate(
            frame_index=frame.frame_index,
            image=frame.image,
            quad_estimate=estimate,
        )


class FakePreprocessor:
    def __init__(
        self,
        failures: set[int] | None = None,
    ) -> None:
        self.failures = failures or set()
        self.calls: list[int] = []

    def process(
        self,
        plate: RectifiedPlate,
    ) -> PreparedPlate:
        self.calls.append(plate.frame_index)
        if plate.frame_index in self.failures:
            raise ValueError("의도한 전처리 실패")
        return PreparedPlate(
            frame_index=plate.frame_index,
            image=plate.image,
            quad_estimate=plate.quad_estimate,
            preprocessing_applied=True,
        )


class FakeReader:
    def __init__(
        self,
        *,
        texts: dict[int, str] | None = None,
        scores: dict[int, float] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.texts = texts or {}
        self.scores = scores or {}
        self.error = error
        self.calls: list[tuple[int, ...]] = []

    def recognize(
        self,
        plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        self.calls.append(
            tuple(plate.frame_index for plate in plates)
        )
        if self.error is not None:
            raise self.error

        return tuple(
            RawOcrResult(
                frame_index=plate.frame_index,
                raw_text=self.texts.get(
                    plate.frame_index,
                    PLATE_NUMBER,
                ),
                rec_score=self.scores.get(
                    plate.frame_index,
                    0.9,
                ),
            )
            for plate in plates
        )


class RaisingAggregator:
    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> object:
        raise RuntimeError("의도한 예상 밖 집계 오류")


def _pipeline(
    *,
    selector: FakeSelector | None = None,
    detector: FakeDetector | None = None,
    geometry: FakeGeometry | PlateGeometry | None = None,
    preprocessor: FakePreprocessor | None = None,
    reader: FakeReader | None = None,
    aggregator: object | None = None,
    policy: OcrPipelinePolicy | None = None,
) -> tuple[
    PlateOcrPipeline,
    FakeSelector,
    FakeDetector,
    FakeGeometry | PlateGeometry,
    FakePreprocessor,
    FakeReader,
]:
    selected_selector = selector or FakeSelector()
    selected_detector = detector or FakeDetector()
    selected_geometry = geometry or FakeGeometry()
    selected_preprocessor = preprocessor or FakePreprocessor()
    selected_reader = reader or FakeReader()
    selected_aggregator = (
        aggregator
        if aggregator is not None
        else PlateAggregator()
    )

    pipeline = PlateOcrPipeline(
        selector=selected_selector,
        detector=selected_detector,
        geometry=selected_geometry,
        preprocessor=selected_preprocessor,
        reader=selected_reader,
        aggregator=selected_aggregator,
        policy=policy,
    )
    return (
        pipeline,
        selected_selector,
        selected_detector,
        selected_geometry,
        selected_preprocessor,
        selected_reader,
    )


class PlateOcrPipelineCharacterizationTests(unittest.TestCase):
    """리팩터링 전에 현재 pipeline의 외부 관찰 동작을 고정한다."""

    def setUp(self) -> None:
        self._previous_logging_disable_level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)

    def tearDown(self) -> None:
        logging.disable(self._previous_logging_disable_level)

    def test_six_frame_success_calls_detector_for_two_anchors(self) -> None:
        pipeline, selector, detector, geometry, _, reader = _pipeline()

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(result.plate_number, PLATE_NUMBER)
        self.assertTrue(result.succeeded)
        self.assertEqual(selector.calls, 1)
        self.assertEqual(detector.calls, [1, 5])
        self.assertEqual(geometry.estimate_calls, [(1, 5)])
        self.assertEqual(reader.calls, [(0, 1, 2, 3, 4, 5)])
        self.assertEqual(result.metrics.detector_calls, 2)
        self.assertEqual(result.metrics.recognizer_calls, 1)

    def test_pipeline_supports_configured_three_six_and_eight_frames(
        self,
    ) -> None:
        for frame_count in (3, 6, 8):
            with self.subTest(frame_count=frame_count):
                policy = OcrPipelinePolicy(frame_count=frame_count)
                pipeline, _, detector, geometry, _, reader = _pipeline(
                    policy=policy,
                )

                result = pipeline.read_plate(_frames(frame_count))

                self.assertEqual(result.status, ReadStatus.SUCCESS)
                self.assertEqual(result.total_frames, frame_count)
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
                self.assertEqual(result.metrics.detector_calls, 2)

    def test_pipeline_uses_custom_early_anchor_candidate_count(
        self,
    ) -> None:
        policy = OcrPipelinePolicy(
            frame_count=6,
            early_anchor_candidate_count=3,
        )
        pipeline, _, detector, geometry, _, _ = _pipeline(
            selector=FakeSelector(earlier_frame_index=2),
            policy=policy,
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [2, 5])
        self.assertEqual(geometry.estimate_calls, [(2, 5)])

    def test_pipeline_rejects_anchor_outside_custom_early_pool(
        self,
    ) -> None:
        selector = FakeSelector(earlier_frame_index=1)
        pipeline, _, detector, geometry, _, reader = _pipeline(
            selector=selector,
            policy=OcrPipelinePolicy(
                frame_count=6,
                early_anchor_candidate_count=1,
            ),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.INVALID_INPUT)
        self.assertEqual(selector.calls, 1)
        self.assertEqual(detector.calls, [])
        self.assertEqual(geometry.estimate_calls, [])
        self.assertEqual(reader.calls, [])

    def test_policy_mismatch_is_rejected_before_component_calls(
        self,
    ) -> None:
        cases = (
            (3, 6),
            (6, 3),
            (6, 8),
            (8, 6),
        )

        for configured_count, supplied_count in cases:
            with self.subTest(
                configured_count=configured_count,
                supplied_count=supplied_count,
            ):
                pipeline, selector, detector, geometry, _, reader = _pipeline(
                    policy=OcrPipelinePolicy(
                        frame_count=configured_count,
                    )
                )

                result = pipeline.read_plate(_frames(supplied_count))

                self.assertEqual(result.status, ReadStatus.INVALID_INPUT)
                self.assertEqual(selector.calls, 0)
                self.assertEqual(detector.calls, [])
                self.assertEqual(geometry.estimate_calls, [])
                self.assertEqual(reader.calls, [])

    def test_invalid_burst_contract_is_rejected_at_pipeline_boundary(
        self,
    ) -> None:
        valid = list(_frames())

        wrong_indices = valid.copy()
        wrong_indices[2] = CapturedFrame(
            frame_index=3,
            image=wrong_indices[2].image,
        )

        bool_index = valid.copy()
        bool_index[0] = CapturedFrame(
            frame_index=True,
            image=bool_index[0].image,
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

        empty_image = valid.copy()
        empty_image[0] = CapturedFrame(
            frame_index=0,
            image=np.zeros((0, 40, 3), dtype=np.uint8),
        )

        mixed_resolution = valid.copy()
        mixed_resolution[-1] = CapturedFrame(
            frame_index=5,
            image=np.zeros((25, 40, 3), dtype=np.uint8),
        )

        cases = (
            ("wrong_type", (object(), *valid[1:])),
            ("wrong_indices", tuple(wrong_indices)),
            ("bool_index", tuple(bool_index)),
            ("wrong_dtype", tuple(wrong_dtype)),
            ("wrong_channels", tuple(wrong_channels)),
            ("empty_image", tuple(empty_image)),
            ("mixed_resolution", tuple(mixed_resolution)),
        )

        for name, frames in cases:
            with self.subTest(name=name):
                pipeline, selector, detector, geometry, _, reader = _pipeline()

                result = pipeline.read_plate(frames)

                self.assertEqual(result.status, ReadStatus.INVALID_INPUT)
                self.assertEqual(selector.calls, 0)
                self.assertEqual(detector.calls, [])
                self.assertEqual(geometry.estimate_calls, [])
                self.assertEqual(reader.calls, [])

    def test_selector_must_follow_early_pool_and_last_anchor_policy(
        self,
    ) -> None:
        selectors = (
            FakeSelector(earlier_frame_index=2),
            FakeSelector(later_frame_index=4),
            FakeSelector(earlier_frame_index=True),
            FakeSelector(earlier_frame_index=1.0),
        )

        for selector in selectors:
            with self.subTest(selector=selector):
                pipeline, *_ = _pipeline(selector=selector)

                result = pipeline.read_plate(_frames())

                self.assertEqual(result.status, ReadStatus.INVALID_INPUT)

    def test_pipeline_continues_when_only_one_anchor_is_detected(self) -> None:
        cases = (
            ({1: _detection(1), 5: None}, (1,)),
            ({1: None, 5: _detection(5)}, (5,)),
        )

        for responses, expected_detection_indices in cases:
            with self.subTest(
                detected_indices=expected_detection_indices,
            ):
                geometry = FakeGeometry()
                pipeline, _, detector, _, _, _ = _pipeline(
                    detector=FakeDetector(responses),
                    geometry=geometry,
                )

                result = pipeline.read_plate(_frames())

                self.assertEqual(result.status, ReadStatus.SUCCESS)
                self.assertEqual(detector.calls, [1, 5])
                self.assertEqual(
                    geometry.estimate_calls,
                    [expected_detection_indices],
                )

    def test_later_single_anchor_succeeds_with_two_matching_frames(
        self,
    ) -> None:
        pipeline, _, _, _, _, reader = _pipeline(
            detector=FakeDetector(
                {1: None, 5: _detection(5)}
            ),
            geometry=PlateGeometry(),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(result.valid_frames, 2)
        self.assertEqual(result.vote_count, 2)
        self.assertEqual(result.vote_ratio, 1.0)
        self.assertEqual(reader.calls, [(4, 5)])

    def test_later_single_anchor_is_ambiguous_when_two_frames_disagree(
        self,
    ) -> None:
        pipeline, *_ = _pipeline(
            detector=FakeDetector(
                {1: None, 5: _detection(5)}
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
        self.assertEqual(result.valid_frames, 2)
        self.assertEqual(result.vote_count, 1)
        self.assertEqual(result.vote_ratio, 0.5)

    def test_no_detection_returns_no_plate_region(self) -> None:
        geometry = FakeGeometry()
        pipeline, _, detector, _, _, _ = _pipeline(
            detector=FakeDetector({1: None, 5: None}),
            geometry=geometry,
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.NO_PLATE_REGION)
        self.assertIsNone(result.plate_number)
        self.assertFalse(result.succeeded)
        self.assertEqual(detector.calls, [1, 5])
        self.assertEqual(geometry.estimate_calls, [])

    def test_rectification_failure_excludes_only_that_frame(self) -> None:
        pipeline, _, _, _, _, reader = _pipeline(
            geometry=FakeGeometry(rectify_failures={2}),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(reader.calls, [(0, 1, 3, 4, 5)])
        self.assertTrue(
            any(
                failure.stage == "rectification"
                and failure.frame_index == 2
                for failure in result.failures
            )
        )

    def test_preprocessing_failure_excludes_only_that_frame(self) -> None:
        pipeline, _, _, _, _, reader = _pipeline(
            preprocessor=FakePreprocessor({3}),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(reader.calls, [(0, 1, 2, 4, 5)])
        self.assertTrue(
            any(
                failure.stage == "preprocessing"
                and failure.frame_index == 3
                for failure in result.failures
            )
        )

    def test_ocr_empty_invalid_format_low_score_and_tie_are_results(
        self,
    ) -> None:
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

                self.assertEqual(result.status, expected_status)
                self.assertIsNone(result.plate_number)
                self.assertFalse(result.succeeded)

    def test_selector_value_error_is_currently_invalid_input_result(
        self,
    ) -> None:
        pipeline, *_ = _pipeline(
            selector=FakeSelector(ValueError("selector 계약 오류")),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.INVALID_INPUT)
        self.assertIsNone(result.plate_number)

    def test_detector_errors_are_currently_model_error_result(self) -> None:
        pipeline, *_ = _pipeline(
            detector=FakeDetector(
                {
                    1: RuntimeError("earlier detector 오류"),
                    5: RuntimeError("later detector 오류"),
                }
            )
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.MODEL_ERROR)
        self.assertIsNone(result.plate_number)

    def test_reader_error_is_currently_model_error_result(self) -> None:
        pipeline, *_ = _pipeline(
            reader=FakeReader(
                error=RuntimeError("recognizer 오류"),
            )
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.MODEL_ERROR)
        self.assertIsNone(result.plate_number)

    def test_unexpected_error_is_currently_internal_error_result(self) -> None:
        pipeline, *_ = _pipeline(
            aggregator=RaisingAggregator(),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.INTERNAL_ERROR)
        self.assertIsNone(result.plate_number)
        self.assertTrue(
            any(
                failure.stage == "pipeline"
                for failure in result.failures
            )
        )

    def test_invalid_frame_count_is_currently_invalid_input_result(
        self,
    ) -> None:
        pipeline, *_ = _pipeline()

        result = pipeline.read_plate(_frames(5))

        self.assertEqual(result.status, ReadStatus.INVALID_INPUT)
        self.assertIsNone(result.plate_number)

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
