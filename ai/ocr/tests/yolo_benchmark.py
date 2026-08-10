"""
학습한 YOLOv8 pose 번호판 검출 모델이 잘 동작하는지
버전별로 테스트해보고 비교해 보기 위해 구현했습니다.

# 환경 생성 (Miniforge 터미널)
conda create -n plate-yolo-bench python=3.13 -y
conda activate plate-yolo-bench

# 사용 방법
1. 이 파일과 같은 ``tests`` 디렉터리에 테스트할 ``.pt`` 파일을 둡니다.
2. 아래 ``MODEL_FILES``의 파일명만 직접 수정합니다.
3. ai/ocr/ 디렉터리에서 실행합니다.

   streamlit run tests/yolo_benchmark.py

모델 파일은 업로드하지 않습니다.
모델 1은 항상 사용하고, 화면의 체크박스로 모델 2와 모델 3을 추가할 수 있습니다.
입력은 원본 사진만 받으며, 다운로드는 검출된 4점으로 크롭과 원근 보정을 함께 수행한 PNG 사진만 제공합니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import io
import math
from pathlib import Path
import time
from typing import Any, cast

import cv2
import numpy as np
import streamlit as st
from PIL import Image, ImageOps


# ---------------------------------------------------------------------------
# 사용자가 주로 수정할 설정
# ---------------------------------------------------------------------------

# 상대 경로는 이 파일이 있는 ai/ocr/tests 디렉터리를 기준으로 해석합니다.
# 필요하면 r"C:\models\best.pt"처럼 절대 경로를 적어도 됩니다.
MODEL_FILES = (
    "bestv1_1.pt",
    "candidate_2.pt",
    "candidate_3.pt",
)

MODEL_LABELS = (
    "모델 1",
    "모델 2",
    "모델 3",
)

MAX_DETECTIONS = 20


Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]
Box = tuple[float, float, float, float]


class GeometryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GeometryConfig:
    min_area_px: float = 64.0
    min_edge_px: float = 4.0
    bounds_tolerance_px: float = 2.0


@dataclass(frozen=True, slots=True)
class ModelSpec:
    index: int
    label: str
    path: Path


@dataclass(slots=True)
class PlateDetection:
    detection_index: int
    confidence: float
    box: Box
    raw_quad: Quad
    rectification_quad: Quad
    keypoint_order_valid: bool
    rectified: np.ndarray
    rectify_ms: float


@dataclass(slots=True)
class ModelResult:
    spec: ModelSpec
    load_ms: float
    inference_ms: float
    annotated: np.ndarray | None
    detections: tuple[PlateDetection, ...]
    detection_errors: tuple[str, ...]
    error: str | None = None


@dataclass(slots=True)
class ImageResult:
    upload_index: int
    file_name: str
    original: np.ndarray
    model_results: tuple[ModelResult, ...]


def resolve_model_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path.resolve()


def configured_models() -> tuple[ModelSpec, ...]:
    if len(MODEL_FILES) != 3 or len(MODEL_LABELS) != 3:
        raise RuntimeError(
            "MODEL_FILES와 MODEL_LABELS에는 각각 정확히 3개 항목이 필요합니다."
        )

    return tuple(
        ModelSpec(
            index=index,
            label=MODEL_LABELS[index],
            path=resolve_model_path(MODEL_FILES[index]),
        )
        for index in range(3)
    )


def _cross(first: Point, second: Point, third: Point) -> float:
    return (
        (second[0] - first[0]) * (third[1] - second[1])
        - (second[1] - first[1]) * (third[0] - second[0])
    )


def convert_quad_points(points: Sequence[Sequence[float]]) -> Quad:
    """모델이 출력한 K1~K4 순서를 보존하면서 좌표를 변환합니다."""
    if len(points) != 4:
        raise GeometryError("번호판 꼭짓점은 정확히 4개여야 합니다.")

    converted: list[Point] = []
    for point in points:
        if len(point) != 2:
            raise GeometryError("각 꼭짓점은 (x, y)여야 합니다.")

        x = float(point[0])
        y = float(point[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise GeometryError("꼭짓점 좌표는 유한해야 합니다.")
        converted.append((x, y))

    return cast(Quad, tuple(converted))


def order_quad_points(points: Sequence[Sequence[float]]) -> Quad:
    """네 점을 좌상→우상→우하→좌하 순서로 정렬합니다."""

    converted = convert_quad_points(points)
    center_x = sum(x for x, _ in converted) / 4.0
    center_y = sum(y for _, y in converted) / 4.0
    cyclic = sorted(
        converted,
        key=lambda point: math.atan2(
            point[1] - center_y,
            point[0] - center_x,
        ),
    )

    top_left_position = min(
        range(4),
        key=lambda index: cyclic[index][0] + cyclic[index][1],
    )
    ordered = cast(
        Quad,
        tuple(
            cyclic[(top_left_position + offset) % 4]
            for offset in range(4)
        ),
    )

    crosses = tuple(
        _cross(
            ordered[index],
            ordered[(index + 1) % 4],
            ordered[(index + 2) % 4],
        )
        for index in range(4)
    )
    if any(abs(value) <= 1e-6 for value in crosses):
        raise GeometryError("중복되거나 일직선인 꼭짓점이 있습니다.")
    if not (
        all(value > 0.0 for value in crosses)
        or all(value < 0.0 for value in crosses)
    ):
        raise GeometryError("4점이 볼록 사각형을 만들지 않습니다.")

    return ordered


def quad_area(quad: Quad) -> float:
    return abs(
        sum(
            quad[index][0] * quad[(index + 1) % 4][1]
            - quad[(index + 1) % 4][0] * quad[index][1]
            for index in range(4)
        )
    ) / 2.0


def quad_dimensions(quad: Quad) -> tuple[float, float]:
    top_left, top_right, bottom_right, bottom_left = quad
    width = max(
        math.dist(top_left, top_right),
        math.dist(bottom_left, bottom_right),
    )
    height = max(
        math.dist(top_left, bottom_left),
        math.dist(top_right, bottom_right),
    )
    return width, height


def validate_quad(
    points: Sequence[Sequence[float]],
    image_shape: Sequence[int],
    config: GeometryConfig | None = None,
) -> Quad:
    """유효한 사각형을 원근 보정용 공간 순서로 반환합니다."""

    _, ordered = prepare_quad(points, image_shape, config)
    return ordered


def prepare_quad(
    points: Sequence[Sequence[float]],
    image_shape: Sequence[int],
    config: GeometryConfig | None = None,
) -> tuple[Quad, Quad]:
    """raw K1~K4와 원근 보정용 정렬 사각형을 함께 반환합니다."""

    config = config or GeometryConfig()
    raw = convert_quad_points(points)

    if len(image_shape) < 2:
        raise GeometryError("이미지 크기를 확인할 수 없습니다.")

    height = int(image_shape[0])
    width = int(image_shape[1])
    if height < 2 or width < 2:
        raise GeometryError("이미지가 너무 작습니다.")

    tolerance = config.bounds_tolerance_px
    for x, y in raw:
        if (
            x < -tolerance
            or x > width - 1 + tolerance
            or y < -tolerance
            or y > height - 1 + tolerance
        ):
            raise GeometryError("4점 좌표가 이미지 범위를 벗어났습니다.")

    clipped_raw = cast(
        Quad,
        tuple(
            (
                min(max(x, 0.0), float(width - 1)),
                min(max(y, 0.0), float(height - 1)),
            )
            for x, y in raw
        ),
    )
    ordered = order_quad_points(clipped_raw)
    if quad_area(ordered) < config.min_area_px:
        raise GeometryError("번호판 영역 면적이 너무 작습니다.")

    plate_width, plate_height = quad_dimensions(ordered)
    if min(plate_width, plate_height) < config.min_edge_px:
        raise GeometryError("번호판 영역의 변이 너무 짧습니다.")

    return clipped_raw, ordered


def is_expected_keypoint_order(
    raw_quad: Quad,
    ordered_quad: Quad,
    tolerance_px: float = 1e-3,
) -> bool:
    """raw K1~K4가 좌상→우상→우하→좌하 계약과 일치하는지 확인합니다."""

    return all(
        math.dist(raw_point, ordered_point) <= tolerance_px
        for raw_point, ordered_point in zip(
            raw_quad,
            ordered_quad,
            strict=True,
        )
    )


def rectify_plate(image: np.ndarray, quad: Quad) -> np.ndarray:
    """4점 내부를 크롭하면서 직사각형으로 원근 보정합니다."""

    validated = validate_quad(quad, image.shape)
    target_width, target_height = quad_dimensions(validated)
    output_width = max(2, round(target_width))
    output_height = max(2, round(target_height))

    source = np.asarray(validated, dtype=np.float32)
    destination = np.asarray(
        (
            (0.0, 0.0),
            (float(output_width - 1), 0.0),
            (float(output_width - 1), float(output_height - 1)),
            (0.0, float(output_height - 1)),
        ),
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(source, destination)
    rectified = cv2.warpPerspective(
        image,
        transform,
        (output_width, output_height),
        flags=cv2.INTER_LINEAR,
    )
    if rectified.size == 0:
        raise GeometryError("원근 보정 결과가 비어 있습니다.")

    return rectified


def crop_plate_box(image: np.ndarray, box: Box) -> np.ndarray:
    """원근 보정 없이 YOLO bbox 영역을 이미지 경계 안에서 자릅니다."""

    if len(image.shape) < 2:
        raise GeometryError("이미지 크기를 확인할 수 없습니다.")

    image_height, image_width = image.shape[:2]
    x1, y1, x2, y2 = box
    if not all(math.isfinite(value) for value in box):
        raise GeometryError("bbox 좌표는 유한해야 합니다.")

    left = max(0, min(image_width, math.floor(min(x1, x2))))
    top = max(0, min(image_height, math.floor(min(y1, y2))))
    right = max(0, min(image_width, math.ceil(max(x1, x2))))
    bottom = max(0, min(image_height, math.ceil(max(y1, y2))))
    if right <= left or bottom <= top:
        raise GeometryError("이미지 안에 자를 수 있는 bbox 영역이 없습니다.")

    return image[top:bottom, left:right].copy()


def decode_photo(file_bytes: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(file_bytes)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        rgb = np.asarray(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def encode_png(image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("PNG 이미지 인코딩에 실패했습니다.")
    return encoded.tobytes()


def _tensor_to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    return np.asarray(value)


@st.cache_resource(show_spinner=False)
def load_pose_model(
    model_path: str,
    model_mtime_ns: int,
) -> tuple[Any, float]:
    # mtime도 캐시 키에 포함하여 같은 이름의 파일을 교체했을 때 다시 로드합니다.
    _ = model_mtime_ns
    from ultralytics import YOLO

    started = time.perf_counter()
    model = YOLO(model_path)
    load_ms = (time.perf_counter() - started) * 1000
    return model, load_ms


def draw_detections(
    image: np.ndarray,
    detections: Sequence[PlateDetection],
) -> np.ndarray:
    annotated = image.copy()
    keypoint_names = (
        "K1 TL",
        "K2 TR",
        "K3 BR",
        "K4 BL",
    )
    point_colors = (
        (0, 0, 255),
        (0, 165, 255),
        (0, 255, 255),
        (255, 0, 255),
    )

    for detection in detections:
        x1, y1, x2, y2 = detection.box
        cv2.rectangle(
            annotated,
            (round(x1), round(y1)),
            (round(x2), round(y2)),
            (0, 255, 0),
            2,
        )

        raw_polygon = np.asarray(
            detection.raw_quad,
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        cv2.polylines(
            annotated,
            [raw_polygon],
            isClosed=True,
            color=(160, 160, 160),
            thickness=1,
        )

        rectification_polygon = np.asarray(
            detection.rectification_quad,
            dtype=np.int32,
        ).reshape((-1, 1, 2))
        cv2.polylines(
            annotated,
            [rectification_polygon],
            isClosed=True,
            color=(255, 255, 0),
            thickness=2,
        )
        for point_index, (x, y) in enumerate(detection.raw_quad):
            center = (round(x), round(y))
            cv2.circle(
                annotated,
                center,
                radius=5,
                color=point_colors[point_index],
                thickness=-1,
            )
            cv2.putText(
                annotated,
                keypoint_names[point_index],
                (center[0] + 6, center[1] - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                point_colors[point_index],
                2,
                cv2.LINE_AA,
            )

        cv2.putText(
            annotated,
            f"#{detection.detection_index} {detection.confidence:.3f}",
            (round(x1), max(18, round(y1) - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    return annotated


def run_inference(
    spec: ModelSpec,
    model: Any,
    load_ms: float,
    image: np.ndarray,
    confidence_threshold: float,
    image_size: int,
    device: str,
    use_perspective_rectification: bool,
) -> ModelResult:
    started = time.perf_counter()
    try:
        predict_options: dict[str, Any] = {
            "source": image,
            "conf": confidence_threshold,
            "imgsz": image_size,
            "max_det": MAX_DETECTIONS,
            "verbose": False,
        }
        if device:
            predict_options["device"] = device

        raw_results = model.predict(**predict_options)
        inference_ms = (time.perf_counter() - started) * 1000

        if not raw_results:
            return ModelResult(
                spec=spec,
                load_ms=load_ms,
                inference_ms=inference_ms,
                annotated=image.copy(),
                detections=(),
                detection_errors=(),
            )

        result = raw_results[0]
        boxes = getattr(result, "boxes", None)
        keypoints = getattr(result, "keypoints", None)
        if boxes is None or keypoints is None:
            raise RuntimeError(
                "pose 결과에 boxes 또는 keypoints가 없습니다. "
                "4-keypoint pose 모델인지 확인하세요."
            )

        boxes_xyxy = _tensor_to_numpy(boxes.xyxy)
        box_confidences = _tensor_to_numpy(boxes.conf)
        keypoints_xy = _tensor_to_numpy(keypoints.xy)

        if keypoints_xy.ndim != 3 or keypoints_xy.shape[1:] != (4, 2):
            raise RuntimeError(
                "예상 keypoint shape은 (N, 4, 2)이지만 "
                f"실제 shape은 {keypoints_xy.shape}입니다."
            )
        if not (
            len(boxes_xyxy)
            == len(box_confidences)
            == len(keypoints_xy)
        ):
            raise RuntimeError(
                "bbox, confidence, keypoint 검출 개수가 서로 다릅니다."
            )

        detections: list[PlateDetection] = []
        detection_errors: list[str] = []
        for raw_index in range(len(keypoints_xy)):
            detection_index = raw_index + 1
            try:
                raw_quad, rectification_quad = prepare_quad(
                    keypoints_xy[raw_index].tolist(),
                    image.shape,
                )
                keypoint_order_valid = is_expected_keypoint_order(
                    raw_quad,
                    rectification_quad,
                )
                box = cast(
                    Box,
                    tuple(float(value) for value in boxes_xyxy[raw_index]),
                )
                rectify_started = time.perf_counter()
                if use_perspective_rectification:
                    rectified = rectify_plate(
                        image,
                        rectification_quad,
                    )
                else:
                    rectified = crop_plate_box(image, box)
                rectify_ms = (time.perf_counter() - rectify_started) * 1000
                detections.append(
                    PlateDetection(
                        detection_index=detection_index,
                        confidence=float(box_confidences[raw_index]),
                        box=box,
                        raw_quad=raw_quad,
                        rectification_quad=rectification_quad,
                        keypoint_order_valid=keypoint_order_valid,
                        rectified=rectified,
                        rectify_ms=rectify_ms,
                    )
                )
            except Exception as exc:
                detection_errors.append(
                    f"검출 #{detection_index}: "
                    f"{type(exc).__name__}: {exc}"
                )

        return ModelResult(
            spec=spec,
            load_ms=load_ms,
            inference_ms=inference_ms,
            annotated=draw_detections(image, detections),
            detections=tuple(detections),
            detection_errors=tuple(detection_errors),
        )
    except Exception as exc:
        inference_ms = (time.perf_counter() - started) * 1000
        return ModelResult(
            spec=spec,
            load_ms=load_ms,
            inference_ms=inference_ms,
            annotated=None,
            detections=(),
            detection_errors=(),
            error=f"{type(exc).__name__}: {exc}",
        )


def safe_stem(file_name: str) -> str:
    raw_stem = Path(file_name).stem
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in raw_stem
    ).strip("_")
    return cleaned or "photo"


def request_signature(
    uploads: Sequence[tuple[str, bytes]],
    active_models: Sequence[ModelSpec],
    confidence_threshold: float,
    image_size: int,
    device: str,
    use_perspective_rectification: bool,
) -> str:
    digest = hashlib.sha256()
    for file_name, file_bytes in uploads:
        digest.update(file_name.encode("utf-8", errors="replace"))
        digest.update(file_bytes)
    for spec in active_models:
        digest.update(str(spec.path).encode("utf-8", errors="replace"))
        if spec.path.is_file():
            digest.update(str(spec.path.stat().st_mtime_ns).encode("ascii"))
    digest.update(str(confidence_threshold).encode("ascii"))
    digest.update(str(image_size).encode("ascii"))
    digest.update(device.encode("utf-8", errors="replace"))
    digest.update(str(use_perspective_rectification).encode("ascii"))
    return digest.hexdigest()


def render_image_result(
    image_result: ImageResult,
    use_perspective_rectification: bool,
) -> None:
    st.subheader(
        f"{image_result.upload_index + 1}. {image_result.file_name}"
    )
    st.image(
        image_result.original,
        caption=(
            f"업로드 원본 · "
            f"{image_result.original.shape[1]}×"
            f"{image_result.original.shape[0]}"
        ),
        channels="BGR",
        use_container_width=True,
    )

    columns = st.columns(len(image_result.model_results))
    for column, model_result in zip(
        columns,
        image_result.model_results,
        strict=True,
    ):
        with column:
            st.markdown(f"#### {model_result.spec.label}")
            st.caption(model_result.spec.path.name)

            if model_result.error:
                st.error(model_result.error)
                continue

            if model_result.annotated is not None:
                st.image(
                    model_result.annotated,
                    caption=(
                        f"4점 검출 결과 · "
                        f"{len(model_result.detections)}개"
                    ),
                    channels="BGR",
                    use_container_width=True,
                )

            st.caption(
                f"최초 실제 로드 {model_result.load_ms:.1f} ms · "
                f"추론 {model_result.inference_ms:.1f} ms"
            )
            if use_perspective_rectification:
                st.caption(
                    "색상 점은 모델의 raw K1~K4, "
                    "하늘색 외곽선은 펼치기에 사용한 정렬 사각형입니다."
                )
            else:
                st.caption(
                    "원근 보정 없이 초록색 YOLO bbox 영역을 잘랐습니다."
                )

            if model_result.detection_errors:
                with st.expander(
                    f"사용하지 못한 검출 "
                    f"{len(model_result.detection_errors)}개"
                ):
                    for error in model_result.detection_errors:
                        st.warning(error)

            if not model_result.detections:
                st.info("유효한 4점 검출 결과가 없습니다.")
                continue

            for detection in model_result.detections:
                height, width = detection.rectified.shape[:2]
                if (
                    use_perspective_rectification
                    and not detection.keypoint_order_valid
                ):
                    st.warning(
                        f"검출 #{detection.detection_index}: "
                        "raw keypoint 순서가 "
                        "K1(TL)→K2(TR)→K3(BR)→K4(BL) "
                        "계약과 다릅니다. 펼치기에는 공간 순서로 "
                        "정렬한 4점을 사용했습니다."
                    )
                st.image(
                    detection.rectified,
                    caption=(
                        f"검출 #{detection.detection_index} "
                        f"{'펼친 사진' if use_perspective_rectification else 'bbox crop'} "
                        "· "
                        f"confidence {detection.confidence:.3f} · "
                        f"{width}×{height} · "
                        f"{'보정' if use_perspective_rectification else '자르기'} "
                        f"{detection.rectify_ms:.1f} ms"
                    ),
                    channels="BGR",
                    use_container_width=True,
                )

                download_name = (
                    f"{safe_stem(image_result.file_name)}"
                    f"__model{model_result.spec.index + 1}"
                    f"__detection{detection.detection_index:02d}.png"
                )
                st.download_button(
                    label=f"검출 #{detection.detection_index} PNG 다운로드",
                    data=encode_png(detection.rectified),
                    file_name=download_name,
                    mime="image/png",
                    key=(
                        f"download_"
                        f"{image_result.upload_index}_"
                        f"{model_result.spec.index}_"
                        f"{detection.detection_index}"
                    ),
                    use_container_width=True,
                )

    st.divider()


def main() -> None:
    st.set_page_config(
        page_title="YOLO Pose 번호판 모델 테스트",
        layout="wide",
    )
    st.title("YOLOv8 Pose 번호판 모델 테스트")
    st.caption(
        "원본 사진에서 번호판의 4점을 검출하고, "
        "원근 보정 또는 YOLO bbox crop 결과를 비교합니다."
    )

    try:
        model_specs = configured_models()
    except Exception as exc:
        st.error(f"모델 설정 오류: {exc}")
        return

    with st.sidebar:
        st.header("비교 모델")
        use_second = st.checkbox("모델 2와 비교", value=False)
        use_third = st.checkbox("모델 3과 비교", value=False)

        active_indices = [0]
        if use_second:
            active_indices.append(1)
        if use_third:
            active_indices.append(2)
        active_models = tuple(model_specs[index] for index in active_indices)

        for spec in active_models:
            exists = spec.path.is_file()
            status = "확인됨" if exists else "파일 없음"
            st.code(f"{spec.label}: {spec.path.name}")
            if exists:
                st.caption(status)
            else:
                st.error(status)

        st.divider()
        st.header("추론 설정")
        confidence_threshold = st.slider(
            "bbox confidence",
            min_value=0.05,
            max_value=0.95,
            value=0.25,
            step=0.05,
        )
        image_size = st.select_slider(
            "입력 이미지 크기",
            options=(320, 480, 640, 800, 960, 1280),
            value=640,
        )
        device = st.text_input(
            "device",
            value="",
            placeholder="비우면 자동 선택, 예: cpu 또는 0",
        ).strip()
        use_perspective_rectification = st.checkbox(
            "원근 보정 사용",
            value=True,
            help=(
                "켜면 검출된 4점을 직사각형으로 펼치고, "
                "끄면 YOLO bbox 영역만 자릅니다."
            ),
        )

        if st.button(
            "모델 캐시 초기화",
            use_container_width=True,
        ):
            load_pose_model.clear()
            st.session_state.pop("pose_results", None)
            st.session_state.pop("pose_signature", None)
            st.rerun()

    uploaded_files = st.file_uploader(
        "테스트할 원본 사진 업로드",
        type=("png", "jpg", "jpeg", "bmp", "webp"),
        accept_multiple_files=True,
    )

    uploads: list[tuple[str, bytes]] = []
    decoded_uploads: list[tuple[int, str, np.ndarray]] = []
    for upload_index, upload in enumerate(uploaded_files or []):
        file_bytes = upload.getvalue()
        uploads.append((upload.name, file_bytes))
        try:
            decoded_uploads.append(
                (
                    upload_index,
                    upload.name,
                    decode_photo(file_bytes),
                )
            )
        except Exception as exc:
            st.error(
                f"{upload.name} 읽기 실패: "
                f"{type(exc).__name__}: {exc}"
            )

    if decoded_uploads:
        with st.expander("업로드 원본 미리보기", expanded=False):
            preview_columns = st.columns(min(3, len(decoded_uploads)))
            for preview_index, (_, file_name, image) in enumerate(
                decoded_uploads
            ):
                preview_columns[preview_index % len(preview_columns)].image(
                    image,
                    caption=file_name,
                    channels="BGR",
                    use_container_width=True,
                )

    missing_models = [
        spec for spec in active_models if not spec.path.is_file()
    ]
    run_disabled = not decoded_uploads or bool(missing_models)
    run = st.button(
        (
            "4점 검출 및 펼치기"
            if use_perspective_rectification
            else "4점 검출 및 bbox 자르기"
        ),
        type="primary",
        disabled=run_disabled,
        use_container_width=True,
    )

    signature = request_signature(
        uploads=uploads,
        active_models=active_models,
        confidence_threshold=confidence_threshold,
        image_size=image_size,
        device=device,
        use_perspective_rectification=use_perspective_rectification,
    )

    if run:
        loaded_models: dict[int, tuple[Any, float]] = {}
        load_errors: dict[int, str] = {}

        for spec in active_models:
            with st.spinner(f"{spec.label} 로드 중: {spec.path.name}"):
                try:
                    model, load_ms = load_pose_model(
                        str(spec.path),
                        spec.path.stat().st_mtime_ns,
                    )
                    loaded_models[spec.index] = (model, load_ms)
                except Exception as exc:
                    load_errors[spec.index] = (
                        f"{type(exc).__name__}: {exc}"
                    )

        image_results: list[ImageResult] = []
        total_jobs = len(decoded_uploads) * len(active_models)
        completed_jobs = 0
        progress = st.progress(0.0, text="추론 준비 중")

        for upload_index, file_name, original in decoded_uploads:
            model_results: list[ModelResult] = []
            for spec in active_models:
                completed_jobs += 1
                progress.progress(
                    completed_jobs / total_jobs,
                    text=f"{file_name} · {spec.label}",
                )

                if spec.index in load_errors:
                    model_results.append(
                        ModelResult(
                            spec=spec,
                            load_ms=0.0,
                            inference_ms=0.0,
                            annotated=None,
                            detections=(),
                            detection_errors=(),
                            error=load_errors[spec.index],
                        )
                    )
                    continue

                model, load_ms = loaded_models[spec.index]
                model_results.append(
                    run_inference(
                        spec=spec,
                        model=model,
                        load_ms=load_ms,
                        image=original,
                        confidence_threshold=confidence_threshold,
                        image_size=image_size,
                        device=device,
                        use_perspective_rectification=(
                            use_perspective_rectification
                        ),
                    )
                )

            image_results.append(
                ImageResult(
                    upload_index=upload_index,
                    file_name=file_name,
                    original=original,
                    model_results=tuple(model_results),
                )
            )

        progress.empty()
        st.session_state.pose_results = tuple(image_results)
        st.session_state.pose_signature = signature

    stored_results = st.session_state.get("pose_results")
    stored_signature = st.session_state.get("pose_signature")
    if stored_results and stored_signature == signature:
        st.header(
            "검출 및 원근 보정 결과"
            if use_perspective_rectification
            else "검출 및 bbox crop 결과"
        )
        for image_result in stored_results:
            render_image_result(
                image_result,
                use_perspective_rectification,
            )
    elif stored_results and uploads:
        st.info(
            "사진, 모델 선택 또는 추론 설정이 변경되었습니다. "
            "다시 실행하면 현재 조건의 결과를 표시합니다."
        )


if __name__ == "__main__":
    main()
