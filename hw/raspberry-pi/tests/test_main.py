"""
실제 하드웨어, OCR 모델과 HTTP 요청 없이 main orchestration을 검증한다.

개별 센서 측정, 카메라 촬영 및 OCR 내부 알고리즘은 검증하지 않는다.
OCR startup, 입차 이벤트, Backend 요청과 LED 표시 전달, 오류 경계 및
자원 cleanup을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import math
import sys
from types import ModuleType
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest


gpio_stub = ModuleType("RPi.GPIO")
gpio_stub.BCM = 11
gpio_stub.OUT = 0
gpio_stub.IN = 1
gpio_stub.LOW = 0
gpio_stub.HIGH = 1

rpi_stub = ModuleType("RPi")
rpi_stub.__path__ = []
rpi_stub.GPIO = gpio_stub

sys.modules["RPi"] = rpi_stub
sys.modules["RPi.GPIO"] = gpio_stub

from src import main as main_module

from src.camera.entry_camera import (
    CameraInitializationError,
    CaptureSequenceError,
)
from src.communication.backend_client import BackendClientError
from src.communication.schemas import (
    AccessDecision,
    BackendEntryRequest,
    BackendEntryResult,
    SessionContext,
)
from src.entry.entry_controller import EntrySignal
from src.entry.entry_event import EntryEvent
from src.ocr import (
    InvalidBurstError,
    OcrPipelinePolicy,
    OcrRuntimeConfig,
    OcrRuntimeError,
    PlateReadResult,
    ReadStatus,
)


BACKEND_BASE_URL = "http://backend:8080"
BACKEND_HW_API_KEY = "test-backend-api-key"
ENTRY_ATTEMPT_ID = "550e8400-e29b-41d4-a716-446655440000"
IDEMPOTENCY_KEY = "c176f427-3e47-4fbd-bb17-12ca2bf46ee9"
SECOND_ENTRY_ATTEMPT_ID = "710fa330-f2f1-4d89-a959-aca0af2216f8"
SECOND_IDEMPOTENCY_KEY = "69119a2d-d0ba-443e-b72d-30fa64318e09"
ENTRY_TIME_OFFSET = timedelta(hours=9)
ENTRY_TIME = datetime(
    2026,
    7,
    31,
    12,
    34,
    56,
    tzinfo=timezone(ENTRY_TIME_OFFSET),
)
PLATE_NUMBER = "12가3456"
OCR_CONFIDENCE = 0.97
FRAMES = tuple(object() for _ in range(main_module.CAPTURE_FRAME_COUNT))


# [테스트 데이터와 helper]


def make_backend_result(
    *,
    access_decision: AccessDecision = AccessDecision.ALLOW,
    entry_attempt_id: str = ENTRY_ATTEMPT_ID,
    duplicate_request: bool = False,
) -> BackendEntryResult:
    session_context = (
        SessionContext(
            session_id=55,
            vehicle_id=10,
            is_disabled_vehicle=False,
            is_electric=False,
        )
        if access_decision is AccessDecision.ALLOW
        else None
    )

    return BackendEntryResult(
        entry_attempt_id=entry_attempt_id,
        decision_revision=1,
        access_decision=access_decision,
        session_context=session_context,
        duplicate_request=duplicate_request,
    )


@dataclass(slots=True)
class MainHarness:
    """main orchestration에 주입한 mock 묶음."""

    pipeline: MagicMock
    sensor: MagicMock
    camera: MagicMock
    green_led: MagicMock
    controller: MagicMock
    backend_client: MagicMock
    event: EntryEvent
    backend_result: BackendEntryResult
    logger: MagicMock
    factory: MagicMock
    backend_constructor: MagicMock
    sensor_constructor: MagicMock
    camera_constructor: MagicMock
    green_led_constructor: MagicMock
    controller_constructor: MagicMock
    create_entry_event: MagicMock
    sleep: MagicMock


@pytest.fixture
def harness(
    monkeypatch: pytest.MonkeyPatch,
) -> MainHarness:
    """외부 자원 접근 없이 main을 실행할 기본 mock을 구성한다."""

    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    sensor = MagicMock(spec=main_module.UltrasonicSensor)
    camera = MagicMock(spec=main_module.EntryCamera)
    green_led = MagicMock(spec=main_module.GreenLed)
    controller = MagicMock(spec=main_module.EntryController)
    backend_client = MagicMock(spec=main_module.BackendClient)
    logger = MagicMock(spec=logging.Logger)

    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    backend_result = make_backend_result()

    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    sensor.measure.return_value = 20.0
    camera.capture_sequence.return_value = FRAMES
    controller.update.return_value = EntrySignal.NONE
    backend_client.request_entry.return_value = backend_result

    factory = MagicMock(return_value=pipeline)
    backend_constructor = MagicMock(return_value=backend_client)
    sensor_constructor = MagicMock(return_value=sensor)
    camera_constructor = MagicMock(return_value=camera)
    green_led_constructor = MagicMock(return_value=green_led)
    controller_constructor = MagicMock(return_value=controller)
    create_entry_event = MagicMock(return_value=event)

    # 기본 main 실행은 한 번의 센서 반복 뒤 정상 종료 경로로 진입한다.
    sleep = MagicMock(side_effect=KeyboardInterrupt())

    monkeypatch.setattr(
        main_module,
        "BACKEND_BASE_URL",
        BACKEND_BASE_URL,
    )
    monkeypatch.setattr(
        main_module,
        "BACKEND_HW_API_KEY",
        BACKEND_HW_API_KEY,
    )
    monkeypatch.setattr(
        main_module,
        "configure_logging",
        MagicMock(),
    )
    monkeypatch.setattr(
        main_module.logging,
        "getLogger",
        MagicMock(return_value=logger),
    )
    monkeypatch.setattr(
        main_module,
        "BackendClient",
        backend_constructor,
    )
    monkeypatch.setattr(
        main_module,
        "load_plate_ocr_pipeline",
        factory,
    )
    monkeypatch.setattr(
        main_module,
        "UltrasonicSensor",
        sensor_constructor,
    )
    monkeypatch.setattr(
        main_module,
        "EntryCamera",
        camera_constructor,
    )
    monkeypatch.setattr(
        main_module,
        "GreenLed",
        green_led_constructor,
    )
    monkeypatch.setattr(
        main_module,
        "create_entry_event",
        create_entry_event,
    )
    monkeypatch.setattr(
        main_module,
        "EntryController",
        controller_constructor,
    )
    monkeypatch.setattr(
        main_module.time,
        "sleep",
        sleep,
    )

    return MainHarness(
        pipeline=pipeline,
        sensor=sensor,
        camera=camera,
        green_led=green_led,
        controller=controller,
        backend_client=backend_client,
        event=event,
        backend_result=backend_result,
        logger=logger,
        factory=factory,
        backend_constructor=backend_constructor,
        sensor_constructor=sensor_constructor,
        camera_constructor=camera_constructor,
        green_led_constructor=green_led_constructor,
        controller_constructor=controller_constructor,
        create_entry_event=create_entry_event,
        sleep=sleep,
    )


# [설정 검증]


def test_validate_measurement_interval_accepts_positive_finite_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "MEASUREMENT_INTERVAL_SECONDS",
        0.1,
    )

    main_module.validate_measurement_interval()


@pytest.mark.parametrize(
    "invalid_interval",
    [
        pytest.param(0.0, id="zero"),
        pytest.param(-0.1, id="negative"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
        pytest.param(True, id="boolean"),
        pytest.param("0.1", id="string"),
    ],
)
def test_validate_measurement_interval_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
    invalid_interval: object,
) -> None:
    monkeypatch.setattr(
        main_module,
        "MEASUREMENT_INTERVAL_SECONDS",
        invalid_interval,
    )

    with pytest.raises(ValueError, match="측정 주기"):
        main_module.validate_measurement_interval()


def test_validate_backend_settings_accepts_valid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "BACKEND_BASE_URL",
        BACKEND_BASE_URL,
    )
    monkeypatch.setattr(
        main_module,
        "BACKEND_HW_API_KEY",
        BACKEND_HW_API_KEY,
    )

    main_module.validate_backend_settings()


@pytest.mark.parametrize(
    "invalid_base_url",
    [
        pytest.param("", id="empty"),
        pytest.param(" \t\n", id="whitespace"),
    ],
)
def test_validate_backend_settings_rejects_invalid_base_url(
    monkeypatch: pytest.MonkeyPatch,
    invalid_base_url: str,
) -> None:
    monkeypatch.setattr(
        main_module,
        "BACKEND_BASE_URL",
        invalid_base_url,
    )
    monkeypatch.setattr(
        main_module,
        "BACKEND_HW_API_KEY",
        BACKEND_HW_API_KEY,
    )

    with pytest.raises(ValueError, match="base URL"):
        main_module.validate_backend_settings()


@pytest.mark.parametrize(
    "invalid_api_key",
    [
        pytest.param("", id="empty"),
        pytest.param(" \t\n", id="whitespace"),
    ],
)
def test_validate_backend_settings_rejects_invalid_api_key(
    monkeypatch: pytest.MonkeyPatch,
    invalid_api_key: str,
) -> None:
    monkeypatch.setattr(
        main_module,
        "BACKEND_BASE_URL",
        BACKEND_BASE_URL,
    )
    monkeypatch.setattr(
        main_module,
        "BACKEND_HW_API_KEY",
        invalid_api_key,
    )

    with pytest.raises(ValueError, match="API key"):
        main_module.validate_backend_settings()


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        pytest.param(
            "BACKEND_BASE_URL",
            "",
            id="base-url",
        ),
        pytest.param(
            "BACKEND_HW_API_KEY",
            "",
            id="api-key",
        ),
    ],
)
def test_main_stops_before_runtime_initialization_for_invalid_backend_setting(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    invalid_value: str,
) -> None:
    monkeypatch.setattr(
        main_module,
        setting_name,
        invalid_value,
    )

    with pytest.raises(ValueError):
        main_module.main()

    harness.backend_constructor.assert_not_called()
    harness.factory.assert_not_called()
    harness.controller_constructor.assert_not_called()
    harness.sensor_constructor.assert_not_called()
    harness.camera_constructor.assert_not_called()


def test_main_validates_measurement_interval_before_backend_settings(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls = MagicMock()
    measurement_validation = MagicMock()
    backend_validation = MagicMock()

    validation_calls.attach_mock(
        measurement_validation,
        "measurement",
    )
    validation_calls.attach_mock(
        backend_validation,
        "backend",
    )
    monkeypatch.setattr(
        main_module,
        "validate_measurement_interval",
        measurement_validation,
    )
    monkeypatch.setattr(
        main_module,
        "validate_backend_settings",
        backend_validation,
    )

    main_module.main()

    assert validation_calls.mock_calls[:2] == [
        call.measurement(),
        call.backend(),
    ]


# [EntryEvent 생성]


def test_create_entry_event_uses_separate_uuids_and_fixed_timezone() -> None:
    first_uuid = UUID(ENTRY_ATTEMPT_ID)
    second_uuid = UUID(IDEMPOTENCY_KEY)

    with (
        patch.object(
            main_module,
            "uuid4",
            side_effect=[first_uuid, second_uuid],
        ) as uuid4,
        patch.object(main_module, "datetime") as datetime_mock,
    ):
        datetime_mock.now.return_value = ENTRY_TIME

        event = main_module.create_entry_event()

    assert uuid4.call_count == 2
    datetime_mock.now.assert_called_once_with(
        main_module.ENTRY_TIMEZONE
    )
    assert event.entry_attempt_id == str(first_uuid)
    assert event.idempotency_key == str(second_uuid)
    assert isinstance(event.entry_attempt_id, str)
    assert isinstance(event.idempotency_key, str)
    assert event.entry_time is ENTRY_TIME
    assert event.entry_time.tzinfo is not None
    assert event.entry_time.utcoffset() == ENTRY_TIME_OFFSET


# [OCR 결과 로그]


def test_log_ocr_result_logs_successful_plate_number() -> None:
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
    )

    main_module.log_ocr_result(result, logger)

    logger.info.assert_called_once_with(
        "Vehicle plate OCR succeeded. plate_number=%s",
        PLATE_NUMBER,
    )
    logger.warning.assert_not_called()
    logger.error.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(
            ReadStatus.NO_PLATE_REGION,
            id="no-plate-region",
        ),
        pytest.param(
            ReadStatus.OCR_EMPTY,
            id="ocr-empty",
        ),
        pytest.param(
            ReadStatus.INVALID_FORMAT,
            id="invalid-format",
        ),
    ],
)
def test_log_ocr_result_logs_normal_read_failure(
    status: ReadStatus,
) -> None:
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=status,
        plate_number=None,
    )

    main_module.log_ocr_result(result, logger)

    logger.info.assert_not_called()
    logger.warning.assert_called_once()
    logger.error.assert_not_called()

    warning_args = logger.warning.call_args.args
    assert "failed" in warning_args[0]
    assert warning_args[1] == status.value


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(
            ReadStatus.LOW_SCORE,
            id="low-score",
        ),
        pytest.param(
            ReadStatus.AMBIGUOUS,
            id="ambiguous",
        ),
    ],
)
def test_log_ocr_result_logs_uncertain_read(
    status: ReadStatus,
) -> None:
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=status,
        plate_number=None,
    )

    main_module.log_ocr_result(result, logger)

    logger.info.assert_not_called()
    logger.warning.assert_called_once()
    logger.error.assert_not_called()

    warning_args = logger.warning.call_args.args
    assert "uncertain" in warning_args[0]
    assert warning_args[1] == status.value


def test_log_ocr_result_rejects_unknown_status() -> None:
    logger = MagicMock(spec=logging.Logger)
    unknown_status = object()
    result = PlateReadResult(
        status=unknown_status,  # type: ignore[arg-type]
        plate_number=None,
    )

    with pytest.raises(RuntimeError):
        main_module.log_ocr_result(result, logger)

    logger.info.assert_not_called()
    logger.warning.assert_not_called()
    logger.error.assert_not_called()


# [Backend 결과 로그]


@pytest.mark.parametrize(
    ("access_decision", "expected_log_method"),
    [
        pytest.param(
            AccessDecision.ALLOW,
            "info",
            id="allow",
        ),
        pytest.param(
            AccessDecision.REVIEW,
            "warning",
            id="review",
        ),
        pytest.param(
            AccessDecision.DENY,
            "warning",
            id="deny",
        ),
    ],
)
def test_log_backend_entry_result_uses_decision_log_level(
    access_decision: AccessDecision,
    expected_log_method: str,
) -> None:
    logger = MagicMock(spec=logging.Logger)
    result = make_backend_result(
        access_decision=access_decision,
        duplicate_request=True,
    )

    main_module.log_backend_entry_result(result, logger)

    expected_log = getattr(logger, expected_log_method)
    expected_log.assert_called_once()

    log_args = expected_log.call_args.args
    assert log_args[1] == ENTRY_ATTEMPT_ID
    assert log_args[2] == access_decision.value
    assert log_args[3] is True

    if expected_log_method == "info":
        logger.warning.assert_not_called()
    else:
        logger.info.assert_not_called()


def test_log_backend_entry_result_rejects_unknown_decision() -> None:
    logger = MagicMock(spec=logging.Logger)
    unknown_decision = MagicMock()
    unknown_decision.value = "UNKNOWN"
    result = MagicMock(spec=BackendEntryResult)
    result.entry_attempt_id = ENTRY_ATTEMPT_ID
    result.access_decision = unknown_decision
    result.duplicate_request = False

    with pytest.raises(RuntimeError):
        main_module.log_backend_entry_result(result, logger)

    logger.info.assert_not_called()
    logger.warning.assert_not_called()


# [입차 이벤트 처리]


def test_process_entry_event_posts_successful_ocr_result() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    decision_calls = MagicMock()
    ocr_result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_result = make_backend_result()

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = ocr_result
    backend_client.request_entry.return_value = backend_result

    with (
        patch.object(
            main_module,
            "log_ocr_result",
        ) as log_ocr_result,
        patch.object(
            main_module,
            "log_backend_entry_result",
        ) as log_backend_entry_result,
    ):
        decision_calls.attach_mock(
            log_backend_entry_result,
            "log_backend_entry_result",
        )
        decision_calls.attach_mock(
            green_led.indicate_allow,
            "indicate_allow",
        )
        returned = main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert returned is None
    camera.capture_sequence.assert_called_once_with()
    pipeline.read_plate.assert_called_once_with(FRAMES)
    assert pipeline.read_plate.call_args.args[0] is FRAMES
    log_ocr_result.assert_called_once_with(ocr_result, logger)

    backend_client.request_entry.assert_called_once()
    backend_call = backend_client.request_entry.call_args
    request = backend_call.args[0]

    assert isinstance(request, BackendEntryRequest)
    assert request.entry_attempt_id == event.entry_attempt_id
    assert request.recognized_plate_number == PLATE_NUMBER
    assert request.entry_time is event.entry_time
    assert request.confidence == OCR_CONFIDENCE
    assert backend_call.kwargs == {
        "idempotency_key": event.idempotency_key,
    }
    log_backend_entry_result.assert_called_once_with(
        backend_result,
        logger,
    )
    green_led.indicate_allow.assert_called_once_with(
        main_module.GREEN_LED_DURATION_SECONDS
    )
    assert decision_calls.mock_calls == [
        call.log_backend_entry_result(
            backend_result,
            logger,
        ),
        call.indicate_allow(
            main_module.GREEN_LED_DURATION_SECONDS
        ),
    ]


@pytest.mark.parametrize(
    "access_decision",
    [
        pytest.param(
            AccessDecision.REVIEW,
            id="review",
        ),
        pytest.param(
            AccessDecision.DENY,
            id="deny",
        ),
    ],
)
def test_process_entry_event_does_not_indicate_non_allow_decision(
    access_decision: AccessDecision,
) -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_result = make_backend_result(
        access_decision=access_decision,
    )
    backend_client.request_entry.return_value = backend_result

    with patch.object(
        main_module,
        "log_backend_entry_result",
    ) as log_backend_entry_result:
        returned = main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert returned is None
    log_backend_entry_result.assert_called_once_with(
        backend_result,
        logger,
    )
    green_led.indicate_allow.assert_not_called()


def test_process_entry_event_stops_after_capture_failure() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    capture_error = CaptureSequenceError("capture failed")

    camera.capture_sequence.side_effect = capture_error

    returned = main_module.process_entry_event(
        event,
        camera=camera,
        ocr_pipeline=pipeline,
        backend_client=backend_client,
        green_led=green_led,
        logger=logger,
    )

    assert returned is None
    camera.capture_sequence.assert_called_once_with()
    pipeline.read_plate.assert_not_called()
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()
    logger.warning.assert_called_once()
    assert logger.warning.call_args.kwargs["exc_info"] is True
    logger.error.assert_not_called()


@pytest.mark.parametrize(
    ("ocr_error", "expected_message"),
    [
        pytest.param(
            InvalidBurstError("invalid burst"),
            "Vehicle plate OCR input contract failed.",
            id="invalid-burst",
        ),
        pytest.param(
            OcrRuntimeError("runtime failure"),
            "Vehicle plate OCR runtime failed.",
            id="ocr-runtime",
        ),
    ],
)
def test_process_entry_event_handles_known_ocr_error(
    ocr_error: Exception,
    expected_message: str,
) -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.side_effect = ocr_error

    returned = main_module.process_entry_event(
        event,
        camera=camera,
        ocr_pipeline=pipeline,
        backend_client=backend_client,
        green_led=green_led,
        logger=logger,
    )

    assert returned is None
    camera.capture_sequence.assert_called_once_with()
    pipeline.read_plate.assert_called_once_with(FRAMES)
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()
    logger.error.assert_called_once_with(
        expected_message,
        exc_info=True,
    )


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(
            ReadStatus.NO_PLATE_REGION,
            id="no-plate-region",
        ),
        pytest.param(
            ReadStatus.OCR_EMPTY,
            id="ocr-empty",
        ),
        pytest.param(
            ReadStatus.INVALID_FORMAT,
            id="invalid-format",
        ),
        pytest.param(
            ReadStatus.LOW_SCORE,
            id="low-score",
        ),
        pytest.param(
            ReadStatus.AMBIGUOUS,
            id="ambiguous",
        ),
    ],
)
def test_process_entry_event_does_not_call_backend_for_unsuccessful_ocr(
    status: ReadStatus,
) -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=status,
        plate_number=None,
    )

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = result

    with patch.object(
        main_module,
        "log_ocr_result",
    ) as log_ocr_result:
        returned = main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert returned is None
    log_ocr_result.assert_called_once_with(result, logger)
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()


def test_process_entry_event_rejects_success_without_plate_number() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=None,
        rec_score=OCR_CONFIDENCE,
    )

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = result

    with (
        patch.object(
            main_module,
            "log_ocr_result",
        ) as log_ocr_result,
        patch.object(
            main_module,
            "log_backend_entry_result",
        ) as log_backend_entry_result,
    ):
        with pytest.raises(RuntimeError):
            main_module.process_entry_event(
                event,
                camera=camera,
                ocr_pipeline=pipeline,
                backend_client=backend_client,
                green_led=green_led,
                logger=logger,
            )

    log_ocr_result.assert_not_called()
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()
    log_backend_entry_result.assert_not_called()


def test_process_entry_event_rejects_success_without_rec_score() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=None,
    )

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = result

    with (
        patch.object(
            main_module,
            "log_ocr_result",
        ) as log_ocr_result,
        patch.object(
            main_module,
            "log_backend_entry_result",
        ) as log_backend_entry_result,
    ):
        with pytest.raises(RuntimeError, match="rec_score"):
            main_module.process_entry_event(
                event,
                camera=camera,
                ocr_pipeline=pipeline,
                backend_client=backend_client,
                green_led=green_led,
                logger=logger,
            )

    log_ocr_result.assert_not_called()
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()
    log_backend_entry_result.assert_not_called()


def test_process_entry_event_handles_backend_client_error() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_error = BackendClientError("request failed")

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = result
    backend_client.request_entry.side_effect = backend_error

    with patch.object(
        main_module,
        "log_backend_entry_result",
    ) as log_backend_entry_result:
        returned = main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert returned is None
    logger.error.assert_called_once_with(
        "Backend entry request failed. entry_attempt_id=%s",
        ENTRY_ATTEMPT_ID,
        exc_info=True,
    )
    log_backend_entry_result.assert_not_called()
    green_led.indicate_allow.assert_not_called()


@pytest.mark.parametrize(
    "unexpected_error",
    [
        pytest.param(
            LookupError("unexpected backend failure"),
            id="lookup-error",
        ),
        pytest.param(
            RuntimeError("unexpected backend failure"),
            id="runtime-error",
        ),
    ],
)
def test_process_entry_event_propagates_unexpected_backend_error(
    unexpected_error: Exception,
) -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_client.request_entry.side_effect = unexpected_error

    with pytest.raises(type(unexpected_error)) as captured:
        main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert captured.value is unexpected_error
    green_led.indicate_allow.assert_not_called()


def test_process_entry_event_rejects_mismatched_response_id() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_client.request_entry.return_value = make_backend_result(
        entry_attempt_id=SECOND_ENTRY_ATTEMPT_ID,
    )

    with patch.object(
        main_module,
        "log_backend_entry_result",
    ) as log_backend_entry_result:
        with pytest.raises(RuntimeError, match="entry_attempt_id"):
            main_module.process_entry_event(
                event,
                camera=camera,
                ocr_pipeline=pipeline,
                backend_client=backend_client,
                green_led=green_led,
                logger=logger,
            )

    log_backend_entry_result.assert_not_called()
    green_led.indicate_allow.assert_not_called()


def test_process_entry_event_propagates_unexpected_ocr_exception() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    unexpected_error = LookupError("unexpected OCR failure")

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.side_effect = unexpected_error

    with pytest.raises(LookupError) as captured:
        main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert captured.value is unexpected_error
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()
    logger.error.assert_not_called()


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(2),
            id="system-exit",
        ),
    ],
)
def test_process_entry_event_propagates_termination_exception(
    termination: BaseException,
) -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert captured.value is termination
    backend_client.request_entry.assert_not_called()
    green_led.indicate_allow.assert_not_called()
    logger.warning.assert_not_called()
    logger.error.assert_not_called()


def test_process_entry_event_logs_and_propagates_led_error() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)
    led_error = RuntimeError("LED indication failed")

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_client.request_entry.return_value = make_backend_result()
    green_led.indicate_allow.side_effect = led_error

    with pytest.raises(RuntimeError) as captured:
        main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert captured.value is led_error
    logger.exception.assert_called_once_with(
        "Green LED allow indication failed. entry_attempt_id=%s",
        ENTRY_ATTEMPT_ID,
    )


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(2),
            id="system-exit",
        ),
    ],
)
def test_process_entry_event_propagates_led_termination_without_error_log(
    termination: BaseException,
) -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    backend_client = MagicMock(spec=main_module.BackendClient)
    green_led = MagicMock(spec=main_module.GreenLed)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )
    backend_client.request_entry.return_value = make_backend_result()
    green_led.indicate_allow.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        main_module.process_entry_event(
            event,
            camera=camera,
            ocr_pipeline=pipeline,
            backend_client=backend_client,
            green_led=green_led,
            logger=logger,
        )

    assert captured.value is termination
    logger.exception.assert_not_called()


# [startup과 반복 흐름]


def test_main_constructs_backend_client_once_with_existing_settings(
    harness: MainHarness,
) -> None:
    main_module.main()

    harness.backend_constructor.assert_called_once_with(
        base_url=BACKEND_BASE_URL,
        api_key=BACKEND_HW_API_KEY,
    )


def test_main_loads_ocr_pipeline_once(
    harness: MainHarness,
) -> None:
    main_module.main()

    harness.factory.assert_called_once()


def test_main_passes_runtime_settings_and_capture_policy_to_factory(
    harness: MainHarness,
) -> None:
    main_module.main()

    harness.factory.assert_called_once()
    config = harness.factory.call_args.args[0]

    assert isinstance(config, OcrRuntimeConfig)
    assert (
        config.detector_model_path
        == main_module.OCR_DETECTOR_MODEL_PATH
    )
    assert (
        config.recognizer_model_dir
        == main_module.OCR_RECOGNIZER_MODEL_DIR
    )
    assert config.device == main_module.OCR_DEVICE
    assert config.warm_up is main_module.OCR_WARMUP_ENABLED
    assert isinstance(config.policy, OcrPipelinePolicy)
    assert config.policy.frame_count == main_module.CAPTURE_FRAME_COUNT


def test_main_constructs_backend_before_loading_pipeline(
    harness: MainHarness,
) -> None:
    calls = MagicMock()
    calls.attach_mock(
        harness.backend_constructor,
        "backend_constructor",
    )
    calls.attach_mock(harness.factory, "factory")

    main_module.main()

    assert [
        recorded_call[0]
        for recorded_call in calls.mock_calls[:2]
    ] == [
        "backend_constructor",
        "factory",
    ]


def test_main_loads_pipeline_before_hardware_in_order(
    harness: MainHarness,
) -> None:
    calls = MagicMock()
    calls.attach_mock(harness.factory, "factory")
    calls.attach_mock(
        harness.sensor_constructor,
        "sensor_constructor",
    )
    calls.attach_mock(
        harness.camera_constructor,
        "camera_constructor",
    )
    calls.attach_mock(
        harness.green_led_constructor,
        "green_led_constructor",
    )

    main_module.main()

    assert [
        recorded_call[0]
        for recorded_call in calls.mock_calls[:4]
    ] == [
        "factory",
        "sensor_constructor",
        "camera_constructor",
        "green_led_constructor",
    ]


def test_main_propagates_factory_failure_before_hardware_initialization(
    harness: MainHarness,
) -> None:
    startup_error = RuntimeError("model initialization failed")
    harness.factory.side_effect = startup_error

    with pytest.raises(RuntimeError) as captured:
        main_module.main()

    assert captured.value is startup_error
    harness.backend_constructor.assert_called_once()
    harness.factory.assert_called_once()
    harness.sensor_constructor.assert_not_called()
    harness.camera_constructor.assert_not_called()
    harness.green_led_constructor.assert_not_called()


def test_main_does_not_create_event_for_none_signal(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_entry_event = MagicMock()
    monkeypatch.setattr(
        main_module,
        "process_entry_event",
        process_entry_event,
    )
    harness.sensor.measure.return_value = 18.0
    harness.controller.update.return_value = EntrySignal.NONE

    main_module.main()

    harness.sensor.measure.assert_called_once_with()
    harness.controller.update.assert_called_once_with(18.0)
    harness.create_entry_event.assert_not_called()
    process_entry_event.assert_not_called()


def test_main_creates_event_before_processing_detected_entry(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_entry_event = MagicMock()
    ordered_calls = MagicMock()

    monkeypatch.setattr(
        main_module,
        "process_entry_event",
        process_entry_event,
    )
    ordered_calls.attach_mock(
        harness.create_entry_event,
        "create_entry_event",
    )
    ordered_calls.attach_mock(
        process_entry_event,
        "process_entry_event",
    )
    harness.controller.update.return_value = EntrySignal.ENTRY_DETECTED

    main_module.main()

    harness.create_entry_event.assert_called_once_with()
    process_entry_event.assert_called_once_with(
        harness.event,
        camera=harness.camera,
        ocr_pipeline=harness.pipeline,
        backend_client=harness.backend_client,
        green_led=harness.green_led,
        logger=harness.logger,
    )
    assert [
        recorded_call[0]
        for recorded_call in ordered_calls.mock_calls
    ] == [
        "create_entry_event",
        "process_entry_event",
    ]


def test_main_reuses_runtime_objects_across_multiple_entry_events(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_entry_event = MagicMock()
    first_event = harness.event
    second_event = EntryEvent(
        entry_attempt_id=SECOND_ENTRY_ATTEMPT_ID,
        idempotency_key=SECOND_IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )

    monkeypatch.setattr(
        main_module,
        "process_entry_event",
        process_entry_event,
    )

    harness.create_entry_event.side_effect = [
        first_event,
        second_event,
    ]
    harness.sensor.measure.side_effect = [5.0, 5.0]
    harness.controller.update.side_effect = [
        EntrySignal.ENTRY_DETECTED,
        EntrySignal.ENTRY_DETECTED,
    ]
    harness.sleep.side_effect = [
        None,
        KeyboardInterrupt(),
    ]

    main_module.main()

    harness.backend_constructor.assert_called_once()
    harness.factory.assert_called_once()
    harness.green_led_constructor.assert_called_once_with()
    assert harness.create_entry_event.call_count == 2
    assert process_entry_event.call_count == 2

    first_call, second_call = process_entry_event.call_args_list
    assert first_call.args[0] is first_event
    assert second_call.args[0] is second_event

    for event_call in process_entry_event.call_args_list:
        assert event_call.kwargs["camera"] is harness.camera
        assert event_call.kwargs["ocr_pipeline"] is harness.pipeline
        assert (
            event_call.kwargs["backend_client"]
            is harness.backend_client
        )
        assert event_call.kwargs["green_led"] is harness.green_led
        assert event_call.kwargs["logger"] is harness.logger


def test_main_continues_after_known_ocr_runtime_error(
    harness: MainHarness,
) -> None:
    ocr_error = OcrRuntimeError("temporary OCR runtime failure")
    successful_result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
        rec_score=OCR_CONFIDENCE,
    )

    harness.sensor.measure.side_effect = [5.0, 5.0]
    harness.controller.update.side_effect = [
        EntrySignal.ENTRY_DETECTED,
        EntrySignal.ENTRY_DETECTED,
    ]
    harness.camera.capture_sequence.return_value = FRAMES
    harness.pipeline.read_plate.side_effect = [
        ocr_error,
        successful_result,
    ]
    harness.sleep.side_effect = [
        None,
        KeyboardInterrupt(),
    ]

    main_module.main()

    assert harness.sensor.measure.call_count == 2
    assert harness.camera.capture_sequence.call_count == 2
    assert harness.pipeline.read_plate.call_count == 2
    harness.backend_client.request_entry.assert_called_once()
    harness.factory.assert_called_once()
    harness.logger.error.assert_called_once()
    assert harness.logger.error.call_args.kwargs["exc_info"] is True


def test_main_continues_after_backend_client_error(
    harness: MainHarness,
) -> None:
    first_error = BackendClientError("temporary backend failure")
    second_result = make_backend_result(
        entry_attempt_id=SECOND_ENTRY_ATTEMPT_ID,
    )
    second_event = EntryEvent(
        entry_attempt_id=SECOND_ENTRY_ATTEMPT_ID,
        idempotency_key=SECOND_IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )

    harness.create_entry_event.side_effect = [
        harness.event,
        second_event,
    ]
    harness.sensor.measure.side_effect = [5.0, 5.0]
    harness.controller.update.side_effect = [
        EntrySignal.ENTRY_DETECTED,
        EntrySignal.ENTRY_DETECTED,
    ]
    harness.backend_client.request_entry.side_effect = [
        first_error,
        second_result,
    ]
    harness.sleep.side_effect = [
        None,
        KeyboardInterrupt(),
    ]

    main_module.main()

    assert harness.sensor.measure.call_count == 2
    assert harness.backend_client.request_entry.call_count == 2
    harness.logger.error.assert_called_once_with(
        "Backend entry request failed. entry_attempt_id=%s",
        ENTRY_ATTEMPT_ID,
        exc_info=True,
    )


def test_main_cleans_existing_hardware_after_led_initialization_failure(
    harness: MainHarness,
) -> None:
    initialization_error = RuntimeError(
        "green LED initialization failed"
    )
    harness.green_led_constructor.side_effect = initialization_error

    with pytest.raises(RuntimeError) as captured:
        main_module.main()

    assert captured.value is initialization_error
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()
    harness.green_led.cleanup.assert_not_called()
    harness.logger.exception.assert_called_once_with(
        "Raspberry Pi green LED initialization failed."
    )
    assert call(
        "Raspberry Pi entry service started."
    ) not in harness.logger.info.call_args_list
    assert call(
        "Raspberry Pi entry service stopped."
    ) not in harness.logger.info.call_args_list


# [서비스 종료와 cleanup]


def test_main_cleans_hardware_in_reverse_initialization_order(
    harness: MainHarness,
) -> None:
    cleanup_calls = MagicMock()
    cleanup_calls.attach_mock(
        harness.green_led.cleanup,
        "green_led_cleanup",
    )
    cleanup_calls.attach_mock(
        harness.camera.cleanup,
        "camera_cleanup",
    )
    cleanup_calls.attach_mock(
        harness.sensor.cleanup,
        "sensor_cleanup",
    )

    main_module.main()

    assert cleanup_calls.mock_calls == [
        call.green_led_cleanup(),
        call.camera_cleanup(),
        call.sensor_cleanup(),
    ]
    harness.logger.info.assert_any_call(
        "Raspberry Pi entry service stopped."
    )


def test_main_cleans_sensor_after_camera_initialization_failure(
    harness: MainHarness,
) -> None:
    initialization_error = CameraInitializationError(
        "camera initialization failed"
    )
    harness.camera_constructor.side_effect = initialization_error

    with pytest.raises(CameraInitializationError) as captured:
        main_module.main()

    assert captured.value is initialization_error
    harness.sensor.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_not_called()
    harness.green_led_constructor.assert_not_called()
    harness.green_led.cleanup.assert_not_called()
    assert call(
        "Raspberry Pi entry service stopped."
    ) not in harness.logger.info.call_args_list


def test_main_cleans_resources_and_propagates_unexpected_ocr_error(
    harness: MainHarness,
) -> None:
    unexpected_error = LookupError("unexpected OCR failure")

    harness.controller.update.return_value = EntrySignal.ENTRY_DETECTED
    harness.camera.capture_sequence.return_value = FRAMES
    harness.pipeline.read_plate.side_effect = unexpected_error

    with pytest.raises(LookupError) as captured:
        main_module.main()

    assert captured.value is unexpected_error
    harness.green_led.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()


def test_main_cleans_resources_and_propagates_unexpected_backend_error(
    harness: MainHarness,
) -> None:
    unexpected_error = LookupError("unexpected Backend failure")

    harness.controller.update.return_value = EntrySignal.ENTRY_DETECTED
    harness.backend_client.request_entry.side_effect = unexpected_error

    with pytest.raises(LookupError) as captured:
        main_module.main()

    assert captured.value is unexpected_error
    harness.green_led.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()


def test_main_continues_cleanup_after_led_cleanup_failure(
    harness: MainHarness,
) -> None:
    cleanup_error = RuntimeError("green LED cleanup failed")
    harness.green_led.cleanup.side_effect = cleanup_error

    main_module.main()

    harness.green_led.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()
    harness.logger.exception.assert_any_call(
        "Raspberry Pi green LED cleanup failed."
    )


def test_main_continues_sensor_cleanup_after_camera_cleanup_failure(
    harness: MainHarness,
) -> None:
    cleanup_error = RuntimeError("camera cleanup failed")
    harness.camera.cleanup.side_effect = cleanup_error

    main_module.main()

    harness.green_led.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()
    harness.logger.exception.assert_any_call(
        "Raspberry Pi entry camera cleanup failed."
    )


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(3),
            id="system-exit",
        ),
    ],
)
def test_main_preserves_led_cleanup_termination_after_remaining_cleanup(
    harness: MainHarness,
    termination: BaseException,
) -> None:
    later_termination = SystemExit(9)
    harness.green_led.cleanup.side_effect = termination
    harness.camera.cleanup.side_effect = later_termination

    with pytest.raises(type(termination)) as captured:
        main_module.main()

    assert captured.value is termination
    harness.green_led.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(3),
            id="system-exit",
        ),
    ],
)
def test_main_preserves_camera_cleanup_termination_after_sensor_cleanup(
    harness: MainHarness,
    termination: BaseException,
) -> None:
    harness.camera.cleanup.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        main_module.main()

    assert captured.value is termination
    harness.green_led.cleanup.assert_called_once_with()
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()
