"""
실제 하드웨어와 OCR 모델 없이 main orchestration을 검증한다.

개별 센서 측정, 카메라 촬영 및 OCR 내부 알고리즘은 검증하지 않는다.
OCR startup, 입차 이벤트 전달, 오류 경계와 자원 cleanup을 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
from types import ModuleType
from unittest.mock import MagicMock, call, patch

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

with patch.dict(
    sys.modules,
    {
        "RPi": rpi_stub,
        "RPi.GPIO": gpio_stub,
    },
):
    from src import main as main_module

from src.camera.entry_camera import (
    CameraInitializationError,
    CaptureSequenceError,
)
from src.entry.entry_controller import EntrySignal
from src.ocr import (
    InvalidBurstError,
    OcrRuntimeConfig,
    OcrRuntimeError,
    PlateReadResult,
    ReadStatus,
)


PLATE_NUMBER = "12가3456"
FRAMES = tuple(object() for _ in range(main_module.CAPTURE_FRAME_COUNT))


# [테스트 데이터와 helper]


@dataclass(slots=True)
class MainHarness:
    """main orchestration에 주입한 mock 묶음."""

    pipeline: MagicMock
    sensor: MagicMock
    camera: MagicMock
    controller: MagicMock
    logger: MagicMock
    factory: MagicMock
    sensor_constructor: MagicMock
    camera_constructor: MagicMock
    controller_constructor: MagicMock
    sleep: MagicMock


@pytest.fixture
def harness(
    monkeypatch: pytest.MonkeyPatch,
) -> MainHarness:
    """하드웨어와 모델 접근 없이 main을 실행할 기본 mock을 구성한다."""

    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    sensor = MagicMock(spec=main_module.UltrasonicSensor)
    camera = MagicMock(spec=main_module.EntryCamera)
    controller = MagicMock(spec=main_module.EntryController)
    logger = MagicMock(spec=logging.Logger)

    pipeline.read_plate.return_value = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
    )
    sensor.measure.return_value = 20.0
    camera.capture_sequence.return_value = FRAMES
    controller.update.return_value = EntrySignal.NONE

    factory = MagicMock(return_value=pipeline)
    sensor_constructor = MagicMock(return_value=sensor)
    camera_constructor = MagicMock(return_value=camera)
    controller_constructor = MagicMock(return_value=controller)

    # 기본 main 실행은 한 번의 센서 반복 뒤 정상 종료 경로로 진입한다.
    sleep = MagicMock(side_effect=KeyboardInterrupt())

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
        controller=controller,
        logger=logger,
        factory=factory,
        sensor_constructor=sensor_constructor,
        camera_constructor=camera_constructor,
        controller_constructor=controller_constructor,
        sleep=sleep,
    )


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


def test_log_ocr_result_rejects_success_without_plate_number() -> None:
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=None,
    )

    with pytest.raises(RuntimeError):
        main_module.log_ocr_result(result, logger)

    logger.info.assert_not_called()
    logger.warning.assert_not_called()
    logger.error.assert_not_called()


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


# [입차 이벤트 처리]


def test_process_entry_event_passes_same_frames_to_pipeline() -> None:
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    logger = MagicMock(spec=logging.Logger)
    result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
    )

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.return_value = result

    with patch.object(
        main_module,
        "log_ocr_result",
    ) as log_ocr_result:
        returned = main_module.process_entry_event(
            camera,
            pipeline,
            logger,
        )

    assert returned is None
    camera.capture_sequence.assert_called_once_with()
    pipeline.read_plate.assert_called_once_with(FRAMES)
    assert pipeline.read_plate.call_args.args[0] is FRAMES
    log_ocr_result.assert_called_once_with(result, logger)


def test_process_entry_event_stops_after_capture_failure() -> None:
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    logger = MagicMock(spec=logging.Logger)
    capture_error = CaptureSequenceError("capture failed")

    camera.capture_sequence.side_effect = capture_error

    returned = main_module.process_entry_event(
        camera,
        pipeline,
        logger,
    )

    assert returned is None
    camera.capture_sequence.assert_called_once_with()
    pipeline.read_plate.assert_not_called()
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
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.side_effect = ocr_error

    returned = main_module.process_entry_event(
        camera,
        pipeline,
        logger,
    )

    assert returned is None
    camera.capture_sequence.assert_called_once_with()
    pipeline.read_plate.assert_called_once_with(FRAMES)
    logger.error.assert_called_once_with(
        expected_message,
        exc_info=True,
    )


def test_process_entry_event_propagates_unexpected_exception() -> None:
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    logger = MagicMock(spec=logging.Logger)
    unexpected_error = LookupError("unexpected OCR failure")

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.side_effect = unexpected_error

    with pytest.raises(LookupError) as captured:
        main_module.process_entry_event(
            camera,
            pipeline,
            logger,
        )

    assert captured.value is unexpected_error
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
    camera = MagicMock(spec=main_module.EntryCamera)
    pipeline = MagicMock(spec=main_module.PlateOcrPipeline)
    logger = MagicMock(spec=logging.Logger)

    camera.capture_sequence.return_value = FRAMES
    pipeline.read_plate.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        main_module.process_entry_event(
            camera,
            pipeline,
            logger,
        )

    assert captured.value is termination
    logger.warning.assert_not_called()
    logger.error.assert_not_called()


# [OCR startup과 반복 흐름]


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
    assert config.policy.frame_count == main_module.CAPTURE_FRAME_COUNT


def test_main_loads_pipeline_before_sensor_and_camera(
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

    main_module.main()

    assert [
        recorded_call[0]
        for recorded_call in calls.mock_calls[:3]
    ] == [
        "factory",
        "sensor_constructor",
        "camera_constructor",
    ]


def test_main_propagates_factory_failure_before_hardware_initialization(
    harness: MainHarness,
) -> None:
    startup_error = RuntimeError("model initialization failed")
    harness.factory.side_effect = startup_error

    with pytest.raises(RuntimeError) as captured:
        main_module.main()

    assert captured.value is startup_error
    harness.factory.assert_called_once()
    harness.sensor_constructor.assert_not_called()
    harness.camera_constructor.assert_not_called()


def test_main_does_not_process_entry_event_for_none_signal(
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
    process_entry_event.assert_not_called()


def test_main_processes_entry_detected_with_loaded_pipeline(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_entry_event = MagicMock()
    monkeypatch.setattr(
        main_module,
        "process_entry_event",
        process_entry_event,
    )
    harness.controller.update.return_value = EntrySignal.ENTRY_DETECTED

    main_module.main()

    process_entry_event.assert_called_once_with(
        harness.camera,
        harness.pipeline,
        harness.logger,
    )


def test_main_reuses_pipeline_across_multiple_entry_events(
    harness: MainHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_entry_event = MagicMock()
    monkeypatch.setattr(
        main_module,
        "process_entry_event",
        process_entry_event,
    )

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

    harness.factory.assert_called_once()
    assert process_entry_event.call_count == 2
    assert all(
        event_call.args[1] is harness.pipeline
        for event_call in process_entry_event.call_args_list
    )


def test_main_continues_after_known_ocr_runtime_error(
    harness: MainHarness,
) -> None:
    ocr_error = OcrRuntimeError("temporary OCR runtime failure")
    successful_result = PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=PLATE_NUMBER,
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
    harness.factory.assert_called_once()
    harness.logger.error.assert_called_once()
    assert harness.logger.error.call_args.kwargs["exc_info"] is True


# [서비스 종료와 cleanup]


def test_main_cleans_camera_before_sensor_on_normal_exit(
    harness: MainHarness,
) -> None:
    cleanup_calls = MagicMock()
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
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()


def test_main_continues_sensor_cleanup_after_camera_cleanup_failure(
    harness: MainHarness,
) -> None:
    cleanup_error = RuntimeError("camera cleanup failed")
    harness.camera.cleanup.side_effect = cleanup_error

    main_module.main()

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
def test_main_preserves_camera_cleanup_termination_after_sensor_cleanup(
    harness: MainHarness,
    termination: BaseException,
) -> None:
    harness.camera.cleanup.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        main_module.main()

    assert captured.value is termination
    harness.camera.cleanup.assert_called_once_with()
    harness.sensor.cleanup.assert_called_once_with()
