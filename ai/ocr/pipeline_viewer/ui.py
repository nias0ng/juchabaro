"""OCR 파이프라인 trace를 Streamlit의 이미지와 표로 표현한다.

렌더링 과정에서는 원본 NumPy 배열을 수정하지 않는다. 데이터 클래스의
원시 구조를 보여줄 때도 이미지는 복사·직렬화하지 않고 shape와 dtype 등
계약 확인에 필요한 메타데이터만 표시한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from numbers import Real
from pathlib import Path
from typing import Any, cast

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
from ocr.image_validation import is_nonempty_bgr_uint8_image
from ocr.types import PlateDecision


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


def _clipped_pixel(value: Real, upper_bound: int) -> int:
    """좌표를 유효한 이미지 pixel 범위로 제한한다."""

    coordinate = float(value)
    if not np.isfinite(coordinate):
        coordinate = 0.0
    return int(
        round(
            min(
                max(coordinate, 0.0),
                float(max(0, upper_bound - 1)),
            )
        )
    )


def draw_detection(image: np.ndarray, detection: Any | None) -> np.ndarray:
    """원본 복사본 위에 best 후보의 bbox와 네 keypoint를 그린다."""

    canvas = image.copy()
    if detection is None:
        return canvas

    image_height, image_width = canvas.shape[:2]

    x1, y1, x2, y2 = (
        _clipped_pixel(detection.bbox_xyxy[0], image_width),
        _clipped_pixel(detection.bbox_xyxy[1], image_height),
        _clipped_pixel(detection.bbox_xyxy[2], image_width),
        _clipped_pixel(detection.bbox_xyxy[3], image_height),
    )
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 220, 0), 2)

    points = np.asarray(
        tuple(
            (
                _clipped_pixel(point[0], image_width),
                _clipped_pixel(point[1], image_height),
            )
            for point in detection.quad
        ),
        dtype=np.int32,
    )
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
        f"best score={float(detection.detector_score):.3f}",
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
    image_height, image_width = canvas.shape[:2]
    points = np.asarray(
        tuple(
            (
                _clipped_pixel(point[0], image_width),
                _clipped_pixel(point[1], image_height),
            )
            for point in estimate.quad
        ),
        dtype=np.int32,
    )
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
    if call.error_chain:
        return " <- ".join(
            f"{error_type}: {message}"
            for error_type, message in call.error_chain
        )
    return f"{call.error_type}: {call.error_message}"


def _frame_name(run: DebugRun, frame_index: int) -> str:
    if 0 <= frame_index < len(run.file_names):
        return run.file_names[frame_index]
    return "-"


def _bgr_image(value: Any) -> np.ndarray | None:
    """Trace 객체에서 표시 가능한 이미지만 꺼낸다."""

    image = getattr(value, "image", None)
    return image if is_nonempty_bgr_uint8_image(image) else None


def _aggregation_decision(
    trace: PipelineTrace,
) -> PlateDecision | None:
    """성공한 집계 호출의 판정을 반환한다."""

    call = trace.first("aggregation")
    if (
        call is None
        or not call.succeeded
        or call.output is None
    ):
        return None
    return cast(PlateDecision, call.output)


def _normal_result_message(run: DebugRun) -> str:
    """최소 공개 결과에 없는 판독 실패 사유를 trace에서 요약한다."""

    decision = _aggregation_decision(run.trace)
    if decision is not None:
        if decision.error_message:
            return decision.error_message

    detection_calls = run.trace.calls_for("detection")
    if detection_calls and all(
        call.succeeded and call.output == ()
        for call in detection_calls
    ):
        return "선택된 anchor에서 번호판이 검출되지 않았습니다."

    geometry_call = run.trace.first("geometry")
    if geometry_call is not None:
        if not geometry_call.succeeded:
            return _call_error(geometry_call) or "좌표 추정에 실패했습니다."
        if geometry_call.output == ():
            return "사용 가능한 번호판 좌표가 없습니다."
        if geometry_call.output is None:
            return "Geometry 출력이 기록되지 않았습니다."

    rectification_calls = run.trace.calls_for("rectification")
    if rectification_calls and not any(
        call.succeeded and call.output is not None
        for call in rectification_calls
    ):
        return "원근 보정 가능한 번호판 영역이 없습니다."

    return "번호판을 확정하지 못했습니다."


def _trace_failure_rows(run: DebugRun) -> list[dict[str, Any]]:
    """실패한 component와 pipeline 호출을 요약한다."""

    rows: list[dict[str, Any]] = []

    for call in run.trace.calls:
        if call.succeeded:
            continue
        frames = ", ".join(
            f"F{frame_index + 1}"
            for frame_index in call.frame_indices
        )
        rows.append(
            {
                "stage": call.stage,
                "frame": frames or "-",
                "message": _call_error(call),
            }
        )

    pipeline_call = run.trace.pipeline_call
    if (
        pipeline_call is not None
        and not pipeline_call.succeeded
        and not any(
            (
                not call.succeeded
                and call.error_type == pipeline_call.error_type
                and call.error_message == pipeline_call.error_message
            )
            for call in run.trace.calls
        )
    ):
        rows.append(
            {
                "stage": "pipeline",
                "frame": "-",
                "message": _call_error(pipeline_call),
            }
        )

    return rows


def _trace_metric_rows(trace: PipelineTrace) -> list[dict[str, Any]]:
    """함수 trace를 기존 pipeline 단계 단위의 timing으로 묶는다."""

    pipeline_call = trace.pipeline_call
    return [
        {
            "stage": "frame_selection",
            "elapsed_ms": trace.elapsed_ms_for("frame_selection"),
        },
        {
            "stage": "detection",
            "elapsed_ms": trace.elapsed_ms_for("detection"),
        },
        {
            "stage": "geometry",
            "elapsed_ms": trace.elapsed_ms_for(
                "geometry",
                "rectification",
            ),
        },
        {
            "stage": "preprocessing",
            "elapsed_ms": trace.elapsed_ms_for("preprocessing"),
        },
        {
            "stage": "recognition",
            "elapsed_ms": trace.elapsed_ms_for("recognition"),
        },
        {
            "stage": "postprocessing",
            "elapsed_ms": trace.elapsed_ms_for(
                "text_postprocessing",
                "aggregation",
            ),
        },
        {
            "stage": "total",
            "elapsed_ms": (
                pipeline_call.elapsed_ms
                if pipeline_call is not None
                else 0.0
            ),
        },
    ]


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
    pipeline_call = run.trace.pipeline_call
    decision = _aggregation_decision(run.trace)

    if result is None:
        status = "EXECUTION_ERROR"
        plate_number = None
        message = (
            _call_error(pipeline_call)
            if pipeline_call is not None
            else "Pipeline 실행 결과가 기록되지 않았습니다."
        )
        st.error(f"{status}: {message}")
    else:
        status = _enum_value(result.status)
        plate_number = result.plate_number
        if result.succeeded:
            st.success(f"최종 번호판: {plate_number}")
        else:
            st.warning(f"{status}: {_normal_result_message(run)}")

    valid_frames = (
        decision.valid_frames
        if decision is not None
        else None
    )
    vote_count = (
        decision.vote_count
        if decision is not None
        else None
    )
    vote_ratio = (
        decision.vote_ratio
        if decision is not None
        else None
    )
    total_ms = (
        pipeline_call.elapsed_ms
        if pipeline_call is not None
        else None
    )

    columns = st.columns(6)
    columns[0].metric("Status", status)
    columns[1].metric("Plate", plate_number or "-")
    columns[2].metric(
        "Valid frames",
        valid_frames if valid_frames is not None else "-",
    )
    columns[3].metric(
        "Votes",
        vote_count if vote_count is not None else "-",
    )
    columns[4].metric(
        "Vote ratio",
        f"{float(vote_ratio):.3f}" if vote_ratio is not None else "-",
    )
    columns[5].metric(
        "Total",
        f"{total_ms:.1f} ms" if total_ms is not None else "-",
    )

    st.markdown("#### 단계 실패")
    failure_rows = _trace_failure_rows(run)
    if failure_rows:
        st.dataframe(
            failure_rows,
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("기록된 단계 실패가 없습니다.")


def _render_frame_selection(run: DebugRun) -> None:
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
        selection.earlier_frame_index,
        selection.later_frame_index,
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


def _render_detection(run: DebugRun) -> None:
    calls = run.trace.calls_for("detection")
    if not calls:
        st.info("YOLO detector가 호출되지 않았습니다.")
        return

    rows: list[dict[str, Any]] = []
    columns = st.columns(min(2, len(calls)))
    for column, call in zip(columns, calls, strict=True):
        frame = call.inputs
        candidates = (
            call.output
            if call.succeeded and call.output is not None
            else ()
        )
        candidate_count = (
            len(candidates)
            if call.succeeded and call.output is not None
            else None
        )
        best_candidate = candidates[0] if candidates else None

        with column:
            frame_image = _bgr_image(frame)
            if frame_image is not None:
                st.image(
                    draw_detection(frame_image, best_candidate),
                    channels="BGR",
                    use_container_width=True,
                )
            else:
                st.error("표시할 anchor 이미지가 없습니다.")
                st.json(summarize_value(frame))
            if not call.succeeded:
                st.error(_call_error(call))
                state = "ERROR"
            elif call.output is None:
                st.warning("Detector 출력이 기록되지 않았습니다.")
                state = "NO_OUTPUT"
            elif not candidates:
                st.warning("번호판 미검출")
                state = "NO_DETECTION"
            else:
                st.success(
                    f"후보 {candidate_count}개 · "
                    f"best score="
                    f"{float(best_candidate.detector_score):.4f}"
                )
                state = "DETECTED"
            st.caption(
                f"F{frame.frame_index + 1} · "
                f"{_frame_name(run, frame.frame_index)}"
            )

        if candidates:
            for rank, candidate in enumerate(candidates, start=1):
                rows.append(
                    {
                        "frame": f"F{frame.frame_index + 1}",
                        "output_state": state,
                        "candidate": (
                            "BEST"
                            if rank == 1
                            else f"#{rank}"
                        ),
                        "score": round(
                            float(candidate.detector_score),
                            4,
                        ),
                        "bbox_xyxy": tuple(
                            round(float(value), 2)
                            for value in candidate.bbox_xyxy
                        ),
                        "quad": tuple(
                            tuple(round(float(value), 2) for value in point)
                            for point in candidate.quad
                        ),
                        "candidate_count": candidate_count,
                        "elapsed_ms": round(call.elapsed_ms, 3),
                    }
                )
        else:
            rows.append(
                {
                    "frame": f"F{frame.frame_index + 1}",
                    "output_state": state,
                    "candidate": None,
                    "score": None,
                    "bbox_xyxy": None,
                    "quad": None,
                    "candidate_count": candidate_count,
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

    estimates = estimate_call.output
    if estimates is None:
        st.warning("Geometry 출력이 기록되지 않았습니다.")
        return

    estimate_by_index = {
        estimate.frame_index: estimate
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
                frame.frame_index in rectification_by_index
                and rectification_by_index[
                    frame.frame_index
                ].succeeded
                and _bgr_image(
                    rectification_by_index[frame.frame_index].output
                )
                is not None
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
                scene_image = _bgr_image(frame)
                if scene_image is not None:
                    st.image(
                        draw_estimate(scene_image, estimate),
                        channels="BGR",
                        use_container_width=True,
                        caption=(
                            _enum_value(estimate.source)
                            if estimate is not None
                            else "좌표 없음"
                        ),
                    )
                else:
                    st.error("표시할 원본 이미지가 없습니다.")
                    st.json(summarize_value(frame))
                if rectify_call is None:
                    st.caption("원근 보정 미호출")
                elif not rectify_call.succeeded:
                    st.error(_call_error(rectify_call))
                elif rectify_call.output is None:
                    st.warning("원근 보정 출력이 기록되지 않았습니다.")
                elif (
                    rectified_image := _bgr_image(rectify_call.output)
                ) is not None:
                    rectified = rectify_call.output
                    st.image(
                        rectified_image,
                        channels="BGR",
                        use_container_width=True,
                        caption=(
                            "Rectified "
                            f"{rectified_image.shape[1]}×"
                            f"{rectified_image.shape[0]}"
                        ),
                    )
                else:
                    st.error("원근 보정 이미지를 표시할 수 없습니다.")
                    st.json(summarize_value(rectify_call.output))


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
            rectified_image = _bgr_image(rectified)
            if rectified_image is None:
                message = "원근 보정 입력 이미지를 표시할 수 없습니다."
                columns[0].error(message)
                columns[0].json(summarize_value(rectified))
                rows.append(
                    {
                        "frame": f"F{frame_index + 1}",
                        "input_shape": None,
                        "output_shape": None,
                        "applied": None,
                        "elapsed_ms": round(call.elapsed_ms, 3),
                        "error": message,
                    }
                )
                continue

            columns[0].image(
                rectified_image,
                channels="BGR",
                use_container_width=True,
                caption=(
                    "Rectified input · "
                    f"{rectified_image.shape[1]}×{rectified_image.shape[0]}"
                ),
            )

            prepared_image = (
                _bgr_image(call.output)
                if call.succeeded and call.output is not None
                else None
            )
            if call.succeeded and prepared_image is not None:
                prepared = call.output
                columns[1].image(
                    prepared_image,
                    channels="BGR",
                    use_container_width=True,
                    caption=(
                        "Prepared output · "
                        f"{prepared_image.shape[1]}×{prepared_image.shape[0]}"
                    ),
                )
                rows.append(
                    {
                        "frame": f"F{frame_index + 1}",
                        "input_shape": tuple(rectified_image.shape),
                        "output_shape": tuple(prepared_image.shape),
                        "applied": prepared.preprocessing_applied,
                        "elapsed_ms": round(call.elapsed_ms, 3),
                        "error": "",
                    }
                )
            elif call.succeeded and call.output is not None:
                message = "전처리 출력 이미지를 표시할 수 없습니다."
                columns[1].error(message)
                columns[1].json(summarize_value(call.output))
                rows.append(
                    {
                        "frame": f"F{frame_index + 1}",
                        "input_shape": tuple(rectified_image.shape),
                        "output_shape": None,
                        "applied": None,
                        "elapsed_ms": round(call.elapsed_ms, 3),
                        "error": message,
                    }
                )
            else:
                columns[1].error(_call_error(call) or "전처리 출력 없음")
                rows.append(
                    {
                        "frame": f"F{frame_index + 1}",
                        "input_shape": tuple(rectified_image.shape),
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

    prepared_plates = recognition.inputs
    if prepared_plates is None:
        st.warning("Recognition 입력이 기록되지 않았습니다.")
        return
    raw_results = recognition.output
    if raw_results is None:
        st.warning("Recognition 출력이 기록되지 않았습니다.")
        return

    raw_by_index = {
        result.frame_index: result
        for result in raw_results
    }
    text_calls = run.trace.calls_for("text_postprocessing")
    candidate_by_index = {
        call.frame_indices[0]: call.output
        for call in text_calls
        if call.succeeded and call.output is not None
    }

    result_rows: list[dict[str, Any]] = []
    for plate in prepared_plates:
        frame_index = plate.frame_index
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
                    if (
                        text_call is not None
                        and not text_call.succeeded
                    )
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
    elif aggregation.output is None:
        st.warning("집계 출력이 기록되지 않았습니다.")
    else:
        st.json(summarize_value(aggregation.output))


def _render_diagnostics(run: DebugRun) -> None:
    metric_rows = _trace_metric_rows(run.trace)
    st.markdown("#### Trace 기반 실행 시간")
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
        f"detector_calls={len(run.trace.calls_for('detection'))}, "
        f"recognizer_calls={len(run.trace.calls_for('recognition'))}"
    )

    pipeline_call = run.trace.pipeline_call
    st.markdown("#### Pipeline 경계")
    if pipeline_call is None:
        st.info("전체 pipeline 호출 기록이 없습니다.")
    else:
        with st.expander(
            (
                "전체 입력·결과 "
                f"· {pipeline_call.elapsed_ms:.3f} ms"
            ),
            expanded=not pipeline_call.succeeded,
        ):
            if not pipeline_call.succeeded:
                st.error(_call_error(pipeline_call))
            left, right = st.columns(2)
            with left:
                st.caption("Input")
                st.json(summarize_value(pipeline_call.inputs))
            with right:
                st.caption("Output")
                st.json(summarize_value(pipeline_call.output))

    st.markdown("#### 실제 함수 호출")
    if not run.trace.calls:
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
        _render_frame_selection(run)
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
