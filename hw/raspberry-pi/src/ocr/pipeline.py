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
from threading import Lock
from typing import Protocol

from .errors import (
    InvalidBurstError,
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
    ) -> tuple[DetectedPlate, ...]:
        """한 프레임의 번호판 후보를 우선순위 순으로 반환한다."""


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
        정상 판독 상태와 성공 시 전체 번호판 및 winner의 대표
        PaddleOCR ``rec_score``를 포함한 ``PlateReadResult``.

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

        # 한 pipeline 인스턴스에서 두 차량 이벤트의 여러 stage가 서로
        # 섞이지 않게 하며 공유 모델과 CLAHE의 동시 사용도 방지한다.
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
            성공 번호와 대표 ``rec_score`` 또는 정상적인 판독 실패 상태를
            담은 PlateReadResult.

        실패:
            burst 계약 위반은 InvalidBurstError, 알려진 모델·adapter·
            OpenCV·내부 invariant 오류는 OcrRuntimeError가 발생한다.
            예상하지 못한 component 예외는 변환하지 않는다.

        YOLO가 한 anchor에서 정상적으로 빈 후보 tuple을 반환하거나
        geometry가 장면상 사용할 수 없는 프레임 좌표를 생략하면
        나머지로 계속한다.

        입력 ndarray는 복사하지 않고 읽기 전용으로 취급한다. 호출자는
        이 메서드가 끝날 때까지 원본 buffer를 변경하거나 재사용하면 안 된다.
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

        anchor_indices = self._select_anchors(frames)
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
        return self._decision_result(decision)

    # [단계별 실행]

    def _select_anchors(
        self,
        frames: tuple[CapturedFrame, ...],
    ) -> tuple[int, int]:
        """Anchor selector를 실행하고 detector 호출 인덱스를 확인한다."""

        selection = self._selector.select_anchors(frames)
        return self._validate_selection(selection)

    def _detect_anchors(
        self,
        frame_by_index: dict[int, CapturedFrame],
        anchor_indices: tuple[int, int],
    ) -> list[DetectedPlate]:
        """두 anchor를 탐지하고 1번 미검출 시 0번을 대신 사용한다."""

        earlier_frame_index, later_frame_index = anchor_indices
        earlier_candidates = self._detect_frame(
            frame_by_index,
            earlier_frame_index,
        )

        # 품질 점수로 1번을 골랐어도 번호판 검출에는 0번이 더 나을 수 있다.
        # 정상 미검출에만 fallback하며 모델 실행 오류는 기존대로 전파한다.
        if not earlier_candidates and earlier_frame_index == 1:
            earlier_candidates = self._detect_frame(
                frame_by_index,
                0,
            )

        # earlier anchor의 미검출과 무관하게 마지막 anchor도 실행해
        # single-anchor geometry fallback 가능성을 유지한다.
        later_candidates = self._detect_frame(
            frame_by_index,
            later_frame_index,
        )
        return [*earlier_candidates, *later_candidates]

    def _detect_frame(
        self,
        frame_by_index: dict[int, CapturedFrame],
        frame_index: int,
    ) -> tuple[DetectedPlate, ...]:
        """한 프레임의 후보를 탐지하고 반환 frame index를 검증한다."""

        candidates = self._detector.detect(
            frame_by_index[frame_index]
        )
        for candidate in candidates:
            self._validate_matching_frame_index(
                component="detector",
                actual=candidate.frame_index,
                expected=frame_index,
            )
        return candidates

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
            prepared = self._preprocessor.process(plate)
            self._validate_matching_frame_index(
                component="preprocessor",
                actual=prepared.frame_index,
                expected=plate.frame_index,
            )
            prepared_plates.append(prepared)

        return prepared_plates

    def _recognize(
        self,
        prepared_plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        """PaddleOCR batch를 실행하고 입력과 일대일인 결과를 반환한다."""

        raw_results = self._reader.recognize(prepared_plates)
        return self._align_raw_results(
            raw_results,
            prepared_plates,
        )

    def _build_candidates(
        self,
        raw_results: Sequence[RawOcrResult],
    ) -> list[OcrCandidate]:
        """원시 OCR 결과를 정규화된 번호판 후보로 변환한다."""

        candidates: list[OcrCandidate] = []

        for raw_result in raw_results:
            candidate = self._text_processor(raw_result)
            self._validate_matching_frame_index(
                component="text processor",
                actual=candidate.frame_index,
                expected=raw_result.frame_index,
            )
            candidates.append(candidate)
        return candidates

    def _aggregate(
        self,
        candidates: Sequence[OcrCandidate],
    ) -> PlateDecision:
        """후보를 최종 번호판 판정으로 집계한다."""

        return self._aggregator.aggregate(candidates)

    @staticmethod
    def _no_plate_region_result() -> PlateReadResult:
        """사용할 번호판 영역이 없는 정상 판독 결과를 만든다."""

        return PlateReadResult(
            status=ReadStatus.NO_PLATE_REGION,
            plate_number=None,
        )

    # [외부 입력과 단계 간 정렬 검증]

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
    ) -> tuple[int, int]:
        """Selector 결과가 detector 호출 정책을 만족하는지 확인한다."""

        anchor_indices = (
            selection.earlier_frame_index,
            selection.later_frame_index,
        )

        if any(
            isinstance(frame_index, bool)
            or not isinstance(frame_index, int)
            for frame_index in anchor_indices
        ):
            raise OcrRuntimeError(
                "selector anchor index는 bool이 아닌 정수여야 합니다."
            )

        if anchor_indices[0] not in range(
            self._policy.early_anchor_candidate_count
        ):
            raise OcrRuntimeError(
                "earlier anchor가 정책의 품질 비교 후보 범위를 "
                "벗어났습니다."
            )

        if anchor_indices[1] != self._policy.frame_count - 1:
            raise OcrRuntimeError(
                "later anchor는 burst의 마지막 프레임이어야 합니다."
            )

        return anchor_indices

    @staticmethod
    def _index_estimates(
        estimates: Sequence[EstimatedQuad],
        frame_by_index: dict[int, CapturedFrame],
    ) -> dict[int, EstimatedQuad]:
        """좌표 추정 결과의 중복과 입력 범위를 검사해 index mapping을 만든다."""

        estimate_by_index: dict[int, EstimatedQuad] = {}

        for estimate in estimates:
            frame_index = estimate.frame_index
            if (
                isinstance(frame_index, bool)
                or not isinstance(frame_index, int)
            ):
                raise OcrRuntimeError(
                    "geometry frame_index는 bool이 아닌 정수여야 합니다."
                )

            if frame_index not in frame_by_index:
                raise OcrRuntimeError(
                    "geometry가 입력에 없는 frame_index를 반환했습니다."
                )

            if frame_index in estimate_by_index:
                raise OcrRuntimeError(
                    "geometry 결과의 frame_index가 중복되었습니다."
                )

            estimate_by_index[frame_index] = estimate
        return estimate_by_index

    @staticmethod
    def _align_raw_results(
        raw_results: Sequence[RawOcrResult],
        prepared_plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        """PaddleOCR 결과가 입력 batch와 일대일 대응하는지 확인한다."""

        result_tuple = tuple(raw_results)
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
    ) -> PlateReadResult:
        """집계기의 판정을 상위 서비스용 최종 결과로 변환한다."""

        return PlateReadResult(
            status=decision.status,
            plate_number=decision.plate_number,
            rec_score=decision.winner_rec_score,
        )
