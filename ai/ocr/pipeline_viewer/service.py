"""Streamlit OCR viewer의 모델 수명주기와 파이프라인 실행을 담당한다.

운영 코드는 ``hw/raspberry-pi/src/ocr``에서 직접 import하고 복제하지
않는다. 이 모듈은 PC 모델 경로 검증, 업로드 이미지 계약 검증, 모델별
1회 warm-up과 단일 디버그 실행 조립만 담당한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import re
import sys
from threading import Lock
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps


# [저장소와 운영 모듈 경로]


VIEWER_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = VIEWER_DIR.parents[2]
RASPBERRY_PI_ROOT = REPOSITORY_ROOT / "hw" / "raspberry-pi"
PRODUCTION_SRC = RASPBERRY_PI_ROOT / "src"
DEFAULT_MODEL_ROOT = RASPBERRY_PI_ROOT / "models"

if str(PRODUCTION_SRC) not in sys.path:
    # ai/ocr 디렉터리와 이름이 겹치지 않도록 운영 src를 가장 먼저 찾는다.
    sys.path.insert(0, str(PRODUCTION_SRC))


from ocr.inference.plate_detector import (  # noqa: E402
    load_yolo_plate_detector,
)
from ocr.inference.plate_reader import (  # noqa: E402
    load_paddle_plate_reader,
)
from ocr.image_validation import (  # noqa: E402
    is_nonempty_bgr_uint8_image,
)
from ocr.pipeline import (  # noqa: E402
    OcrPipelinePolicy,
    PlateOcrPipeline,
)
from ocr.postprocessing.aggregator import (  # noqa: E402
    AggregationPolicy,
    PlateAggregator,
)
from ocr.postprocessing.plate_text import (  # noqa: E402
    build_ocr_candidate,
)
from ocr.types import CapturedFrame, PlateReadResult  # noqa: E402
from ocr.vision.frame_selector import QualityFrameSelector  # noqa: E402
from ocr.vision.geometry import GeometryConfig, PlateGeometry  # noqa: E402
from ocr.vision.plate_preprocessor import PlatePreprocessor  # noqa: E402

from .tracing import (  # noqa: E402
    PipelineTrace,
    TracedFrameSelector,
    TracedPlateAggregator,
    TracedPlateDetector,
    TracedPlateGeometry,
    TracedPlatePreprocessor,
    TracedPlateReader,
    TracedTextProcessor,
    run_traced_pipeline,
)


DEFAULT_OCR_POLICY = OcrPipelinePolicy()
EXPECTED_FRAME_COUNT = DEFAULT_OCR_POLICY.frame_count
PADDLE_REQUIRED_FILES = (
    "inference.json",
    "inference.pdiparams",
    "inference.yml",
)


# [설정과 실행 결과]


class ModelConfigurationError(RuntimeError):
    """모델 디렉터리가 운영 loader의 파일 계약을 만족하지 않는 경우."""


class BurstInputError(ValueError):
    """업로드된 burst가 파이프라인 입력 계약을 위반한 경우."""


@dataclass(frozen=True, slots=True)
class ModelPaths:
    """번호판 검출 및 문자열 인식 모델의 로컬 경로."""

    root: Path
    detector: Path
    recognizer: Path


@dataclass(frozen=True, slots=True)
class StartupReport:
    """모델별 로드와 dummy warm-up에 걸린 시간."""

    detector_load_ms: float
    detector_warm_up_ms: float
    recognizer_load_ms: float
    recognizer_warm_up_ms: float

    @property
    def total_ms(self) -> float:
        """모델 준비 전체 시간을 밀리초로 반환한다."""

        return (
            self.detector_load_ms
            + self.detector_warm_up_ms
            + self.recognizer_load_ms
            + self.recognizer_warm_up_ms
        )


@dataclass(slots=True)
class DebugRuntime:
    """캐시해서 재사용하는 운영 컴포넌트와 실행 직렬화 lock."""

    model_paths: ModelPaths
    device: str
    policy: OcrPipelinePolicy
    selector: Any
    detector: Any
    geometry: Any
    preprocessor: Any
    reader: Any
    aggregator: Any
    startup: StartupReport
    run_lock: Lock


@dataclass(frozen=True, slots=True)
class UploadPayload:
    """Streamlit 업로드 객체에서 분리한 이름과 원본 bytes."""

    file_name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    """파일명과 파이프라인 인덱스를 보존한 BGR 이미지."""

    frame_index: int
    file_name: str
    image: np.ndarray
    byte_size: int


@dataclass(frozen=True, slots=True)
class DecodedBurst:
    """정렬·검증이 끝난 연속 프레임 burst."""

    frames: tuple[DecodedFrame, ...]
    signature: str


@dataclass(slots=True)
class DebugRun:
    """한 번의 pipeline 결과와 예외에서도 보존되는 호출 trace.

    ``result``는 pipeline이 정상 판독 결과를 반환했을 때만 존재한다.
    실행 예외의 타입과 메시지는 ``trace.pipeline_call``에 남는다.
    """

    request_signature: str
    file_names: tuple[str, ...]
    result: PlateReadResult | None
    trace: PipelineTrace


def default_model_paths() -> ModelPaths:
    """저장소의 ``hw/raspberry-pi/models`` 모델 경로를 반환한다."""

    root = DEFAULT_MODEL_ROOT.resolve()
    return ModelPaths(
        root=root,
        detector=root / "plate_detector" / "bestv1_1.pt",
        recognizer=root / "plate_recognizer",
    )


def model_paths_from_root(root: Path) -> ModelPaths:
    """지정한 root 아래에서 운영 배치 규칙에 맞는 모델 경로를 만든다."""

    resolved = root.expanduser().resolve()
    return ModelPaths(
        root=resolved,
        detector=resolved / "plate_detector" / "bestv1_1.pt",
        recognizer=resolved / "plate_recognizer",
    )


def validate_model_paths(paths: ModelPaths) -> None:
    """두 모델의 필수 파일이 존재하고 비어 있지 않은지 한 번에 검사한다."""

    problems: list[str] = []

    if not paths.detector.is_file():
        problems.append(f"YOLO 모델 파일 없음: {paths.detector}")
    elif paths.detector.stat().st_size == 0:
        problems.append(f"YOLO 모델 파일이 비어 있음: {paths.detector}")

    if not paths.recognizer.is_dir():
        problems.append(
            f"PaddleOCR 모델 디렉터리 없음: {paths.recognizer}"
        )
    else:
        for filename in PADDLE_REQUIRED_FILES:
            artifact = paths.recognizer / filename
            if not artifact.is_file():
                problems.append(f"PaddleOCR 필수 파일 없음: {artifact}")
            elif artifact.stat().st_size == 0:
                problems.append(f"PaddleOCR 필수 파일이 비어 있음: {artifact}")

    if problems:
        raise ModelConfigurationError("\n".join(problems))


def _timed(operation: Any) -> tuple[Any, float]:
    """operation 반환값과 실행 시간을 밀리초 단위로 반환한다."""

    started = time.perf_counter()
    value = operation()
    return value, (time.perf_counter() - started) * 1000.0


def load_runtime(
    paths: ModelPaths | None = None,
    *,
    device: str = "cpu",
) -> DebugRuntime:
    """모델 두 개를 로드하고 각 dummy warm-up을 정확히 한 번 수행한다.

    이 함수 자체에는 Streamlit 의존성이 없다. 호출자는 프로세스 안에서
    한 번만 실행되도록 ``st.cache_resource``로 감싸야 한다.
    """

    selected_paths = paths or default_model_paths()
    validate_model_paths(selected_paths)
    geometry_config = GeometryConfig()
    aggregation_policy = AggregationPolicy()

    detector, detector_load_ms = _timed(
        lambda: load_yolo_plate_detector(
            selected_paths.detector,
            device=device,
            warm_up=False,
        )
    )
    _, detector_warm_up_ms = _timed(detector.warm_up)

    reader, recognizer_load_ms = _timed(
        lambda: load_paddle_plate_reader(
            selected_paths.recognizer,
            device=device,
            warm_up=False,
        )
    )
    _, recognizer_warm_up_ms = _timed(reader.warm_up)

    return DebugRuntime(
        model_paths=selected_paths,
        device=device,
        policy=DEFAULT_OCR_POLICY,
        selector=QualityFrameSelector(policy=DEFAULT_OCR_POLICY),
        detector=detector,
        geometry=PlateGeometry(geometry_config),
        preprocessor=PlatePreprocessor(),
        reader=reader,
        aggregator=PlateAggregator(aggregation_policy),
        startup=StartupReport(
            detector_load_ms=detector_load_ms,
            detector_warm_up_ms=detector_warm_up_ms,
            recognizer_load_ms=recognizer_load_ms,
            recognizer_warm_up_ms=recognizer_warm_up_ms,
        ),
        run_lock=Lock(),
    )


# [업로드 이미지 처리]


_NATURAL_PART_PATTERN = re.compile(r"(\d+)")


def _natural_key(file_name: str) -> tuple[tuple[int, int | str], ...]:
    """숫자 부분을 정수로 비교하는 결정적인 파일명 정렬 key를 만든다."""

    parts: list[tuple[int, int | str]] = []
    for part in _NATURAL_PART_PATTERN.split(file_name.casefold()):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts)


def _decode_image(payload: UploadPayload) -> np.ndarray:
    """업로드 bytes의 EXIF 방향을 적용해 BGR uint8 이미지로 변환한다."""

    if not payload.content:
        raise BurstInputError(f"{payload.file_name}: 파일이 비어 있습니다.")

    try:
        with Image.open(io.BytesIO(payload.content)) as source:
            rgb = np.asarray(
                ImageOps.exif_transpose(source).convert("RGB"),
                dtype=np.uint8,
            )
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception as exc:
        # 업로드 bytes와 decoder는 외부 입력 경계이므로 라이브러리별
        # 예외 타입에 의존하지 않고 사용자 입력 오류로 격리한다.
        raise BurstInputError(
            f"{payload.file_name}: 이미지를 해석할 수 없습니다."
        ) from exc

    if not is_nonempty_bgr_uint8_image(bgr):
        raise BurstInputError(
            f"{payload.file_name}: BGR uint8 HxWx3 변환에 실패했습니다."
        )
    return np.ascontiguousarray(bgr)


def _burst_signature(payloads: Sequence[UploadPayload]) -> str:
    """파일명·크기·내용으로 현재 업로드 burst 식별자를 만든다."""

    digest = hashlib.sha256()
    for payload in payloads:
        encoded_name = payload.file_name.encode("utf-8", errors="surrogatepass")
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(payload.content).to_bytes(8, "big"))
        digest.update(payload.content)
    return digest.hexdigest()


def decode_burst(payloads: Sequence[UploadPayload]) -> DecodedBurst:
    """정책 수만큼의 사진을 자연 정렬하고 입력 계약을 검증한다."""

    supplied = tuple(payloads)
    if len(supplied) != EXPECTED_FRAME_COUNT:
        raise BurstInputError(
            f"연속 사진 {EXPECTED_FRAME_COUNT}장이 필요합니다: "
            f"actual={len(supplied)}"
        )

    ordered = tuple(
        payload
        for _, payload in sorted(
            enumerate(supplied),
            key=lambda item: (
                _natural_key(item[1].file_name),
                item[0],
            ),
        )
    )

    decoded: list[DecodedFrame] = []
    shapes: set[tuple[int, ...]] = set()
    for frame_index, payload in enumerate(ordered):
        image = _decode_image(payload)
        shapes.add(tuple(image.shape))
        decoded.append(
            DecodedFrame(
                frame_index=frame_index,
                file_name=payload.file_name,
                image=image,
                byte_size=len(payload.content),
            )
        )

    if len(shapes) != 1:
        shape_details = ", ".join(
            f"F{frame.frame_index + 1}={tuple(frame.image.shape)}"
            for frame in decoded
        )
        raise BurstInputError(
            "한 burst의 모든 프레임 해상도가 같아야 합니다: "
            f"{shape_details}"
        )

    return DecodedBurst(
        frames=tuple(decoded),
        signature=_burst_signature(ordered),
    )


# [추적 파이프라인 실행]


def _build_traced_pipeline(
    runtime: DebugRuntime,
    trace: PipelineTrace,
) -> PlateOcrPipeline:
    """캐시된 컴포넌트를 현재 실행 전용 trace wrapper로 조립한다."""

    return PlateOcrPipeline(
        selector=TracedFrameSelector(runtime.selector, trace),
        detector=TracedPlateDetector(runtime.detector, trace),
        geometry=TracedPlateGeometry(runtime.geometry, trace),
        preprocessor=TracedPlatePreprocessor(runtime.preprocessor, trace),
        reader=TracedPlateReader(runtime.reader, trace),
        aggregator=TracedPlateAggregator(runtime.aggregator, trace),
        text_processor=TracedTextProcessor(build_ocr_candidate, trace),
        policy=runtime.policy,
    )


def run_debug_pipeline(
    runtime: DebugRuntime,
    burst: DecodedBurst,
) -> DebugRun:
    """실제 운영 파이프라인을 한 번 실행하고 단계별 trace를 반환한다."""

    captured_frames = tuple(
        CapturedFrame(
            frame_index=frame.frame_index,
            image=frame.image,
        )
        for frame in burst.frames
    )
    trace = PipelineTrace()
    pipeline = _build_traced_pipeline(runtime, trace)

    # 모델별 lock과 별개로 이벤트 전체를 직렬화해 trace와 시간 측정을
    # 다른 Streamlit 세션의 추론이 교란하지 않도록 한다.
    with runtime.run_lock:
        try:
            result = run_traced_pipeline(
                trace=trace,
                frames=captured_frames,
                operation=lambda: pipeline.read_plate(captured_frames),
            )
        except Exception:
            # 운영 pipeline의 예외 계약은 유지하되, viewer 경계에서는
            # 실패한 호출의 trace도 화면에서 조사할 수 있게 보존한다.
            result = None

    return DebugRun(
        request_signature=burst.signature,
        file_names=tuple(frame.file_name for frame in burst.frames),
        result=result,
        trace=trace,
    )
