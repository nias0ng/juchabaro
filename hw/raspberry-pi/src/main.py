"""
Raspberry Pi 입차 감지 서비스의 객체 생명주기와 실행 흐름을 관리한다.

초음파 센서 측정값으로 입차 확정 신호를 확인하고 해당 시점에 카메라
촬영과 번호판 OCR을 수행한다. 입차 판단 세부 로직, 카메라 내부 제어와
외부 통신은 담당하지 않는다.
"""

import logging
import math
import time

from src.camera.entry_camera import (
    CameraInitializationError,
    CaptureSequenceError,
    EntryCamera,
)
from src.config.settings import (
    CAPTURE_FRAME_COUNT,
    MEASUREMENT_INTERVAL_SECONDS,
    OCR_DETECTOR_MODEL_PATH,
    OCR_DEVICE,
    OCR_RECOGNIZER_MODEL_DIR,
    OCR_WARMUP_ENABLED,
)
from src.entry.entry_controller import EntryController, EntrySignal
from src.ocr import (
    InvalidBurstError,
    OcrPipelinePolicy,
    OcrRuntimeConfig,
    OcrRuntimeError,
    PlateOcrPipeline,
    PlateReadResult,
    ReadStatus,
    load_plate_ocr_pipeline,
)
from src.sensors.ultrasonic_sensor import UltrasonicSensor


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def validate_measurement_interval() -> None:
    if (
        isinstance(MEASUREMENT_INTERVAL_SECONDS, bool)
        or not isinstance(MEASUREMENT_INTERVAL_SECONDS, (int, float))
        or not math.isfinite(MEASUREMENT_INTERVAL_SECONDS)
        or MEASUREMENT_INTERVAL_SECONDS <= 0
    ):
        raise ValueError("측정 주기는 0보다 큰 유한한 수여야 합니다.")


def log_ocr_result(
    result: PlateReadResult,
    logger: logging.Logger,
) -> None:
    """OCR 판독 결과를 성공, 정상 실패 또는 불확실 상태로 기록한다."""

    if result.status is ReadStatus.SUCCESS:
        if result.plate_number is None:
            raise RuntimeError(
                "OCR 성공 결과에는 확정된 번호판이 필요합니다."
            )

        logger.info(
            "Vehicle plate OCR succeeded. plate_number=%s",
            result.plate_number,
        )
        return

    if result.status in (
        ReadStatus.NO_PLATE_REGION,
        ReadStatus.OCR_EMPTY,
        ReadStatus.INVALID_FORMAT,
    ):
        logger.warning(
            "Vehicle plate OCR failed. status=%s",
            result.status.value,
        )
        return

    if result.status in (
        ReadStatus.LOW_SCORE,
        ReadStatus.AMBIGUOUS,
    ):
        logger.warning(
            "Vehicle plate OCR result is uncertain. status=%s",
            result.status.value,
        )
        return

    raise RuntimeError(
        f"Unsupported OCR read status: {result.status!r}"
    )


def process_entry_event(
    camera: EntryCamera,
    ocr_pipeline: PlateOcrPipeline,
    logger: logging.Logger,
) -> None:
    """한 번의 입차 이벤트에 대해 프레임을 촬영하고 번호판을 판독한다."""

    try:
        frames = camera.capture_sequence()
    except CaptureSequenceError:
        logger.warning(
            "Vehicle entry capture failed.",
            exc_info=True,
        )
        return

    logger.info(
        "Vehicle entry capture succeeded. frame_count=%s",
        len(frames),
    )

    try:
        result = ocr_pipeline.read_plate(frames)
    except InvalidBurstError:
        logger.error(
            "Vehicle plate OCR input contract failed.",
            exc_info=True,
        )
        return
    except OcrRuntimeError:
        logger.error(
            "Vehicle plate OCR runtime failed.",
            exc_info=True,
        )
        return

    log_ocr_result(result, logger)


def main() -> None:
    configure_logging()
    validate_measurement_interval()

    logger = logging.getLogger(__name__)

    policy = OcrPipelinePolicy(
        frame_count=CAPTURE_FRAME_COUNT,
    )
    ocr_pipeline = load_plate_ocr_pipeline(
        OcrRuntimeConfig(
            detector_model_path=OCR_DETECTOR_MODEL_PATH,
            recognizer_model_dir=OCR_RECOGNIZER_MODEL_DIR,
            policy=policy,
            device=OCR_DEVICE,
            warm_up=OCR_WARMUP_ENABLED,
        )
    )

    controller = EntryController()
    sensor: UltrasonicSensor | None = None
    camera: EntryCamera | None = None
    service_started = False

    try:
        sensor = UltrasonicSensor()

        try:
            camera = EntryCamera()
        except (CameraInitializationError, ValueError):
            logger.exception("Raspberry Pi entry camera initialization failed.")
            raise

        logger.info("Raspberry Pi entry service started.")
        service_started = True

        try:
            while True:
                distance_cm = sensor.measure()
                signal = controller.update(distance_cm)

                if signal is EntrySignal.ENTRY_DETECTED:
                    logger.info("Vehicle entry detected.")
                    process_entry_event(
                        camera,
                        ocr_pipeline,
                        logger,
                    )

                time.sleep(MEASUREMENT_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            pass
    finally:
        cleanup_termination: KeyboardInterrupt | SystemExit | None = None

        if camera is not None:
            try:
                camera.cleanup()
            except (KeyboardInterrupt, SystemExit) as exc:
                cleanup_termination = exc
            except Exception:
                logger.exception(
                    "Raspberry Pi entry camera cleanup failed."
                )

        if sensor is not None:
            try:
                sensor.cleanup()
            except (KeyboardInterrupt, SystemExit) as exc:
                if cleanup_termination is None:
                    cleanup_termination = exc
            except Exception:
                logger.exception(
                    "Raspberry Pi ultrasonic sensor cleanup failed."
                )

        if service_started:
            logger.info("Raspberry Pi entry service stopped.")

        if cleanup_termination is not None:
            raise cleanup_termination


if __name__ == "__main__":
    main()
