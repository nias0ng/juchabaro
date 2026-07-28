"""
촬영된 여섯 프레임을 전체 번호판 문자열로 변환하는 OCR 흐름을 조율한다.

파이프라인 위치:
    frame selection → YOLO → geometry → image preprocessing
    → PaddleOCR → text postprocessing → aggregation

이 모듈은 이미 로드된 모델 adapter를 전달받아 재사용한다. 센서 대기,
카메라 촬영, 촬영 시각 생성, 모델 다운로드와 Jetson 전송은 담당하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import logging
from threading import Lock
import time
from typing import Protocol

import numpy as np

from .postprocessing.plate_text import build_ocr_candidate
from .types import (
    AnchorSelection,
    CapturedFrame,
    DetectedPlate,
    EstimatedQuad,
    OcrCandidate,
    PipelineMetrics,
    PlateDecision,
    PlateReadResult,
    PreparedPlate,
    RawOcrResult,
    ReadStatus,
    RectifiedPlate,
    StageFailure,
)


LOGGER = logging.getLogger(__name__)


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


# [실행 정책]


@dataclass(frozen=True, slots=True)
class PipelinePolicy:
    """
    단일 차량 OCR 이벤트의 입력 및 모델 호출 정책.

    현재 카메라 계약은 시간순 여섯 프레임이며, 시간적으로 떨어진 두
    anchor에 YOLO를 정확히 한 번씩 실행한다. 운영 데이터가 바뀌면
    selector 정책과 함께 재검토해야 한다.
    """

    expected_frame_count: int = 6
    max_detector_calls: int = 2

    def __post_init__(self) -> None:
        if self.expected_frame_count != 6:
            raise ValueError(
                "현재 OCR 파이프라인은 프레임 6장을 전제로 합니다."
            )

        if self.max_detector_calls != 2:
            raise ValueError(
                "현재 anchor 선택 정책은 YOLO 호출 2회를 전제로 합니다."
            )


# [OCR 파이프라인]


class PlateOcrPipeline:
    """
    여섯 프레임에서 전체 번호판을 읽는 재사용 가능한 파이프라인.

    입력:
        촬영 시간순이며 frame_index가 0~5인 BGR uint8 프레임 여섯 장.

    출력:
        성공 여부, 전체 번호판, 프레임별 후보와 진단 정보를 포함한
        ``PlateReadResult``.

    실패:
        이벤트 안에서 복구 가능한 실패는 결과 상태와 ``failures``에 담는다.
        ``KeyboardInterrupt``와 ``SystemExit``은 가로채지 않는다.
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
        policy: PipelinePolicy | None = None,
    ) -> None:
        self._selector = selector
        self._detector = detector
        self._geometry = geometry
        self._preprocessor = preprocessor
        self._reader = reader
        self._aggregator = aggregator
        self._text_processor = text_processor
        self._policy = policy or PipelinePolicy()

        # 동일 모델 객체에 두 차량 이벤트가 섞여 들어가지 않게 한다.
        self._event_lock = Lock()

    def read_plate(
        self,
        frames: Sequence[CapturedFrame],
    ) -> PlateReadResult:
        """
        한 번의 차량 촬영 burst를 처리해 전체 번호판 판정을 반환한다.

        입력:
            촬영 시간순이며 frame_index가 0~5인 CapturedFrame 6장.

        출력:
            성공 번호, 실패 상태, 후보·단계별 진단·실행 지표를 담은
            PlateReadResult.

        실패:
            입력·모델·처리 오류는 가능한 범위에서 결과 상태로 격리한다.
            프로세스 종료를 위한 KeyboardInterrupt와 SystemExit은 전파한다.

        각 프레임의 기하·전처리 실패는 해당 프레임만 제외한다. YOLO anchor
        하나가 실패해도 나머지 anchor를 시도하며, PaddleOCR batch 자체가
        실패하면 ``MODEL_ERROR``로 반환한다.
        """

        with self._event_lock:
            started = time.perf_counter()

            try:
                frame_tuple = tuple(frames)
            except TypeError as exc:
                # 센서·카메라 경계의 잘못된 입력도 24시간 서비스 반복문을
                # 종료시키지 않도록 다른 입력 오류와 같은 결과로 격리한다.
                return self._failure_result(
                    status=ReadStatus.INVALID_INPUT,
                    message=(
                        "frames는 CapturedFrame 시퀀스여야 합니다: "
                        f"{exc}"
                    ),
                    total_frames=0,
                    candidates=(),
                    failures=(),
                    metrics=PipelineMetrics(),
                    started=started,
                )

            return self._read_plate_locked(frame_tuple)

    def _read_plate_locked(
        self,
        frames: tuple[CapturedFrame, ...],
    ) -> PlateReadResult:
        started = time.perf_counter()
        metrics = PipelineMetrics()
        failures: list[StageFailure] = []
        candidates: list[OcrCandidate] = []

        try:
            self._validate_frames(frames)
        except ValueError as exc:
            return self._failure_result(
                status=ReadStatus.INVALID_INPUT,
                message=str(exc),
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        try:
            return self._run_event(
                frames=frames,
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )
        except Exception as exc:
            # 프로세스 종료 신호는 Exception의 하위 타입이 아니므로 숨기지 않는다.
            LOGGER.exception(
                "번호판 OCR 이벤트의 예상하지 못한 오류를 격리했습니다."
            )
            failures.append(
                self._stage_failure(
                    "pipeline",
                    None,
                    exc,
                )
            )
            return self._failure_result(
                status=ReadStatus.INTERNAL_ERROR,
                message="번호판 OCR 파이프라인 내부 오류",
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

    def _run_event(
        self,
        *,
        frames: tuple[CapturedFrame, ...],
        candidates: list[OcrCandidate],
        failures: list[StageFailure],
        metrics: PipelineMetrics,
        started: float,
    ) -> PlateReadResult:
        frame_by_index = {
            frame.frame_index: frame
            for frame in frames
        }

        # [Anchor 선택]

        selection_started = time.perf_counter()

        try:
            selection = self._selector.select_anchors(frames)
            anchor_indices = self._validate_selection(
                selection,
                frame_by_index,
            )
        except ValueError as exc:
            metrics.frame_selection_ms = self._elapsed_ms(
                selection_started
            )
            failures.append(
                self._stage_failure(
                    "frame_selection",
                    None,
                    exc,
                )
            )
            return self._failure_result(
                status=ReadStatus.INVALID_INPUT,
                message=str(exc),
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        metrics.frame_selection_ms = self._elapsed_ms(
            selection_started
        )

        # [번호판 검출]

        detections: list[DetectedPlate] = []
        detector_errors = 0

        # 첫 anchor의 결과와 무관하게 두 번째도 실행해야 차량 이동량을
        # 추정할 가능성을 유지할 수 있다.
        for frame_index in anchor_indices:
            detection_started = time.perf_counter()
            metrics.detector_calls += 1

            try:
                detection = self._detector.detect(
                    frame_by_index[frame_index]
                )
            except Exception as exc:
                detector_errors += 1
                failures.append(
                    self._stage_failure(
                        "detection",
                        frame_index,
                        exc,
                    )
                )
                LOGGER.warning(
                    "frame_index=%s 번호판 검출 실패",
                    frame_index,
                    exc_info=True,
                )
            else:
                if detection is not None:
                    if detection.frame_index != frame_index:
                        raise ValueError(
                            "detector가 입력과 다른 frame_index를 "
                            "반환했습니다."
                        )
                    detections.append(detection)
            finally:
                metrics.detection_ms += self._elapsed_ms(
                    detection_started
                )

        if not detections:
            status = (
                ReadStatus.MODEL_ERROR
                if detector_errors
                else ReadStatus.NO_PLATE_REGION
            )
            message = (
                "YOLO 오류로 anchor에서 번호판을 얻지 못했습니다."
                if detector_errors
                else "두 anchor에서 번호판이 검출되지 않았습니다."
            )
            return self._failure_result(
                status=status,
                message=message,
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        # [좌표 추정과 원근 보정]

        geometry_started = time.perf_counter()

        try:
            estimates = self._geometry.estimate_quads(
                frames,
                detections,
            )
            estimate_by_index = self._index_estimates(
                estimates,
                frame_by_index,
            )
        except ValueError as exc:
            metrics.geometry_ms = self._elapsed_ms(
                geometry_started
            )
            failures.append(
                self._stage_failure(
                    "geometry",
                    None,
                    exc,
                )
            )
            return self._failure_result(
                status=ReadStatus.NO_PLATE_REGION,
                message=str(exc),
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        rectified_plates: list[RectifiedPlate] = []

        for frame in frames:
            estimate = estimate_by_index.get(frame.frame_index)

            if estimate is None:
                failures.append(
                    StageFailure(
                        stage="geometry",
                        frame_index=frame.frame_index,
                        message="사용 가능한 번호판 4점 좌표가 없습니다.",
                    )
                )
                continue

            try:
                rectified = self._geometry.rectify(
                    frame,
                    estimate,
                )
            except Exception as exc:
                failures.append(
                    self._stage_failure(
                        "rectification",
                        frame.frame_index,
                        exc,
                    )
                )
                LOGGER.warning(
                    "frame_index=%s 원근 보정 실패",
                    frame.frame_index,
                    exc_info=True,
                )
                continue

            if rectified.frame_index != frame.frame_index:
                raise ValueError(
                    "geometry가 입력과 다른 frame_index를 반환했습니다."
                )

            rectified_plates.append(rectified)

        metrics.geometry_ms = self._elapsed_ms(
            geometry_started
        )

        if not rectified_plates:
            return self._failure_result(
                status=ReadStatus.NO_PLATE_REGION,
                message="원근 보정 가능한 번호판 영역이 없습니다.",
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        # [OCR 화질 전처리]

        preprocessing_started = time.perf_counter()
        prepared_plates: list[PreparedPlate] = []

        for plate in rectified_plates:
            try:
                prepared = self._preprocessor.process(plate)
            except Exception as exc:
                failures.append(
                    self._stage_failure(
                        "preprocessing",
                        plate.frame_index,
                        exc,
                    )
                )
                LOGGER.warning(
                    "frame_index=%s OCR 전처리 실패",
                    plate.frame_index,
                    exc_info=True,
                )
                continue

            if prepared.frame_index != plate.frame_index:
                raise ValueError(
                    "preprocessor가 입력과 다른 frame_index를 반환했습니다."
                )

            prepared_plates.append(prepared)

        metrics.preprocessing_ms = self._elapsed_ms(
            preprocessing_started
        )

        if not prepared_plates:
            return self._failure_result(
                status=ReadStatus.INTERNAL_ERROR,
                message="OCR 전처리에 성공한 번호판 이미지가 없습니다.",
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        # [PaddleOCR 인식]

        recognition_started = time.perf_counter()
        metrics.recognizer_calls += 1

        try:
            raw_results = self._reader.recognize(
                prepared_plates
            )
        except Exception as exc:
            metrics.recognition_ms = self._elapsed_ms(
                recognition_started
            )
            failures.append(
                self._stage_failure(
                    "recognition",
                    None,
                    exc,
                )
            )
            LOGGER.warning(
                "PaddleOCR batch 인식 실패",
                exc_info=True,
            )
            return self._failure_result(
                status=ReadStatus.MODEL_ERROR,
                message="PaddleOCR batch 인식에 실패했습니다.",
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        metrics.recognition_ms = self._elapsed_ms(
            recognition_started
        )

        self._validate_raw_results(
            raw_results,
            prepared_plates,
        )

        # [문자열 후처리와 최종 집계]

        postprocessing_started = time.perf_counter()

        for raw_result in raw_results:
            try:
                candidate = self._text_processor(raw_result)
            except Exception as exc:
                failures.append(
                    self._stage_failure(
                        "text_postprocessing",
                        raw_result.frame_index,
                        exc,
                    )
                )
                LOGGER.warning(
                    "frame_index=%s OCR 문자열 후처리 실패",
                    raw_result.frame_index,
                    exc_info=True,
                )
                continue

            candidates.append(candidate)

        if not candidates:
            metrics.postprocessing_ms = self._elapsed_ms(
                postprocessing_started
            )
            return self._failure_result(
                status=ReadStatus.INTERNAL_ERROR,
                message="후처리 가능한 OCR 결과가 없습니다.",
                total_frames=len(frames),
                candidates=candidates,
                failures=failures,
                metrics=metrics,
                started=started,
            )

        try:
            decision = self._aggregator.aggregate(candidates)
        finally:
            # 집계 계약 오류도 INTERNAL_ERROR로 격리되므로 실패한 시간까지
            # 남겨야 운영 로그에서 지연 원인을 잃지 않는다.
            metrics.postprocessing_ms = self._elapsed_ms(
                postprocessing_started
            )

        return self._decision_result(
            decision=decision,
            total_frames=len(frames),
            candidates=candidates,
            failures=failures,
            metrics=metrics,
            started=started,
        )

    # [입력과 단계별 계약 검증]

    def _validate_frames(
        self,
        frames: Sequence[CapturedFrame],
    ) -> None:
        """여섯 프레임의 순서, dtype, shape와 해상도 계약을 확인한다."""

        expected_count = self._policy.expected_frame_count

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
                "frame_index는 촬영 시간순 0~5여야 합니다: "
                f"actual={actual_indices}"
            )

        image_shapes: set[tuple[int, ...]] = set()

        for frame in frames:
            image = frame.image

            if (
                not isinstance(image, np.ndarray)
                or image.dtype != np.uint8
                or image.ndim != 3
                or image.shape[2] != 3
                or image.shape[0] == 0
                or image.shape[1] == 0
            ):
                raise ValueError(
                    f"frame_index={frame.frame_index}: "
                    "BGR uint8 HxWx3 이미지가 필요합니다."
                )

            image_shapes.add(tuple(image.shape))

        # 동일 좌표 보간을 사용하므로 burst 안의 해상도는 같아야 한다.
        if len(image_shapes) != 1:
            raise ValueError(
                "한 burst의 여섯 프레임 해상도는 같아야 합니다."
            )

    def _validate_selection(
        self,
        selection: AnchorSelection,
        frame_by_index: dict[int, CapturedFrame],
    ) -> tuple[int, int]:
        """Selector 결과가 YOLO 호출 정책과 입력 범위를 만족하는지 확인한다."""

        anchor_indices = (
            selection.earlier_frame_index,
            selection.later_frame_index,
        )

        if len(set(anchor_indices)) != len(anchor_indices):
            raise ValueError(
                "두 anchor의 frame_index가 중복되었습니다."
            )

        if len(anchor_indices) > self._policy.max_detector_calls:
            raise ValueError(
                "Anchor 수가 YOLO 호출 제한을 초과했습니다."
            )

        if any(
            index not in frame_by_index
            for index in anchor_indices
        ):
            raise ValueError(
                "입력에 없는 frame_index가 anchor로 선택되었습니다."
            )

        if anchor_indices[0] >= anchor_indices[1]:
            raise ValueError(
                "earlier anchor는 later anchor보다 앞서야 합니다."
            )

        quality_indices = tuple(
            quality.frame_index
            for quality in selection.qualities
        )

        if quality_indices != tuple(frame_by_index):
            raise ValueError(
                "품질 평가 결과가 입력 프레임 순서와 다릅니다."
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
            if estimate.frame_index not in frame_by_index:
                raise ValueError(
                    "geometry가 입력에 없는 frame_index를 반환했습니다."
                )

            if estimate.frame_index in estimate_by_index:
                raise ValueError(
                    "geometry 결과의 frame_index가 중복되었습니다."
                )

            estimate_by_index[estimate.frame_index] = estimate

        if not estimate_by_index:
            raise ValueError(
                "사용 가능한 번호판 4점 좌표가 없습니다."
            )

        return estimate_by_index

    @staticmethod
    def _validate_raw_results(
        raw_results: Sequence[RawOcrResult],
        prepared_plates: Sequence[PreparedPlate],
    ) -> None:
        """PaddleOCR 결과가 입력 batch와 일대일 대응하는지 확인한다."""

        expected_indices = tuple(
            plate.frame_index
            for plate in prepared_plates
        )
        actual_indices = tuple(
            result.frame_index
            for result in raw_results
        )

        if actual_indices != expected_indices:
            raise ValueError(
                "PaddleOCR 결과 순서가 입력 batch와 다릅니다: "
                f"expected={expected_indices}, actual={actual_indices}"
            )

    # [최종 결과 생성]

    @staticmethod
    def _decision_result(
        *,
        decision: PlateDecision,
        total_frames: int,
        candidates: Sequence[OcrCandidate],
        failures: Sequence[StageFailure],
        metrics: PipelineMetrics,
        started: float,
    ) -> PlateReadResult:
        """집계기의 판정을 상위 서비스용 최종 결과로 변환한다."""

        metrics.total_ms = PlateOcrPipeline._elapsed_ms(
            started
        )

        return PlateReadResult(
            status=decision.status,
            plate_number=decision.plate_number,
            total_frames=total_frames,
            valid_frames=decision.valid_frames,
            vote_count=decision.vote_count,
            vote_ratio=decision.vote_ratio,
            mean_rec_score=decision.mean_rec_score,
            candidates=tuple(candidates),
            failures=tuple(failures),
            metrics=metrics,
            error_message=decision.error_message,
        )

    @staticmethod
    def _failure_result(
        *,
        status: ReadStatus,
        message: str,
        total_frames: int,
        candidates: Sequence[OcrCandidate],
        failures: Sequence[StageFailure],
        metrics: PipelineMetrics,
        started: float,
    ) -> PlateReadResult:
        """중간 단계 실패를 일관된 최종 결과로 변환한다."""

        metrics.total_ms = PlateOcrPipeline._elapsed_ms(
            started
        )

        return PlateReadResult(
            status=status,
            plate_number=None,
            total_frames=total_frames,
            valid_frames=0,
            vote_count=0,
            vote_ratio=0.0,
            mean_rec_score=0.0,
            candidates=tuple(candidates),
            failures=tuple(failures),
            metrics=metrics,
            error_message=message,
        )

    @staticmethod
    def _stage_failure(
        stage: str,
        frame_index: int | None,
        error: BaseException,
    ) -> StageFailure:
        """예외 타입과 메시지를 프레임별 진단 정보로 변환한다."""

        return StageFailure(
            stage=stage,
            frame_index=frame_index,
            message=f"{type(error).__name__}: {error}",
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        """``perf_counter`` 시작점부터 지난 시간을 밀리초로 반환한다."""

        return (time.perf_counter() - started) * 1000.0
