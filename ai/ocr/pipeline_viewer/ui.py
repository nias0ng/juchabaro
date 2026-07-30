"""OCR 파이프라인 trace를 Streamlit의 이미지와 표로 표현한다.

렌더링 과정에서는 원본 NumPy 배열을 수정하지 않는다. 데이터 클래스의
원시 구조를 보여줄 때도 이미지는 복사·직렬화하지 않고 shape와 dtype 등
계약 확인에 필요한 메타데이터만 표시한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import streamlit as st

from .service import (
    DebugRun,
    DebugRuntime,
    DecodedBurst,
    ModelPaths,
)
from .tracing import PipelineTrace, StageCall


_STAGE_LABELS = {
    "frame_selection": "Frame selection",
    "detection": "YOLO detection",
    "geometry": "Geometry estimation",
    "rectification": "Perspective rectification",
    "preprocessing": "OCR preprocessing",
    "recognition": "PaddleOCR recognition",
    "text_postprocessing": "Text postprocessing",
    "aggregation": "Candidate aggregation",
}

_QUAD_COLORS = {
    "DETECTED": (0, 200, 0),
    "INTERPOLATED": (255, 200, 0),
    "EXTRAPOLATED": (0, 140, 255),
    "REUSED": (255, 0, 200),
}


# [공통 표시 helper]


def _enum_value(value: Any) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


def _image_metadata(image: np.ndarray) -> dict[str, Any]:
    """대용량 배열 복사 없이 이미지의 전달 계약만 요약한다."""

    return {
        "type": "numpy.ndarray",
        "shape": list(image.shape),
        "dtype": str(image.dtype),
        "contiguous": bool(image.flags.c_contiguous),
    }


def summarize_value(value: Any, *, depth: int = 0) -> Any:
    """Streamlit JSON에 안전한 형태로 파이프라인 전달값을 요약한다."""

    if depth >= 8:
        return f"<{type(value).__name__}>"
    if isinstance(value, np.ndarray):
        return _image_metadata(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: summarize_value(
                getattr(value, item.name),
                depth=depth + 1,
            )
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): summarize_value(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [
            summarize_value(item, depth=depth + 1)
            for item in value
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _put_label(
    image: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    """OpenCV로 읽을 수 있는 짧은 ASCII 진단 label을 그린다."""

    x, y = origin
    cv2.putText(
        image,
        text,
        (max(0, x), max(18, y)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
        cv2.LINE_AA,
    )


def draw_detection(image: np.ndarray, detection: Any | None) -> np.ndarray:
    """원본 복사본 위에 detector bbox와 TL→TR→BR→BL quad를 그린다."""

    canvas = image.copy()
    if detection is None:
        return canvas

    x1, y1, x2, y2 = (
        int(round(float(value)))
        for value in detection.bbox_xyxy
    )
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 220, 0), 2)

    points = np.rint(
        np.asarray(detection.quad, dtype=np.float32)
    ).astype(np.int32)
    cv2.polylines(
        canvas,
        [points.reshape((-1, 1, 2))],
        True,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )

    point_colors = (
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 0, 255),
    )
    for index, (point, color) in enumerate(
        zip(points, point_colors, strict=True)
    ):
        px, py = int(point[0]), int(point[1])
        cv2.circle(canvas, (px, py), 5, color, -1, cv2.LINE_AA)
        _put_label(canvas, str(index + 1), (px + 5, py - 5), color)

    _put_label(
        canvas,
        f"score={float(detection.detector_score):.3f}",
        (x1, y1 - 8),
        (0, 220, 0),
    )
    return canvas


def draw_estimate(image: np.ndarray, estimate: Any | None) -> np.ndarray:
    """원본 복사본 위에 geometry가 적용한 quad와 출처를 그린다."""

    canvas = image.copy()
    if estimate is None:
        return canvas

    source = _enum_value(estimate.source)
    color = _QUAD_COLORS.get(source, (0, 255, 255))
    points = np.rint(
        np.asarray(estimate.quad, dtype=np.float32)
    ).astype(np.int32)
    cv2.polylines(
        canvas,
        [points.reshape((-1, 1, 2))],
        True,
        color,
        3,
        cv2.LINE_AA,
    )
    anchors = ",".join(
        f"F{int(index) + 1}"
        for index in estimate.source_anchor_indices
    )
    _put_label(
        canvas,
        f"{source} ({anchors})",
        (int(points[0][0]), int(points[0][1]) - 8),
        color,
    )
    return canvas


def _call_error(call: StageCall) -> str | None:
    if call.succeeded:
        return None
    return f"{call.error_type}: {call.error_message}"


def _frame_name(run: DebugRun, frame_index: int) -> str:
    if 0 <= frame_index < len(run.file_names):
        return run.file_names[frame_index]
    return "-"


# [모델 준비와 입력]


def render_model_paths(paths: ModelPaths) -> None:
    """현재 앱이 검사하는 모델 경로를 표시한다."""

    with st.expander("모델 파일 위치", expanded=False):
        st.code(
            "\n".join(
                (
                    f"root: {paths.root}",
                    f"YOLO: {paths.detector}",
                    f"PaddleOCR: {paths.recognizer}",
                )
            ),
            language="text",
        )


def render_runtime_ready(runtime: DebugRuntime) -> None:
    """모델 로드와 warm-up 결과를 상단 상태 카드로 표시한다."""

    st.success(
        "모델 준비 완료 — YOLO와 PaddleOCR dummy warm-up을 "
        "각각 한 번 실행했습니다."
    )
    report = runtime.startup
    columns = st.columns(5)
    columns[0].metric("YOLO load", f"{report.detector_load_ms:.1f} ms")
    columns[1].metric(
        "YOLO warm-up",
        f"{report.detector_warm_up_ms:.1f} ms",
    )
    columns[2].metric(
        "Paddle load",
        f"{report.recognizer_load_ms:.1f} ms",
    )
    columns[3].metric(
        "Paddle warm-up",
        f"{report.recognizer_warm_up_ms:.1f} ms",
    )
    columns[4].metric("Startup total", f"{report.total_ms:.1f} ms")


def render_burst_preview(burst: DecodedBurst) -> None:
    """실제 파이프라인에 전달할 파일 순서와 이미지 정보를 보여준다."""

    st.subheader("입력 순서")
    st.caption(
        "파일명을 자연 정렬한 뒤 "
        f"F1~F{len(burst.frames)}을 부여합니다. "
        "이 순서가 실제 촬영 시간순인지 실행 전에 확인하세요."
    )

    for row_start in range(0, len(burst.frames), 3):
        columns = st.columns(3)
        for column, frame in zip(
            columns,
            burst.frames[row_start : row_start + 3],
            strict=False,
        ):
            with column:
                st.image(
                    frame.image,
                    channels="BGR",
                    use_container_width=True,
                )
                height, width = frame.image.shape[:2]
                st.caption(
                    f"F{frame.frame_index + 1} · {frame.file_name} · "
                    f"{width}×{height} · {frame.byte_size:,} bytes"
                )


# [파이프라인 결과 탭]


def _render_summary(run: DebugRun) -> None:
    result = run.result
    status = _enum_value(result.status)

    if result.succeeded:
        st.success(f"최종 번호판: {result.plate_number}")
    elif status in {"MODEL_ERROR", "INTERNAL_ERROR"}:
        st.error(f"{status}: {result.error_message or '처리 실패'}")
    else:
        st.warning(f"{status}: {result.error_message or '판정되지 않음'}")

    columns = st.columns(6)
    columns[0].metric("Status", status)
    columns[1].metric("Plate", result.plate_number or "-")
    columns[2].metric("Valid frames", result.valid_frames)
    columns[3].metric("Votes", result.vote_count)
    columns[4].metric("Vote ratio", f"{result.vote_ratio:.3f}")
    columns[5].metric("Total", f"{result.metrics.total_ms:.1f} ms")

    st.markdown("#### 후보")
    candidate_rows = [
        {
            "frame": f"F{candidate.frame_index + 1}",
            "file": _frame_name(run, candidate.frame_index),
            "raw_text": candidate.raw_text,
            "normalized_text": candidate.normalized_text,
            "rec_score": round(float(candidate.rec_score), 4),
            "valid_format": candidate.valid_format,
        }
        for candidate in result.candidates
    ]
    if candidate_rows:
        st.dataframe(
            candidate_rows,
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("생성된 OCR 후보가 없습니다.")

    st.markdown("#### 단계 실패")
    failure_rows = [
        {
            "stage": failure.stage,
            "frame": (
                f"F{failure.frame_index + 1}"
                if failure.frame_index is not None
                else "-"
            ),
            "message": failure.message,
        }
        for failure in result.failures
    ]
    if failure_rows:
        st.dataframe(
            failure_rows,
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("기록된 단계 실패가 없습니다.")


def _render_frame_selection(run: DebugRun, burst: DecodedBurst) -> None:
    call = run.trace.first("frame_selection")
    if call is None:
        st.info("입력 검증 단계에서 종료되어 frame selector가 호출되지 않았습니다.")
        return
    if not call.succeeded:
        st.error(_call_error(call))
        return

    selection = call.output
    if selection is None:
        st.warning("Frame selector 출력이 없습니다.")
        return

    anchor_indices = {
        int(selection.earlier_frame_index),
        int(selection.later_frame_index),
    }
    quality_rows = [
        {
            "frame": f"F{quality.frame_index + 1}",
            "file": _frame_name(run, quality.frame_index),
            "anchor": quality.frame_index in anchor_indices,
            "sharpness": round(float(quality.sharpness), 3),
            "contrast": round(float(quality.contrast), 3),
            "mean_brightness": round(float(quality.mean_brightness), 3),
            "dark_ratio": round(float(quality.dark_ratio), 4),
            "bright_ratio": round(float(quality.bright_ratio), 4),
            "score": round(float(quality.score), 4),
        }
        for quality in selection.qualities
    ]
    st.dataframe(
        quality_rows,
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        f"선택된 anchor: F{selection.earlier_frame_index + 1}, "
        f"F{selection.later_frame_index + 1}"
    )

    for row_start in range(0, len(burst.frames), 3):
        columns = st.columns(3)
        for column, frame in zip(
            columns,
            burst.frames[row_start : row_start + 3],
            strict=False,
        ):
            with column:
                st.image(
                    frame.image,
                    channels="BGR",
                    use_container_width=True,
                )
                marker = (
                    " · ANCHOR"
                    if frame.frame_index in anchor_indices
                    else ""
                )
                st.caption(
                    f"F{frame.frame_index + 1}{marker} · {frame.file_name}"
                )


def _render_detection(run: DebugRun) -> None:
    calls = run.trace.calls_for("detection")
    if not calls:
        st.info("YOLO detector가 호출되지 않았습니다.")
        return

    rows: list[dict[str, Any]] = []
    columns = st.columns(min(2, len(calls)))
    for column, call in zip(columns, calls, strict=True):
        frame = call.inputs
        detection = call.output if call.succeeded else None
        with column:
            st.image(
                draw_detection(frame.image, detection),
                channels="BGR",
                use_container_width=True,
            )
            if not call.succeeded:
                st.error(_call_error(call))
                state = "ERROR"
            elif detection is None:
                st.warning("번호판 미검출")
                state = "NO_DETECTION"
            else:
                st.success(
                    f"score={float(detection.detector_score):.4f}"
                )
                state = "DETECTED"
            st.caption(
                f"F{frame.frame_index + 1} · "
                f"{_frame_name(run, frame.frame_index)}"
            )

        rows.append(
            {
                "frame": f"F{frame.frame_index + 1}",
                "state": state,
                "score": (
                    round(float(detection.detector_score), 4)
                    if detection is not None
                    else None
                ),
                "bbox_xyxy": (
                    tuple(round(float(value), 2) for value in detection.bbox_xyxy)
                    if detection is not None
                    else None
                ),
                "elapsed_ms": round(call.elapsed_ms, 3),
            }
        )

    st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_geometry(run: DebugRun, burst: DecodedBurst) -> None:
    estimate_call = run.trace.first("geometry")
    if estimate_call is None:
        st.info("Geometry 좌표 추정이 호출되지 않았습니다.")
        return
    if not estimate_call.succeeded:
        st.error(_call_error(estimate_call))
        return

    estimates = tuple(estimate_call.output or ())
    estimate_by_index = {
        int(estimate.frame_index): estimate
        for estimate in estimates
    }
    rectification_calls = run.trace.calls_for("rectification")
    rectification_by_index = {
        call.frame_indices[0]: call
        for call in rectification_calls
        if call.frame_indices
    }

    rows = [
        {
            "frame": f"F{frame.frame_index + 1}",
            "file": frame.file_name,
            "source": (
                _enum_value(estimate_by_index[frame.frame_index].source)
                if frame.frame_index in estimate_by_index
                else "NO_ESTIMATE"
            ),
            "source_anchors": (
                tuple(
                    f"F{index + 1}"
                    for index in estimate_by_index[
                        frame.frame_index
                    ].source_anchor_indices
                )
                if frame.frame_index in estimate_by_index
                else ()
            ),
            "rectified": (
                rectification_by_index.get(frame.frame_index) is not None
                and rectification_by_index[frame.frame_index].succeeded
            ),
        }
        for frame in burst.frames
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)

    for row_start in range(0, len(burst.frames), 3):
        columns = st.columns(3)
        for column, frame in zip(
            columns,
            burst.frames[row_start : row_start + 3],
            strict=False,
        ):
            estimate = estimate_by_index.get(frame.frame_index)
            rectify_call = rectification_by_index.get(frame.frame_index)
            with column:
                st.markdown(
                    f"**F{frame.frame_index + 1} · {frame.file_name}**"
                )
                st.image(
                    draw_estimate(frame.image, estimate),
                    channels="BGR",
                    use_container_width=True,
                    caption=(
                        _enum_value(estimate.source)
                        if estimate is not None
                        else "좌표 없음"
                    ),
                )
                if rectify_call is None:
                    st.caption("원근 보정 미호출")
                elif not rectify_call.succeeded:
                    st.error(_call_error(rectify_call))
                elif rectify_call.output is not None:
                    rectified = rectify_call.output
                    st.image(
                        rectified.image,
                        channels="BGR",
                        use_container_width=True,
                        caption=(
                            "Rectified "
                            f"{rectified.image.shape[1]}×"
                            f"{rectified.image.shape[0]}"
                        ),
                    )


def _render_preprocessing(run: DebugRun) -> None:
    calls = run.trace.calls_for("preprocessing")
    if not calls:
        st.info("OCR 전처리가 호출되지 않았습니다.")
        return

    rows: list[dict[str, Any]] = []
    for call in calls:
        frame_index = call.frame_indices[0]
        with st.expander(
            f"F{frame_index + 1} · {_frame_name(run, frame_index)}",
            expanded=frame_index == calls[0].frame_indices[0],
        ):
            columns = st.columns(2)
            rectified = call.inputs
            columns[0].image(
                rectified.image,
                channels="BGR",
                use_container_width=True,
                caption=(
                    "Rectified input · "
                    f"{rectified.image.shape[1]}×{rectified.image.shape[0]}"
                ),
            )

            if call.succeeded and call.output is not None:
                prepared = call.output
                columns[1].image(
                    prepared.image,
                    channels="BGR",
                    use_container_width=True,
                    caption=(
                        "Prepared output · "
                        f"{prepared.image.shape[1]}×{prepared.image.shape[0]}"
                    ),
                )
                rows.append(
                    {
                        "frame": f"F{frame_index + 1}",
                        "input_shape": tuple(rectified.image.shape),
                        "output_shape": tuple(prepared.image.shape),
                        "applied": prepared.preprocessing_applied,
                        "elapsed_ms": round(call.elapsed_ms, 3),
                        "error": "",
                    }
                )
            else:
                columns[1].error(_call_error(call) or "전처리 출력 없음")
                rows.append(
                    {
                        "frame": f"F{frame_index + 1}",
                        "input_shape": tuple(rectified.image.shape),
                        "output_shape": None,
                        "applied": None,
                        "elapsed_ms": round(call.elapsed_ms, 3),
                        "error": _call_error(call),
                    }
                )

    st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_ocr_and_aggregation(run: DebugRun) -> None:
    recognition = run.trace.first("recognition")
    if recognition is None:
        st.info("PaddleOCR recognition이 호출되지 않았습니다.")
        return
    if not recognition.succeeded:
        st.error(_call_error(recognition))
        return

    prepared_plates = tuple(recognition.inputs)
    raw_results = tuple(recognition.output or ())
    raw_by_index = {
        int(result.frame_index): result
        for result in raw_results
    }
    text_calls = run.trace.calls_for("text_postprocessing")
    candidate_by_index = {
        call.frame_indices[0]: call.output
        for call in text_calls
        if call.succeeded and call.output is not None
    }

    for row_start in range(0, len(prepared_plates), 3):
        columns = st.columns(3)
        for column, plate in zip(
            columns,
            prepared_plates[row_start : row_start + 3],
            strict=False,
        ):
            raw = raw_by_index.get(plate.frame_index)
            with column:
                st.image(
                    plate.image,
                    channels="BGR",
                    use_container_width=True,
                )
                st.caption(
                    f"F{plate.frame_index + 1} · "
                    f"raw={raw.raw_text!r}, "
                    f"score={float(raw.rec_score):.4f}"
                    if raw is not None
                    else f"F{plate.frame_index + 1} · 결과 없음"
                )

    result_rows: list[dict[str, Any]] = []
    for plate in prepared_plates:
        frame_index = int(plate.frame_index)
        raw = raw_by_index.get(frame_index)
        candidate = candidate_by_index.get(frame_index)
        text_call = next(
            (
                call
                for call in text_calls
                if call.frame_indices == (frame_index,)
            ),
            None,
        )
        result_rows.append(
            {
                "frame": f"F{frame_index + 1}",
                "file": _frame_name(run, frame_index),
                "raw_text": raw.raw_text if raw is not None else None,
                "rec_score": (
                    round(float(raw.rec_score), 4)
                    if raw is not None
                    else None
                ),
                "normalized_text": (
                    candidate.normalized_text
                    if candidate is not None
                    else None
                ),
                "valid_format": (
                    candidate.valid_format
                    if candidate is not None
                    else None
                ),
                "postprocess_error": (
                    _call_error(text_call)
                    if text_call is not None
                    else None
                ),
            }
        )
    st.dataframe(
        result_rows,
        hide_index=True,
        use_container_width=True,
    )

    aggregation = run.trace.first("aggregation")
    st.markdown("#### 최종 집계")
    if aggregation is None:
        st.info("집계기가 호출되지 않았습니다.")
    elif not aggregation.succeeded:
        st.error(_call_error(aggregation))
    else:
        st.json(summarize_value(aggregation.output))


def _render_diagnostics(run: DebugRun) -> None:
    metrics = run.result.metrics
    metric_rows = [
        {"stage": "frame_selection", "elapsed_ms": metrics.frame_selection_ms},
        {"stage": "detection", "elapsed_ms": metrics.detection_ms},
        {"stage": "geometry", "elapsed_ms": metrics.geometry_ms},
        {"stage": "preprocessing", "elapsed_ms": metrics.preprocessing_ms},
        {"stage": "recognition", "elapsed_ms": metrics.recognition_ms},
        {"stage": "postprocessing", "elapsed_ms": metrics.postprocessing_ms},
        {"stage": "total", "elapsed_ms": metrics.total_ms},
    ]
    st.markdown("#### 파이프라인 metrics")
    st.dataframe(
        [
            {
                **row,
                "elapsed_ms": round(float(row["elapsed_ms"]), 3),
            }
            for row in metric_rows
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        f"detector_calls={metrics.detector_calls}, "
        f"recognizer_calls={metrics.recognizer_calls}"
    )

    st.markdown("#### 실제 함수 호출")
    call_rows = [
        {
            "order": index + 1,
            "stage": _STAGE_LABELS.get(call.stage, call.stage),
            "frames": ", ".join(
                f"F{frame_index + 1}"
                for frame_index in call.frame_indices
            ),
            "state": "OK" if call.succeeded else "ERROR",
            "elapsed_ms": round(call.elapsed_ms, 3),
            "error": _call_error(call) or "",
        }
        for index, call in enumerate(run.trace.calls)
    ]
    if call_rows:
        st.dataframe(
            call_rows,
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("기록된 함수 호출이 없습니다.")

    for index, call in enumerate(run.trace.calls):
        label = _STAGE_LABELS.get(call.stage, call.stage)
        frames = ", ".join(
            f"F{frame_index + 1}"
            for frame_index in call.frame_indices
        ) or "-"
        with st.expander(
            f"{index + 1}. {label} · {frames} · {call.elapsed_ms:.3f} ms"
        ):
            if not call.succeeded:
                st.error(_call_error(call))
            left, right = st.columns(2)
            with left:
                st.caption("Input")
                st.json(summarize_value(call.inputs))
            with right:
                st.caption("Output")
                st.json(summarize_value(call.output))


def render_debug_run(run: DebugRun, burst: DecodedBurst) -> None:
    """단일 디버그 실행을 단계별 탭으로 렌더링한다."""

    st.divider()
    st.header("파이프라인 실행 결과")

    tabs = st.tabs(
        (
            "최종 결과",
            "Frame selection",
            "YOLO detection",
            "Geometry",
            "Preprocessing",
            "OCR & aggregation",
            "Metrics & I/O",
        )
    )
    with tabs[0]:
        _render_summary(run)
    with tabs[1]:
        _render_frame_selection(run, burst)
    with tabs[2]:
        _render_detection(run)
    with tabs[3]:
        _render_geometry(run, burst)
    with tabs[4]:
        _render_preprocessing(run)
    with tabs[5]:
        _render_ocr_and_aggregation(run)
    with tabs[6]:
        _render_diagnostics(run)
