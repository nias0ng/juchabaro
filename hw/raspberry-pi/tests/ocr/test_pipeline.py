"""실제 모델 없이 OCR pipeline의 공개 결과와 예외 계약을 검증한다."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import fields
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
from src.ocr.types import (
    AnchorSelection,
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    FrameQuality,
    OcrCandidate,
    PlateDecision,
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
) -> DetectedPlate:
    return DetectedPlate(
        frame_index=frame_index,
        bbox_xyxy=(5.0, 5.0, 25.0, 15.0),
        quad=quad,
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
            DetectedPlate | None | BaseException | object,
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
        return response  # type: ignore[return-value]


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

        if self.estimate_error is not None:
            raise self.estimate_error

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
        error = self.rectify_errors.get(frame.frame_index)
        if error is not None:
            raise error
        return RectifiedPlate(
            frame_index=frame.frame_index,
            image=frame.image,
            quad_estimate=estimate,
        )


class FakePreprocessor:
    def __init__(
        self,
        errors: dict[int, BaseException] | None = None,
    ) -> None:
        self.errors = errors or {}
        self.calls: list[int] = []

    def process(
        self,
        plate: RectifiedPlate,
    ) -> PreparedPlate:
        self.calls.append(plate.frame_index)
        error = self.errors.get(plate.frame_index)
        if error is not None:
            raise error
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
                raw_text=self.texts.get(
                    frame_index,
                    PLATE_NUMBER,
                ),
                rec_score=self.scores.get(
                    frame_index,
                    0.9,
                ),
            )
            for frame_index in result_indices
        )


class RaisingTextProcessor:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __call__(self, result: RawOcrResult) -> OcrCandidate:
        raise self.error


class RaisingAggregator:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> object:
        raise self.error


class ReturningAggregator:
    def __init__(self, value: object) -> None:
        self.value = value

    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> object:
        return self.value


class UnexpectedProgrammerError(RuntimeError):
    """Known component 오류로 분류되지 않은 테스트용 예외."""


def _pipeline(
    *,
    selector: FakeSelector | None = None,
    detector: FakeDetector | None = None,
    geometry: FakeGeometry | PlateGeometry | None = None,
    preprocessor: FakePreprocessor | None = None,
    reader: FakeReader | None = None,
    aggregator: object | None = None,
    text_processor: Callable[[RawOcrResult], OcrCandidate] | None = None,
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

    arguments: dict[str, object] = {
        "selector": selected_selector,
        "detector": selected_detector,
        "geometry": selected_geometry,
        "preprocessor": selected_preprocessor,
        "reader": selected_reader,
        "aggregator": selected_aggregator,
        "policy": policy,
    }
    if text_processor is not None:
        arguments["text_processor"] = text_processor

    pipeline = PlateOcrPipeline(**arguments)  # type: ignore[arg-type]
    return (
        pipeline,
        selected_selector,
        selected_detector,
        selected_geometry,
        selected_preprocessor,
        selected_reader,
    )


class PlateOcrPipelineContractTests(unittest.TestCase):
    """공개 DTO, 정상 판독 실패와 오류 예외의 경계를 검증한다."""

    def test_read_status_contains_only_normal_read_outcomes(self) -> None:
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
        self.assertTrue(issubclass(InvalidBurstError, OcrPipelineError))
        self.assertTrue(issubclass(OcrRuntimeError, OcrPipelineError))

    def test_plate_read_result_has_only_public_minimum_fields(self) -> None:
        self.assertEqual(
            tuple(field.name for field in fields(PlateReadResult)),
            ("status", "plate_number"),
        )

        success = PlateReadResult(
            status=ReadStatus.SUCCESS,
            plate_number=PLATE_NUMBER,
        )
        failure = PlateReadResult(
            status=ReadStatus.AMBIGUOUS,
            plate_number=None,
        )

        self.assertTrue(success.succeeded)
        self.assertFalse(failure.succeeded)
        for removed_field in (
            "total_frames",
            "valid_frames",
            "vote_count",
            "vote_ratio",
            "mean_rec_score",
            "candidates",
            "failures",
            "metrics",
            "error_message",
        ):
            self.assertFalse(hasattr(success, removed_field))

    def test_six_frame_success_calls_two_anchors_and_returns_minimum_dto(
        self,
    ) -> None:
        pipeline, selector, detector, geometry, _, reader = _pipeline()

        result = pipeline.read_plate(_frames())

        self.assertEqual(
            result,
            PlateReadResult(
                status=ReadStatus.SUCCESS,
                plate_number=PLATE_NUMBER,
            ),
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(selector.calls, 1)
        self.assertEqual(detector.calls, [1, 5])
        self.assertEqual(geometry.estimate_calls, [(1, 5)])
        self.assertEqual(reader.calls, [(0, 1, 2, 3, 4, 5)])

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
                self.assertEqual(result.plate_number, PLATE_NUMBER)
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

    def test_policy_mismatch_raises_invalid_burst_before_components(
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

                with self.assertRaises(InvalidBurstError):
                    pipeline.read_plate(_frames(supplied_count))

                self.assertEqual(selector.calls, 0)
                self.assertEqual(detector.calls, [])
                self.assertEqual(geometry.estimate_calls, [])
                self.assertEqual(reader.calls, [])

    def test_malformed_burst_raises_invalid_burst_at_boundary(self) -> None:
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

        cases: tuple[tuple[str, object], ...] = (
            ("not_iterable", None),
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

                with self.assertRaises(InvalidBurstError):
                    pipeline.read_plate(frames)  # type: ignore[arg-type]

                self.assertEqual(selector.calls, 0)
                self.assertEqual(detector.calls, [])
                self.assertEqual(geometry.estimate_calls, [])
                self.assertEqual(reader.calls, [])

    def test_internal_component_output_contract_raises_runtime_error(
        self,
    ) -> None:
        cases: tuple[
            tuple[str, Callable[[], PlateOcrPipeline]],
            ...,
        ] = (
            (
                "selector_anchor",
                lambda: _pipeline(
                    selector=FakeSelector(earlier_frame_index=2)
                )[0],
            ),
            (
                "selector_later_not_last",
                lambda: _pipeline(
                    selector=FakeSelector(later_frame_index=4)
                )[0],
            ),
            (
                "selector_bool_index",
                lambda: _pipeline(
                    selector=FakeSelector(
                        earlier_frame_index=True
                    )
                )[0],
            ),
            (
                "selector_float_index",
                lambda: _pipeline(
                    selector=FakeSelector(
                        earlier_frame_index=1.0  # type: ignore[arg-type]
                    )
                )[0],
            ),
            (
                "selector_custom_early_pool",
                lambda: _pipeline(
                    selector=FakeSelector(earlier_frame_index=1),
                    policy=OcrPipelinePolicy(
                        early_anchor_candidate_count=1
                    ),
                )[0],
            ),
            (
                "detector_index",
                lambda: _pipeline(
                    detector=FakeDetector(
                        {1: _detection(0)}
                    )
                )[0],
            ),
            (
                "detector_bool_index",
                lambda: _pipeline(
                    detector=FakeDetector(
                        {1: _detection(True)}
                    )
                )[0],
            ),
            (
                "geometry_index",
                lambda: _pipeline(
                    geometry=FakeGeometry(
                        estimated_indices=(99,)
                    )
                )[0],
            ),
            (
                "reader_order",
                lambda: _pipeline(
                    reader=FakeReader(
                        result_indices=(5, 4, 3, 2, 1, 0)
                    )
                )[0],
            ),
            (
                "aggregator_type",
                lambda: _pipeline(
                    aggregator=ReturningAggregator(object())
                )[0],
            ),
            (
                "aggregator_impossible_success",
                lambda: _pipeline(
                    aggregator=ReturningAggregator(
                        PlateDecision(
                            status=ReadStatus.SUCCESS,
                            plate_number=None,
                            valid_frames=6,
                            vote_count=6,
                            vote_ratio=1.0,
                            mean_rec_score=0.9,
                        )
                    )
                )[0],
            ),
            (
                "aggregator_zero_vote_success",
                lambda: _pipeline(
                    aggregator=ReturningAggregator(
                        PlateDecision(
                            status=ReadStatus.SUCCESS,
                            plate_number=PLATE_NUMBER,
                            valid_frames=0,
                            vote_count=0,
                            vote_ratio=0.0,
                            mean_rec_score=0.0,
                        )
                    )
                )[0],
            ),
            (
                "aggregator_unknown_winner",
                lambda: _pipeline(
                    aggregator=ReturningAggregator(
                        PlateDecision(
                            status=ReadStatus.SUCCESS,
                            plate_number="99하9999",
                            valid_frames=1,
                            vote_count=1,
                            vote_ratio=1.0,
                            mean_rec_score=0.9,
                        )
                    )
                )[0],
            ),
            (
                "aggregator_failure_with_plate",
                lambda: _pipeline(
                    aggregator=ReturningAggregator(
                        PlateDecision(
                            status=ReadStatus.AMBIGUOUS,
                            plate_number=PLATE_NUMBER,
                            valid_frames=6,
                            vote_count=6,
                            vote_ratio=1.0,
                            mean_rec_score=0.9,
                            error_message="ambiguous",
                        )
                    )
                )[0],
            ),
        )

        for name, build_pipeline in cases:
            with self.subTest(stage=name):
                with self.assertRaises(OcrRuntimeError):
                    build_pipeline().read_plate(_frames())

    def test_known_component_errors_are_wrapped_as_runtime_errors(
        self,
    ) -> None:
        builders: tuple[
            tuple[
                str,
                Callable[[OcrComponentError], PlateOcrPipeline],
            ],
            ...,
        ] = (
            (
                "selector",
                lambda error: _pipeline(
                    selector=FakeSelector(error)
                )[0],
            ),
            (
                "detector",
                lambda error: _pipeline(
                    detector=FakeDetector({1: error})
                )[0],
            ),
            (
                "geometry_estimate",
                lambda error: _pipeline(
                    geometry=FakeGeometry(estimate_error=error)
                )[0],
            ),
            (
                "rectification",
                lambda error: _pipeline(
                    geometry=FakeGeometry(
                        rectify_errors={0: error}
                    )
                )[0],
            ),
            (
                "preprocessing",
                lambda error: _pipeline(
                    preprocessor=FakePreprocessor({0: error})
                )[0],
            ),
            (
                "reader",
                lambda error: _pipeline(
                    reader=FakeReader(error=error)
                )[0],
            ),
            (
                "text_postprocessing",
                lambda error: _pipeline(
                    text_processor=RaisingTextProcessor(error)
                )[0],
            ),
            (
                "aggregation",
                lambda error: _pipeline(
                    aggregator=RaisingAggregator(error)
                )[0],
            ),
        )

        for stage, build_pipeline in builders:
            with self.subTest(stage=stage):
                component_error = OcrComponentError(
                    f"{stage} known error"
                )

                with self.assertRaises(OcrRuntimeError) as caught:
                    build_pipeline(component_error).read_plate(_frames())

                self.assertIs(
                    caught.exception.__cause__,
                    component_error,
                )

    def test_unknown_programmer_errors_propagate_as_same_object(
        self,
    ) -> None:
        builders: tuple[
            tuple[
                str,
                Callable[
                    [UnexpectedProgrammerError],
                    PlateOcrPipeline,
                ],
            ],
            ...,
        ] = (
            (
                "selector",
                lambda error: _pipeline(
                    selector=FakeSelector(error)
                )[0],
            ),
            (
                "detector",
                lambda error: _pipeline(
                    detector=FakeDetector({1: error})
                )[0],
            ),
            (
                "geometry_estimate",
                lambda error: _pipeline(
                    geometry=FakeGeometry(estimate_error=error)
                )[0],
            ),
            (
                "rectification",
                lambda error: _pipeline(
                    geometry=FakeGeometry(
                        rectify_errors={0: error}
                    )
                )[0],
            ),
            (
                "preprocessing",
                lambda error: _pipeline(
                    preprocessor=FakePreprocessor({0: error})
                )[0],
            ),
            (
                "reader",
                lambda error: _pipeline(
                    reader=FakeReader(error=error)
                )[0],
            ),
            (
                "text_postprocessing",
                lambda error: _pipeline(
                    text_processor=RaisingTextProcessor(error)
                )[0],
            ),
            (
                "aggregation",
                lambda error: _pipeline(
                    aggregator=RaisingAggregator(error)
                )[0],
            ),
        )

        for stage, build_pipeline in builders:
            with self.subTest(stage=stage):
                programmer_error = UnexpectedProgrammerError(
                    f"{stage} unexpected error"
                )

                with self.assertRaises(
                    UnexpectedProgrammerError
                ) as caught:
                    build_pipeline(programmer_error).read_plate(
                        _frames()
                    )

                self.assertIs(caught.exception, programmer_error)

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

    def test_geometry_can_omit_one_frame_and_continue(self) -> None:
        geometry = FakeGeometry(
            estimated_indices=(0, 1, 3, 4, 5)
        )
        pipeline, _, _, _, _, reader = _pipeline(
            geometry=geometry,
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(reader.calls, [(0, 1, 3, 4, 5)])

    def test_scene_geometry_failure_excludes_only_that_frame(self) -> None:
        pipeline, _, _, _, _, reader = _pipeline(
            geometry=FakeGeometry(
                rectify_errors={
                    2: GeometryError("사용할 수 없는 장면 좌표")
                }
            ),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(reader.calls, [(0, 1, 3, 4, 5)])

    def test_all_scene_invalid_anchor_quads_return_no_plate_region(
        self,
    ) -> None:
        pipeline, *_ = _pipeline(
            detector=FakeDetector(
                {
                    1: _detection(
                        1,
                        quad=INVALID_PLATE_QUAD,
                    ),
                    5: _detection(
                        5,
                        quad=INVALID_PLATE_QUAD,
                    ),
                }
            ),
            geometry=PlateGeometry(),
        )

        result = pipeline.read_plate(_frames())

        self.assertEqual(
            result,
            PlateReadResult(
                status=ReadStatus.NO_PLATE_REGION,
                plate_number=None,
            ),
        )

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
        self.assertEqual(result.plate_number, PLATE_NUMBER)
        self.assertEqual(reader.calls, [(4, 5)])

    def test_later_single_anchor_is_ambiguous_when_frames_disagree(
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
        self.assertFalse(result.succeeded)

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
                    ),
                )
                self.assertFalse(result.succeeded)

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
