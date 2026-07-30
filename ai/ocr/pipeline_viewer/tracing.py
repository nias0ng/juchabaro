"""운영 OCR 컴포넌트의 동작을 바꾸지 않고 단계별 호출을 기록한다.

각 wrapper는 입력 시퀀스를 tuple로 얕게 고정하고, 출력·실행 시간·예외를
``PipelineTrace``에 남긴다. 모델 결과를 검증하거나 변환하는 책임은 원래
파이프라인에 있으며, 이 모듈은 예외를 기록한 뒤 그대로 다시 발생시킨다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import time
from typing import Any, TypeVar


_ResultT = TypeVar("_ResultT")


@dataclass(frozen=True, slots=True)
class StageCall:
    """한 단계 호출의 결과와 root→cause 순 예외 요약."""

    stage: str
    frame_indices: tuple[int, ...]
    inputs: Any
    output: Any | None
    elapsed_ms: float
    error_type: str | None = None
    error_message: str | None = None
    error_chain: tuple[tuple[str, str], ...] = ()

    @property
    def succeeded(self) -> bool:
        """호출 자체가 예외 없이 끝났는지 반환한다."""

        return self.error_type is None


@dataclass(slots=True)
class PipelineTrace:
    """단일 burst 이벤트의 전체 실행과 내부 호출을 보관한다.

    ``pipeline_call``은 내부 component 호출 목록과 별도로 둔다. 전체
    pipeline 호출은 component들을 감싸므로 완료 시점에 기록되는데, 이를
    ``calls``에 넣으면 목록의 실행 순서 의미가 깨지기 때문이다.
    """

    calls: list[StageCall] = field(default_factory=list)
    pipeline_call: StageCall | None = None

    def calls_for(self, stage: str) -> tuple[StageCall, ...]:
        """지정한 단계의 호출만 원래 실행 순서로 반환한다."""

        return tuple(call for call in self.calls if call.stage == stage)

    def first(self, stage: str) -> StageCall | None:
        """지정한 단계의 첫 호출을 반환하고 없으면 ``None``을 반환한다."""

        return next(
            (call for call in self.calls if call.stage == stage),
            None,
        )

    def successful_outputs(self, stage: str) -> tuple[Any, ...]:
        """지정한 단계에서 예외 없이 반환된 non-None 출력만 반환한다."""

        return tuple(
            call.output
            for call in self.calls
            if (
                call.stage == stage
                and call.succeeded
                and call.output is not None
            )
        )

    def elapsed_ms_for(self, *stages: str) -> float:
        """지정한 단계들의 관찰된 함수 실행 시간을 합산한다."""

        stage_set = set(stages)
        return sum(
            call.elapsed_ms
            for call in self.calls
            if call.stage in stage_set
        )


def _frame_indices(values: Sequence[Any]) -> tuple[int, ...]:
    """frame_index를 가진 전달 객체들의 인덱스를 tuple로 추출한다."""

    return tuple(int(value.frame_index) for value in values)


def _exception_chain(
    error: BaseException,
) -> tuple[tuple[str, str], ...]:
    """Traceback 순서대로 예외와 명시적·암시적 원인을 안전하게 요약한다."""

    summaries: list[tuple[str, str]] = []
    seen: set[int] = set()
    current: BaseException | None = error

    while current is not None and id(current) not in seen:
        seen.add(id(current))
        summaries.append((type(current).__name__, str(current)))
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None

    return tuple(summaries)


def _run_traced(
    *,
    trace: PipelineTrace,
    stage: str,
    frame_indices: tuple[int, ...],
    inputs: Any,
    operation: Callable[[], _ResultT],
) -> _ResultT:
    """호출을 측정하고 성공 또는 실패 기록을 하나 남긴다."""

    started = time.perf_counter()

    try:
        output = operation()
    except Exception as exc:
        trace.calls.append(
            StageCall(
                stage=stage,
                frame_indices=frame_indices,
                inputs=inputs,
                output=None,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                error_type=type(exc).__name__,
                error_message=str(exc),
                error_chain=_exception_chain(exc),
            )
        )
        raise

    trace.calls.append(
        StageCall(
            stage=stage,
            frame_indices=frame_indices,
            inputs=inputs,
            output=output,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )
    )
    return output


def run_traced_pipeline(
    *,
    trace: PipelineTrace,
    frames: Sequence[Any],
    operation: Callable[[], _ResultT],
) -> _ResultT:
    """전체 pipeline 호출의 결과·시간·예외를 별도 root call에 기록한다.

    내부 component wrapper와 마찬가지로 예외를 기록한 뒤 그대로 다시
    발생시킨다. Viewer service가 이 예외를 실행 결과와 함께 보존한다.
    """

    frame_tuple = tuple(frames)
    started = time.perf_counter()

    try:
        output = operation()
    except Exception as exc:
        trace.pipeline_call = StageCall(
            stage="pipeline",
            frame_indices=_frame_indices(frame_tuple),
            inputs=frame_tuple,
            output=None,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            error_type=type(exc).__name__,
            error_message=str(exc),
            error_chain=_exception_chain(exc),
        )
        raise

    trace.pipeline_call = StageCall(
        stage="pipeline",
        frame_indices=_frame_indices(frame_tuple),
        inputs=frame_tuple,
        output=output,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )
    return output


class TracedFrameSelector:
    """Frame selector의 입출력을 기록하는 투명 wrapper."""

    def __init__(self, target: Any, trace: PipelineTrace) -> None:
        self._target = target
        self._trace = trace

    def select_anchors(self, frames: Sequence[Any]) -> Any:
        frame_tuple = tuple(frames)
        return _run_traced(
            trace=self._trace,
            stage="frame_selection",
            frame_indices=_frame_indices(frame_tuple),
            inputs=frame_tuple,
            operation=lambda: self._target.select_anchors(frame_tuple),
        )


class TracedPlateDetector:
    """번호판 detector의 anchor별 best-first 후보 batch를 한 호출로 기록한다."""

    def __init__(self, target: Any, trace: PipelineTrace) -> None:
        self._target = target
        self._trace = trace

    def detect(self, frame: Any) -> Any:
        return _run_traced(
            trace=self._trace,
            stage="detection",
            frame_indices=(int(frame.frame_index),),
            inputs=frame,
            operation=lambda: self._target.detect(frame),
        )


class TracedPlateGeometry:
    """좌표 추정과 원근 보정 호출을 각각 기록하는 투명 wrapper."""

    def __init__(self, target: Any, trace: PipelineTrace) -> None:
        self._target = target
        self._trace = trace

    def estimate_quads(
        self,
        frames: Sequence[Any],
        detections: Sequence[Any],
    ) -> Any:
        frame_tuple = tuple(frames)
        detection_tuple = tuple(detections)
        return _run_traced(
            trace=self._trace,
            stage="geometry",
            frame_indices=_frame_indices(frame_tuple),
            inputs={
                "frames": frame_tuple,
                "detections": detection_tuple,
            },
            operation=lambda: self._target.estimate_quads(
                frame_tuple,
                detection_tuple,
            ),
        )

    def rectify(self, frame: Any, estimate: Any) -> Any:
        return _run_traced(
            trace=self._trace,
            stage="rectification",
            frame_indices=(int(frame.frame_index),),
            inputs={
                "frame": frame,
                "estimate": estimate,
            },
            operation=lambda: self._target.rectify(frame, estimate),
        )


class TracedPlatePreprocessor:
    """번호판 전처리 호출을 프레임별로 기록하는 투명 wrapper."""

    def __init__(self, target: Any, trace: PipelineTrace) -> None:
        self._target = target
        self._trace = trace

    def process(self, plate: Any) -> Any:
        return _run_traced(
            trace=self._trace,
            stage="preprocessing",
            frame_indices=(int(plate.frame_index),),
            inputs=plate,
            operation=lambda: self._target.process(plate),
        )


class TracedPlateReader:
    """PaddleOCR batch 인식 호출을 기록하는 투명 wrapper."""

    def __init__(self, target: Any, trace: PipelineTrace) -> None:
        self._target = target
        self._trace = trace

    def recognize(self, plates: Sequence[Any]) -> Any:
        plate_tuple = tuple(plates)
        return _run_traced(
            trace=self._trace,
            stage="recognition",
            frame_indices=_frame_indices(plate_tuple),
            inputs=plate_tuple,
            operation=lambda: self._target.recognize(plate_tuple),
        )


class TracedTextProcessor:
    """OCR 문자열 후처리 callable의 호출을 기록한다."""

    def __init__(
        self,
        target: Callable[[Any], Any],
        trace: PipelineTrace,
    ) -> None:
        self._target = target
        self._trace = trace

    def __call__(self, result: Any) -> Any:
        return _run_traced(
            trace=self._trace,
            stage="text_postprocessing",
            frame_indices=(int(result.frame_index),),
            inputs=result,
            operation=lambda: self._target(result),
        )


class TracedPlateAggregator:
    """최종 후보 집계 호출을 기록하는 투명 wrapper."""

    def __init__(self, target: Any, trace: PipelineTrace) -> None:
        self._target = target
        self._trace = trace

    def aggregate(self, candidates: Sequence[Any]) -> Any:
        candidate_tuple = tuple(candidates)
        return _run_traced(
            trace=self._trace,
            stage="aggregation",
            frame_indices=_frame_indices(candidate_tuple),
            inputs=candidate_tuple,
            operation=lambda: self._target.aggregate(candidate_tuple),
        )
