"""
Raspberry Pi 입차 감지 서비스의 객체 생명주기와 실행 흐름을 관리한다.

초음파 센서 측정값으로 입차 확정 신호를 확인하고 해당 시점에 카메라
촬영, 번호판 OCR과 Backend 입차 등록을 수행한다. 입차 판단 세부 로직,
카메라 내부 제어와 HTTP 통신 세부 구현은 담당하지 않는다. Backend HTTP
통신은 BackendClient에 위임하고 LED GPIO 세부 제어는 GreenLed에 위임한다.
이 모듈은 요청 실행 순서, ALLOW 표시와 오류 경계를 조율한다.
"""

from datetime import datetime, timedelta, timezone
import logging
import math
import time
from uuid import uuid4

from src.camera.entry_camera import (
    CameraInitializationError,
    CaptureSequenceError,
    EntryCamera,
)
from src.communication.backend_client import (
    BackendClient,
    BackendClientError,
)
from src.communication.schemas import (
    AccessDecision,
    BackendEntryRequest,
    BackendEntryResult,
)
from src.config.settings import (
    BACKEND_BASE_URL,
    BACKEND_HW_API_KEY,
    CAPTURE_FRAME_COUNT,
    GREEN_LED_DURATION_SECONDS,
    MEASUREMENT_INTERVAL_SECONDS,
    OCR_DETECTOR_MODEL_PATH,
    OCR_DEVICE,
    OCR_RECOGNIZER_MODEL_DIR,
    OCR_WARMUP_ENABLED,
)
from src.entry.entry_controller import EntryController, EntrySignal
from src.entry.entry_event import EntryEvent
from src.indicators.green_led import GreenLed
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


ENTRY_TIMEZONE = timezone(timedelta(hours=9))


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


def validate_backend_settings() -> None:
    """Backend 입차 등록에 필요한 필수 설정을 검증한다."""

    if not BACKEND_BASE_URL.strip():
        raise ValueError("Backend base URL은 비어 있을 수 없습니다.")

    if not BACKEND_HW_API_KEY.strip():
        raise ValueError("Backend hardware API key는 비어 있을 수 없습니다.")


def create_entry_event() -> EntryEvent:
    """한 번의 물리적 차량 입차 인식 시도를 생성한다."""

    return EntryEvent(
        entry_attempt_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        entry_time=datetime.now(ENTRY_TIMEZONE),
    )


def log_ocr_result(
    result: PlateReadResult,
    logger: logging.Logger,
) -> None:
    """OCR 판독 결과를 성공, 정상 실패 또는 불확실 상태로 기록한다."""

    if result.status is ReadStatus.SUCCESS:
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


def log_backend_entry_result(
    result: BackendEntryResult,
    logger: logging.Logger,
) -> None:
    """Backend 입차 판정 결과를 판정별 로그 레벨로 기록한다."""

    log_arguments = (
        "Backend entry decision received. "
        "entry_attempt_id=%s access_decision=%s duplicate_request=%s",
        result.entry_attempt_id,
        result.access_decision.value,
        result.duplicate_request,
    )

    if result.access_decision is AccessDecision.ALLOW:
        logger.info(*log_arguments)
        return

    if result.access_decision in (
        AccessDecision.REVIEW,
        AccessDecision.DENY,
    ):
        logger.warning(*log_arguments)
        return

    raise RuntimeError(
        f"Unsupported Backend access decision: "
        f"{result.access_decision!r}"
    )


def process_entry_event(
    event: EntryEvent,
    *,
    camera: EntryCamera,
    ocr_pipeline: PlateOcrPipeline,
    backend_client: BackendClient,
    green_led: GreenLed,
    logger: logging.Logger,
) -> None:
    """한 번의 입차 이벤트를 촬영하고 OCR 결과를 Backend에 등록한다."""

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

    if result.status is not ReadStatus.SUCCESS:
        log_ocr_result(result, logger)
        return

    plate_number = result.plate_number

    if plate_number is None:
        raise RuntimeError(
            "OCR 성공 결과에는 확정된 번호판이 필요합니다."
        )

    rec_score = result.rec_score

    if rec_score is None:
        raise RuntimeError(
            "OCR 성공 결과에는 대표 rec_score가 필요합니다."
        )

    log_ocr_result(result, logger)

    request = BackendEntryRequest(
        entry_attempt_id=event.entry_attempt_id,
        recognized_plate_number=plate_number,
        confidence=rec_score,
        entry_time=event.entry_time,
    )

    try:
        backend_result = backend_client.request_entry(
            request,
            idempotency_key=event.idempotency_key,
        )
    except BackendClientError:
        logger.error(
            "Backend entry request failed. entry_attempt_id=%s",
            event.entry_attempt_id,
            exc_info=True,
        )
        return

    if backend_result.entry_attempt_id != event.entry_attempt_id:
        raise RuntimeError(
            "Backend 응답의 entry_attempt_id가 요청과 일치하지 않습니다."
        )

    log_backend_entry_result(backend_result, logger)

    if backend_result.access_decision is not AccessDecision.ALLOW:
        return

    try:
        green_led.indicate_allow(GREEN_LED_DURATION_SECONDS)
    except Exception:
        logger.exception(
            "Green LED allow indication failed. entry_attempt_id=%s",
            event.entry_attempt_id,
        )
        raise


def main() -> None:
    configure_logging()
    validate_measurement_interval()
    validate_backend_settings()

    logger = logging.getLogger(__name__)

    backend_client = BackendClient(
        base_url=BACKEND_BASE_URL,
        api_key=BACKEND_HW_API_KEY,
    )

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
    green_led: GreenLed | None = None
    service_started = False

    try:
        sensor = UltrasonicSensor()

        try:
            camera = EntryCamera()
        except (CameraInitializationError, ValueError):
            logger.exception("Raspberry Pi entry camera initialization failed.")
            raise

        try:
            green_led = GreenLed()
        except Exception:
            logger.exception("Raspberry Pi green LED initialization failed.")
            raise

        logger.info("Raspberry Pi entry service started.")
        service_started = True

        try:
            while True:
                distance_cm = sensor.measure()
                signal = controller.update(distance_cm)

                if signal is EntrySignal.ENTRY_DETECTED:
                    logger.info("Vehicle entry detected.")
                    event = create_entry_event()
                    process_entry_event(
                        event,
                        camera=camera,
                        ocr_pipeline=ocr_pipeline,
                        backend_client=backend_client,
                        green_led=green_led,
                        logger=logger,
                    )

                time.sleep(MEASUREMENT_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            pass
    finally:
        cleanup_termination: KeyboardInterrupt | SystemExit | None = None

        if green_led is not None:
            try:
                green_led.cleanup()
            except (KeyboardInterrupt, SystemExit) as exc:
                cleanup_termination = exc
            except Exception:
                logger.exception(
                    "Raspberry Pi green LED cleanup failed."
                )

        if camera is not None:
            try:
                camera.cleanup()
            except (KeyboardInterrupt, SystemExit) as exc:
                if cleanup_termination is None:
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
