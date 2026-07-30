"""
운영 OCR component와 모델 adapter를 서비스 시작 시 한 번 조립한다.

이 모듈은 모델 경로·실행 장치·공유 프레임 정책을 받아 완성된
``PlateOcrPipeline``을 반환한다. 차량 이벤트 처리, 촬영, 재시도,
API 통신과 정상 판독 실패 처리는 담당하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .inference.plate_detector import load_yolo_plate_detector
from .inference.plate_reader import load_paddle_plate_reader
from .pipeline import PlateOcrPipeline
from .policy import OcrPipelinePolicy, validate_ocr_policy_compatibility
from .postprocessing.aggregator import AggregationPolicy, PlateAggregator
from .vision.frame_selector import QualityFrameSelector
from .vision.geometry import GeometryConfig, PlateGeometry
from .vision.plate_preprocessor import PlatePreprocessor


@dataclass(frozen=True, slots=True)
class OcrRuntimeConfig:
    """
    운영 OCR pipeline을 한 번 조립하는 데 필요한 startup 설정.

    ``policy``는 이후 카메라 촬영 코드와 공유할 프레임 정책이다.
    모델 경로의 존재·파일 구성은 각 모델 loader가 검증하며, load 또는
    선택적 warm-up 실패는 원래 예외 그대로 호출자에게 전달된다.
    """

    detector_model_path: Path
    recognizer_model_dir: Path
    policy: OcrPipelinePolicy
    device: str = "cpu"
    warm_up: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.detector_model_path, Path):
            raise TypeError("detector_model_path는 pathlib.Path여야 합니다.")
        if not isinstance(self.recognizer_model_dir, Path):
            raise TypeError("recognizer_model_dir는 pathlib.Path여야 합니다.")
        if not isinstance(self.policy, OcrPipelinePolicy):
            raise TypeError("policy는 OcrPipelinePolicy여야 합니다.")
        if not isinstance(self.device, str) or not self.device.strip():
            raise ValueError("device는 비어 있지 않은 문자열이어야 합니다.")
        if not isinstance(self.warm_up, bool):
            raise TypeError("warm_up은 bool이어야 합니다.")


def load_plate_ocr_pipeline(
    config: OcrRuntimeConfig,
) -> PlateOcrPipeline:
    """
    운영 기본 component와 모델을 startup에서 한 번 로드해 조립한다.

    호출자는 서비스 시작 시 이 함수를 한 번 호출하고 반환된 pipeline을
    차량 이벤트마다 재사용해야 한다. 전역 cache는 두지 않으므로 lifecycle
    소유권은 호출자에게 있다.

    실패:
        잘못된 runtime 설정·교차 정책 조합, 모델 파일 누락, runtime import,
        모델 load 또는 warm-up 오류를 숨기지 않고 그대로 전달한다. 실패한
        경우 부분 초기화된 pipeline은 반환하지 않는다.
    """

    if not isinstance(config, OcrRuntimeConfig):
        raise TypeError("config는 OcrRuntimeConfig여야 합니다.")

    geometry_config = GeometryConfig()
    aggregation_policy = AggregationPolicy()
    validate_ocr_policy_compatibility(
        config.policy,
        aggregation_policy,
        geometry_config,
    )

    # 정책·OpenCV 설정 오류는 무거운 모델을 읽기 전에 확인한다.
    selector = QualityFrameSelector(policy=config.policy)
    geometry = PlateGeometry(geometry_config)
    preprocessor = PlatePreprocessor()
    aggregator = PlateAggregator(aggregation_policy)

    detector = load_yolo_plate_detector(
        config.detector_model_path,
        device=config.device,
        warm_up=config.warm_up,
    )
    reader = load_paddle_plate_reader(
        config.recognizer_model_dir,
        device=config.device,
        warm_up=config.warm_up,
    )

    return PlateOcrPipeline(
        policy=config.policy,
        selector=selector,
        detector=detector,
        geometry=geometry,
        preprocessor=preprocessor,
        reader=reader,
        aggregator=aggregator,
    )
