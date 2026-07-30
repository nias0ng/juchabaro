"""
촬영된 프레임 burst를 전체 번호판 문자열로 변환하는 OCR 흐름을 조율한다.

파이프라인 순서:
    frame selection → YOLO → geometry → image preprocessing
    → PaddleOCR → text postprocessing → aggregation

이 모듈은 이미 로드된 모델 adapter를 전달받아 재사용한다. 센서 대기,
카메라 촬영, 촬영 시각 생성, 모델 다운로드와 Jetson 전송은 담당하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import math
from numbers import Real
from threading import Lock
from typing import Protocol

from .errors import (
    InvalidBurstError,
    OcrComponentError,
    OcrRuntimeError,
)
from .image_validation import is_nonempty_bgr_uint8_image
from .policy import OcrPipelinePolicy
from .postprocessing.plate_text import build_ocr_candidate
from .types import (
    AnchorSelection,
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    FrameQuality,
    OcrCandidate,
    PlateDecision,
    PlateReadResult,
    PreparedPlate,
    RawOcrResult,
    ReadStatus,
    RectifiedPlate,
)
from .vision.geometry import GeometryError


# [파이프라인 의존성 Protocol]


class FrameSelectorPort(Protocol):
    """YOLO를 실행할 시간적으로 떨어진 두 anchor를 선택하는 계약."""

    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        """프레임 품질과 촬영 순서를 이용해 anchor 선택 결과를 반환한다."""


class PlateDetectorPort(Protocol):
    """이미 로드된 번호판 pose 모델의 추론 계약."""

    def detect(
        self,
        frame: CapturedFrame,
    ) -> DetectedPlate | None:
        """한 프레임에서 사용할 번호판 후보 하나를 반환한다."""


class PlateGeometryPort(Protocol):
    """Anchor 좌표 추정과 원근 보정 계약."""

    def estimate_quads(
        self,
        frames: Sequence[CapturedFrame],
        detections: Sequence[DetectedPlate],
    ) -> tuple[EstimatedQuad, ...]:
        """검출된 anchor로 각 프레임의 사용 가능한 4점을 추정한다."""

    def rectify(
        self,
        frame: CapturedFrame,
        estimate: EstimatedQuad,
    ) -> RectifiedPlate:
        """추정된 4점으로 번호판을 원근 보정한다."""


class PlatePreprocessorPort(Protocol):
    """원근 보정 번호판의 OCR용 화질 전처리 계약."""

    def process(
        self,
        plate: RectifiedPlate,
    ) -> PreparedPlate:
        """번호판 한 장을 PaddleOCR 입력 형태로 변환한다."""


class PlateReaderPort(Protocol):
    """이미 로드된 PaddleOCR recognition 모델의 batch 추론 계약."""

    def recognize(
        self,
        plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        """전처리된 번호판들을 인식하고 원시 OCR 결과를 반환한다."""


class PlateAggregatorPort(Protocol):
    """프레임별 OCR 후보를 전체 번호판 하나로 집계하는 계약."""

    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> PlateDecision:
        """전체 문자열 기준 다수결 판정을 반환한다."""


# [OCR 파이프라인]


class PlateOcrPipeline:
    """
    시간순 프레임 burst에서 전체 번호판을 읽는 재사용 가능한 파이프라인.

    입력:
        정책의 ``frame_count``와 길이가 같고 frame_index가 0부터
        연속적인 BGR uint8 프레임.

    출력:
        정상 판독 상태와 성공 시 전체 번호판만 포함한
        ``PlateReadResult``.

    실패:
        잘못된 burst는 ``InvalidBurstError``, 알려진 component 오류는
        ``OcrRuntimeError``로 전달한다. 그 밖의 예외는 원형 전파한다.
    """

    def __init__(
        self,
        *,
        selector: FrameSelectorPort,
        detector: PlateDetectorPort,
        geometry: PlateGeometryPort,
        preprocessor: PlatePreprocessorPort,
        reader: PlateReaderPort,
        aggregator: PlateAggregatorPort,
        text_processor: Callable[
            [RawOcrResult],
            OcrCandidate,
        ] = build_ocr_candidate,
        policy: OcrPipelinePolicy | None = None,
    ) -> None:
        self._selector = selector
        self._detector = detector
        self._geometry = geometry
        self._preprocessor = preprocessor
        self._reader = reader
        self._aggregator = aggregator
        self._text_processor = text_processor
        self._policy = policy or OcrPipelinePolicy()

        # 동일 모델 객체에 두 차량 이벤트가 섞여 들어가지 않게 한다.
        self._event_lock = Lock()

    def read_plate(
        self,
        frames: Sequence[CapturedFrame],
    ) -> PlateReadResult:
        """
        한 번의 차량 촬영 burst를 처리해 전체 번호판 판정을 반환한다.

        입력:
            정책의 ``frame_count``와 길이가 같고 촬영 시간순인
            CapturedFrame 시퀀스.

        출력:
            성공 번호 또는 정상적인 판독 실패 상태를 담은 PlateReadResult.

        실패:
            burst 계약 위반은 InvalidBurstError, 알려진 모델·adapter·
            OpenCV·내부 invariant 오류는 OcrRuntimeError가 발생한다.
            예상하지 못한 component 예외는 변환하지 않는다.

        YOLO가 한 anchor에서 정상적으로 ``None``을 반환하거나 geometry가
        장면상 사용할 수 없는 프레임 좌표를 생략하면 나머지로 계속한다.
        """

        with self._event_lock:
            try:
                frame_tuple = tuple(frames)
            except TypeError as exc:
                raise InvalidBurstError(
                    "frames는 CapturedFrame 시퀀스여야 합니다."
                ) from exc

            try:
                self._validate_frames(frame_tuple)
            except ValueError as exc:
                raise InvalidBurstError(str(exc)) from exc

            return self._run_event(frame_tuple)

    def _run_event(
        self,
        frames: tuple[CapturedFrame, ...],
    ) -> PlateReadResult:
        frame_by_index = {
            frame.frame_index: frame
            for frame in frames
        }

        anchor_indices = self._select_anchors(
            frames,
            frame_by_index,
        )
        detections = self._detect_anchors(
            frame_by_index,
            anchor_indices,
        )
        if not detections:
            return self._no_plate_region_result()

        estimate_by_index = self._estimate_quads(
            frames,
            detections,
            frame_by_index,
        )
        if not estimate_by_index:
            return self._no_plate_region_result()

        rectified_plates = self._rectify_frames(
            frames,
            estimate_by_index,
        )
        if not rectified_plates:
            return self._no_plate_region_result()

        prepared_plates = self._prepare_plates(rectified_plates)
        raw_results = self._recognize(prepared_plates)
        candidates = self._build_candidates(raw_results)
        decision = self._aggregate(candidates)
        return self._decision_result(decision, candidates)

    # [단계별 실행]

    def _select_anchors(
        self,
        frames: tuple[CapturedFrame, ...],
        frame_by_index: dict[int, CapturedFrame],
    ) -> tuple[int, int]:
        """Anchor selector를 실행하고 두 프레임 인덱스 계약을 검증한다."""

        try:
            selection = self._selector.select_anchors(frames)
        except OcrComponentError as exc:
            raise self._component_runtime_error(
                "frame selector",
                exc,
            ) from exc

        return self._validate_selection(
            selection,
            frame_by_index,
        )

    def _detect_anchors(
        self,
        frame_by_index: dict[int, CapturedFrame],
        anchor_indices: tuple[int, int],
    ) -> list[DetectedPlate]:
        """두 anchor를 모두 검사하고 정상 미검출은 제외한다."""

        detections: list[DetectedPlate] = []

        # 첫 anchor의 정상 미검출(None)과 무관하게 두 번째도 실행해
        # single-anchor fallback 가능성을 유지한다.
        for frame_index in anchor_indices:
            try:
                detection = self._detector.detect(
                    frame_by_index[frame_index]
                )
            except OcrComponentError as exc:
                raise self._component_runtime_error(
                    "plate detector",
                    exc,
                ) from exc

            if detection is None:
                continue
            if not isinstance(detection, DetectedPlate):
                raise OcrRuntimeError(
                    "detector는 DetectedPlate 또는 None을 반환해야 합니다."
                )
            self._validate_matching_frame_index(
                component="detector",
                actual=detection.frame_index,
                expected=frame_index,
            )
            detections.append(detection)

        return detections

    def _estimate_quads(
        self,
        frames: tuple[CapturedFrame, ...],
        detections: Sequence[DetectedPlate],
        frame_by_index: dict[int, CapturedFrame],
    ) -> dict[int, EstimatedQuad]:
        """Anchor 좌표를 추정·검증하고 frame index mapping을 반환한다."""

        try:
            estimates = self._geometry.estimate_quads(
                frames,
                detections,
            )
        except GeometryError:
            return {}
        except OcrComponentError as exc:
            raise self._component_runtime_error(
                "plate geometry",
                exc,
            ) from exc

        return self._index_estimates(
            estimates,
            frame_by_index,
        )

    def _rectify_frames(
        self,
        frames: tuple[CapturedFrame, ...],
        estimate_by_index: dict[int, EstimatedQuad],
    ) -> list[RectifiedPlate]:
        """좌표가 있는 프레임을 보정하고 장면상 실패한 프레임만 제외한다."""

        rectified_plates: list[RectifiedPlate] = []

        for frame in frames:
            estimate = estimate_by_index.get(frame.frame_index)
            if estimate is None:
                continue

            try:
                rectified = self._geometry.rectify(
                    frame,
                    estimate,
                )
            except GeometryError:
                continue
            except OcrComponentError as exc:
                raise self._component_runtime_error(
                    "perspective rectification",
                    exc,
                ) from exc

            if not isinstance(rectified, RectifiedPlate):
                raise OcrRuntimeError(
                    "geometry.rectify는 RectifiedPlate를 반환해야 합니다."
                )
            self._validate_matching_frame_index(
                component="geometry",
                actual=rectified.frame_index,
                expected=frame.frame_index,
            )
            rectified_plates.append(rectified)

        return rectified_plates

    def _prepare_plates(
        self,
        rectified_plates: Sequence[RectifiedPlate],
    ) -> list[PreparedPlate]:
        """원근 보정 번호판을 OCR 입력으로 전처리하고 계약을 검증한다."""

        prepared_plates: list[PreparedPlate] = []

        for plate in rectified_plates:
            try:
                prepared = self._preprocessor.process(plate)
            except OcrComponentError as exc:
                raise self._component_runtime_error(
                    "plate preprocessing",
                    exc,
                ) from exc

            if not isinstance(prepared, PreparedPlate):
                raise OcrRuntimeError(
                    "preprocessor는 PreparedPlate를 반환해야 합니다."
                )
            self._validate_matching_frame_index(
                component="preprocessor",
                actual=prepared.frame_index,
                expected=plate.frame_index,
            )
            prepared_plates.append(prepared)

        if not prepared_plates:
            raise OcrRuntimeError(
                "OCR 전처리 결과가 비어 있습니다."
            )
        return prepared_plates

    def _recognize(
        self,
        prepared_plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        """PaddleOCR batch를 실행하고 입력과 일대일인 결과를 반환한다."""

        try:
            raw_results = self._reader.recognize(
                prepared_plates
            )
        except OcrComponentError as exc:
            raise self._component_runtime_error(
                "plate recognition",
                exc,
            ) from exc

        return self._validate_raw_results(
            raw_results,
            prepared_plates,
        )

    def _build_candidates(
        self,
        raw_results: Sequence[RawOcrResult],
    ) -> list[OcrCandidate]:
        """원시 OCR 결과를 검증된 번호판 후보로 변환한다."""

        candidates: list[OcrCandidate] = []

        for raw_result in raw_results:
            try:
                candidate = self._text_processor(raw_result)
            except OcrComponentError as exc:
                raise self._component_runtime_error(
                    "OCR text postprocessing",
                    exc,
                ) from exc

            if not isinstance(candidate, OcrCandidate):
                raise OcrRuntimeError(
                    "text processor는 OcrCandidate를 반환해야 합니다."
                )
            self._validate_candidate(
                candidate,
                raw_result,
            )
            candidates.append(candidate)

        if not candidates:
            raise OcrRuntimeError(
                "후처리 가능한 OCR 결과가 없습니다."
            )
        return candidates

    def _aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> PlateDecision:
        """후보를 집계하고 알려진 component 오류를 runtime 오류로 바꾼다."""

        try:
            return self._aggregator.aggregate(candidates)
        except OcrComponentError as exc:
            raise self._component_runtime_error(
                "candidate aggregation",
                exc,
            ) from exc

    @staticmethod
    def _no_plate_region_result() -> PlateReadResult:
        """사용할 번호판 영역이 없는 정상 판독 결과를 만든다."""

        return PlateReadResult(
            status=ReadStatus.NO_PLATE_REGION,
            plate_number=None,
        )

    # [입력과 단계별 계약 검증]

    @staticmethod
    def _validate_matching_frame_index(
        *,
        component: str,
        actual: object,
        expected: int,
    ) -> None:
        """Component 반환 index가 bool이 아닌 동일한 정수인지 확인한다."""

        if isinstance(actual, bool) or not isinstance(actual, int):
            raise OcrRuntimeError(
                f"{component} frame_index는 bool이 아닌 정수여야 합니다."
            )
        if actual != expected:
            raise OcrRuntimeError(
                f"{component}가 입력과 다른 frame_index를 반환했습니다."
            )

    @staticmethod
    def _validate_candidate(
        candidate: OcrCandidate,
        raw_result: RawOcrResult,
    ) -> None:
        """문자열 후처리 결과의 타입·index·score 계약을 확인한다."""

        PlateOcrPipeline._validate_matching_frame_index(
            component="text processor",
            actual=candidate.frame_index,
            expected=raw_result.frame_index,
        )
        if (
            not isinstance(candidate.raw_text, str)
            or not isinstance(candidate.normalized_text, str)
        ):
            raise OcrRuntimeError(
                "OCR candidate 문자열 필드는 str이어야 합니다."
            )
        if (
            isinstance(candidate.rec_score, bool)
            or not isinstance(candidate.rec_score, Real)
            or not math.isfinite(float(candidate.rec_score))
            or not 0.0 <= float(candidate.rec_score) <= 1.0
        ):
            raise OcrRuntimeError(
                "OCR candidate rec_score는 0~1 범위의 유한한 수여야 합니다."
            )
        if not isinstance(candidate.valid_format, bool):
            raise OcrRuntimeError(
                "OCR candidate valid_format은 bool이어야 합니다."
            )

    def _validate_frames(
        self,
        frames: Sequence[CapturedFrame],
    ) -> None:
        """Burst의 수, 순서, dtype, shape와 해상도 계약을 확인한다."""

        expected_count = self._policy.frame_count

        if len(frames) != expected_count:
            raise ValueError(
                f"시간순 프레임 {expected_count}장이 필요합니다: "
                f"actual={len(frames)}"
            )

        if any(
            not isinstance(frame, CapturedFrame)
            for frame in frames
        ):
            raise ValueError(
                "frames의 모든 항목은 CapturedFrame이어야 합니다."
            )

        if any(
            isinstance(frame.frame_index, bool)
            or not isinstance(frame.frame_index, int)
            for frame in frames
        ):
            raise ValueError(
                "frame_index는 bool이 아닌 정수여야 합니다."
            )

        expected_indices = tuple(range(expected_count))
        actual_indices = tuple(
            frame.frame_index
            for frame in frames
        )

        if actual_indices != expected_indices:
            raise ValueError(
                "frame_index는 촬영 시간순 "
                f"0~{expected_count - 1}이어야 합니다: "
                f"actual={actual_indices}"
            )

        image_shapes: set[tuple[int, ...]] = set()

        for frame in frames:
            image = frame.image

            if not is_nonempty_bgr_uint8_image(image):
                raise ValueError(
                    f"frame_index={frame.frame_index}: "
                    "BGR uint8 HxWx3 이미지가 필요합니다."
                )

            image_shapes.add(tuple(image.shape))

        # 동일 좌표 보간을 사용하므로 burst 안의 해상도는 같아야 한다.
        if len(image_shapes) != 1:
            raise ValueError(
                "한 burst의 모든 프레임 해상도는 같아야 합니다."
            )

    def _validate_selection(
        self,
        selection: AnchorSelection,
        frame_by_index: dict[int, CapturedFrame],
    ) -> tuple[int, int]:
        """Selector 결과가 YOLO 호출 정책과 입력 범위를 만족하는지 확인한다."""

        if not isinstance(selection, AnchorSelection):
            raise OcrRuntimeError(
                "selector는 AnchorSelection을 반환해야 합니다."
            )

        anchor_indices = (
            selection.earlier_frame_index,
            selection.later_frame_index,
        )

        if any(
            isinstance(index, bool)
            or not isinstance(index, int)
            for index in anchor_indices
        ):
            raise OcrRuntimeError(
                "anchor frame_index는 bool이 아닌 정수여야 합니다."
            )

        if len(set(anchor_indices)) != len(anchor_indices):
            raise OcrRuntimeError(
                "두 anchor의 frame_index가 중복되었습니다."
            )

        if any(
            index not in frame_by_index
            for index in anchor_indices
        ):
            raise OcrRuntimeError(
                "입력에 없는 frame_index가 anchor로 선택되었습니다."
            )

        if anchor_indices[0] >= anchor_indices[1]:
            raise OcrRuntimeError(
                "earlier anchor는 later anchor보다 앞서야 합니다."
            )

        if (
            anchor_indices[0]
            >= self._policy.early_anchor_candidate_count
        ):
            raise OcrRuntimeError(
                "earlier anchor가 정책의 품질 비교 후보 범위를 "
                "벗어났습니다."
            )

        if anchor_indices[1] != self._policy.frame_count - 1:
            raise OcrRuntimeError(
                "later anchor는 burst의 마지막 프레임이어야 합니다."
            )

        try:
            qualities = tuple(selection.qualities)
        except TypeError as exc:
            raise OcrRuntimeError(
                "selector qualities는 FrameQuality 시퀀스여야 합니다."
            ) from exc

        if any(
            not isinstance(quality, FrameQuality)
            for quality in qualities
        ):
            raise OcrRuntimeError(
                "selector qualities는 FrameQuality 시퀀스여야 합니다."
            )

        quality_indices = tuple(quality.frame_index for quality in qualities)
        if any(
            isinstance(index, bool)
            or not isinstance(index, int)
            for index in quality_indices
        ):
            raise OcrRuntimeError(
                "quality frame_index는 bool이 아닌 정수여야 합니다."
            )

        if quality_indices != tuple(frame_by_index):
            raise OcrRuntimeError(
                "품질 평가 결과가 입력 프레임 순서와 다릅니다."
            )

        return anchor_indices

    @staticmethod
    def _index_estimates(
        estimates: Sequence[EstimatedQuad],
        frame_by_index: dict[int, CapturedFrame],
    ) -> dict[int, EstimatedQuad]:
        """좌표 추정 결과의 중복과 입력 범위를 검사해 index mapping을 만든다."""

        try:
            estimate_tuple = tuple(estimates)
        except TypeError as exc:
            raise OcrRuntimeError(
                "geometry 결과는 EstimatedQuad 시퀀스여야 합니다."
            ) from exc

        estimate_by_index: dict[int, EstimatedQuad] = {}

        for estimate in estimate_tuple:
            if not isinstance(estimate, EstimatedQuad):
                raise OcrRuntimeError(
                    "geometry 결과는 EstimatedQuad 시퀀스여야 합니다."
                )
            if (
                isinstance(estimate.frame_index, bool)
                or not isinstance(estimate.frame_index, int)
            ):
                raise OcrRuntimeError(
                    "geometry frame_index는 bool이 아닌 정수여야 합니다."
                )
            if estimate.frame_index not in frame_by_index:
                raise OcrRuntimeError(
                    "geometry가 입력에 없는 frame_index를 반환했습니다."
                )

            if estimate.frame_index in estimate_by_index:
                raise OcrRuntimeError(
                    "geometry 결과의 frame_index가 중복되었습니다."
                )

            estimate_by_index[estimate.frame_index] = estimate
        return estimate_by_index

    @staticmethod
    def _validate_raw_results(
        raw_results: Sequence[RawOcrResult],
        prepared_plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        """PaddleOCR 결과가 입력 batch와 일대일 대응하는지 확인한다."""

        try:
            result_tuple = tuple(raw_results)
        except TypeError as exc:
            raise OcrRuntimeError(
                "PaddleOCR 결과는 RawOcrResult 시퀀스여야 합니다."
            ) from exc

        for result in result_tuple:
            if not isinstance(result, RawOcrResult):
                raise OcrRuntimeError(
                    "PaddleOCR 결과는 RawOcrResult 시퀀스여야 합니다."
                )
            if (
                isinstance(result.frame_index, bool)
                or not isinstance(result.frame_index, int)
            ):
                raise OcrRuntimeError(
                    "PaddleOCR frame_index는 bool이 아닌 정수여야 합니다."
                )
            if not isinstance(result.raw_text, str):
                raise OcrRuntimeError(
                    "PaddleOCR raw_text는 문자열이어야 합니다."
                )
            if (
                isinstance(result.rec_score, bool)
                or not isinstance(result.rec_score, Real)
                or not math.isfinite(float(result.rec_score))
                or not 0.0 <= float(result.rec_score) <= 1.0
            ):
                raise OcrRuntimeError(
                    "PaddleOCR rec_score는 0~1 범위의 유한한 수여야 합니다."
                )

        expected_indices = tuple(
            plate.frame_index
            for plate in prepared_plates
        )
        actual_indices = tuple(
            result.frame_index
            for result in result_tuple
        )

        if actual_indices != expected_indices:
            raise OcrRuntimeError(
                "PaddleOCR 결과 순서가 입력 batch와 다릅니다: "
                f"expected={expected_indices}, actual={actual_indices}"
            )

        return result_tuple

    # [최종 결과 생성]

    @staticmethod
    def _decision_result(
        decision: PlateDecision,
        candidates: Sequence[OcrCandidate],
    ) -> PlateReadResult:
        """집계기의 판정을 상위 서비스용 최종 결과로 변환한다."""

        if not isinstance(decision, PlateDecision):
            raise OcrRuntimeError(
                "aggregator는 PlateDecision을 반환해야 합니다."
            )
        if not isinstance(decision.status, ReadStatus):
            raise OcrRuntimeError(
                "aggregator가 알 수 없는 ReadStatus를 반환했습니다."
            )
        if decision.status is ReadStatus.NO_PLATE_REGION:
            raise OcrRuntimeError(
                "NO_PLATE_REGION은 aggregator가 반환할 수 없습니다."
            )

        integer_diagnostics = (
            decision.valid_frames,
            decision.vote_count,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in integer_diagnostics
        ):
            raise OcrRuntimeError(
                "aggregator의 frame·vote 진단값이 유효하지 않습니다."
            )
        if decision.vote_count > decision.valid_frames:
            raise OcrRuntimeError(
                "aggregator vote_count는 valid_frames보다 클 수 없습니다."
            )
        if decision.valid_frames > len(candidates):
            raise OcrRuntimeError(
                "aggregator valid_frames는 후보 수보다 클 수 없습니다."
            )

        probability_diagnostics = (
            decision.vote_ratio,
            decision.mean_rec_score,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 1.0
            for value in probability_diagnostics
        ):
            raise OcrRuntimeError(
                "aggregator의 비율·confidence 진단값이 유효하지 않습니다."
            )

        expected_vote_ratio = (
            decision.vote_count / decision.valid_frames
            if decision.valid_frames
            else 0.0
        )
        if not math.isclose(
            float(decision.vote_ratio),
            expected_vote_ratio,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise OcrRuntimeError(
                "aggregator vote_ratio가 득표 진단값과 일치하지 않습니다."
            )

        if (
            decision.error_message is not None
            and not isinstance(decision.error_message, str)
        ):
            raise OcrRuntimeError(
                "aggregator error_message는 문자열 또는 None이어야 합니다."
            )

        if decision.status is ReadStatus.SUCCESS:
            if (
                not isinstance(decision.plate_number, str)
                or not decision.plate_number
            ):
                raise OcrRuntimeError(
                    "SUCCESS 판정에는 비어 있지 않은 plate_number가 필요합니다."
                )
            if decision.valid_frames == 0 or decision.vote_count == 0:
                raise OcrRuntimeError(
                    "SUCCESS 판정에는 유효 프레임과 득표가 필요합니다."
                )
            matching_candidates = sum(
                candidate.normalized_text == decision.plate_number
                for candidate in candidates
            )
            if matching_candidates < decision.vote_count:
                raise OcrRuntimeError(
                    "SUCCESS plate_number와 득표 진단값이 후보와 "
                    "일치하지 않습니다."
                )
            if decision.error_message is not None:
                raise OcrRuntimeError(
                    "SUCCESS 판정에는 error_message가 없어야 합니다."
                )
        elif decision.plate_number is not None:
            raise OcrRuntimeError(
                "성공이 아닌 판정에는 plate_number가 없어야 합니다."
            )

        return PlateReadResult(
            status=decision.status,
            plate_number=decision.plate_number,
        )

    @staticmethod
    def _component_runtime_error(
        stage: str,
        error: OcrComponentError,
    ) -> OcrRuntimeError:
        """알려진 component 오류를 공개 runtime 오류로 변환한다."""

        return OcrRuntimeError(
            f"{stage} 실행 또는 계약 오류: "
            f"{type(error).__name__}: {error}"
        )
