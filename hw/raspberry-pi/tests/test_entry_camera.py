"""
실제 Picamera2 장치 없이 EntryCamera의 촬영 및 자원 관리 계약을 검증한다.

카메라 초기화, 설정 검증, 프레임 변환, 전체 재촬영, 예외 전파와 cleanup
상태를 mock으로 확인한다. 실제 CSI 카메라 연결, 이미지 품질, OCR 실행,
파일 저장 및 외부 통신은 검증하지 않는다.
"""

from collections.abc import Callable
from unittest.mock import MagicMock, call

import numpy as np
import pytest

from src.camera import entry_camera
from src.ocr.types import CapturedFrame


# [테스트 데이터와 생성 도우미]


def make_rgb_image(
    *,
    red: int = 10,
    green: int = 20,
    blue: int = 30,
) -> np.ndarray:
    """운영 촬영 계약과 동일한 크기의 RGB uint8 배열을 생성한다."""

    image = np.empty(
        (
            entry_camera.CAMERA_HEIGHT,
            entry_camera.CAMERA_WIDTH,
            3,
        ),
        dtype=np.uint8,
    )
    image[..., 0] = red
    image[..., 1] = green
    image[..., 2] = blue
    return image


def make_camera(
    image: np.ndarray | None = None,
) -> tuple[MagicMock, object]:
    """Picamera2가 사용하는 최소 메서드를 가진 mock을 생성한다."""

    camera = MagicMock()
    configuration = object()

    camera.create_still_configuration.return_value = configuration
    camera.capture_array.return_value = (
        image if image is not None else make_rgb_image()
    )

    return camera, configuration


def make_entry_camera(
    *,
    camera: MagicMock | None = None,
    camera_factory: MagicMock | None = None,
    sleep: MagicMock | None = None,
) -> tuple[
    entry_camera.EntryCamera,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    """주입한 mock과 함께 초기화된 EntryCamera를 반환한다."""

    if camera is None:
        camera, _ = make_camera()
    if camera_factory is None:
        camera_factory = MagicMock(return_value=camera)
    if sleep is None:
        sleep = MagicMock()

    instance = entry_camera.EntryCamera(
        camera_factory=camera_factory,
        sleep=sleep,
    )

    return instance, camera, camera_factory, sleep


# [초기화와 설정 검증]


def test_constructor_initializes_camera_in_order() -> None:
    camera, configuration = make_camera()
    camera_factory = MagicMock(return_value=camera)
    sleep = MagicMock()
    calls = MagicMock()

    calls.attach_mock(camera_factory, "factory")
    calls.attach_mock(
        camera.create_still_configuration,
        "create_still_configuration",
    )
    calls.attach_mock(camera.configure, "configure")
    calls.attach_mock(camera.start, "start")
    calls.attach_mock(sleep, "sleep")

    instance = entry_camera.EntryCamera(
        camera_factory=camera_factory,
        sleep=sleep,
    )

    assert calls.mock_calls == [
        call.factory(),
        call.create_still_configuration(
            main={
                "size": (
                    entry_camera.CAMERA_WIDTH,
                    entry_camera.CAMERA_HEIGHT,
                ),
                "format": entry_camera.CAMERA_PIXEL_FORMAT,
            }
        ),
        call.configure(configuration),
        call.start(),
        call.sleep(entry_camera.CAMERA_WARMUP_SECONDS),
    ]

    frames = instance.capture_sequence()

    assert len(frames) == entry_camera.CAPTURE_FRAME_COUNT


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        pytest.param(
            "CAMERA_WIDTH",
            0,
            id="zero-camera-width",
        ),
        pytest.param(
            "CAMERA_HEIGHT",
            -1,
            id="negative-camera-height",
        ),
        pytest.param(
            "CAMERA_WIDTH",
            True,
            id="boolean-camera-width",
        ),
        pytest.param(
            "CAPTURE_FRAME_COUNT",
            5,
            id="non-six-frame-count",
        ),
        pytest.param(
            "CAPTURE_FRAME_COUNT",
            True,
            id="boolean-frame-count",
        ),
        pytest.param(
            "CAPTURE_RETRY_COUNT",
            -1,
            id="negative-retry-count",
        ),
        pytest.param(
            "CAPTURE_RETRY_COUNT",
            False,
            id="boolean-retry-count",
        ),
        pytest.param(
            "CAMERA_WARMUP_SECONDS",
            -0.1,
            id="negative-warmup",
        ),
        pytest.param(
            "CAPTURE_START_DELAY_SECONDS",
            float("inf"),
            id="infinite-start-delay",
        ),
        pytest.param(
            "CAPTURE_INTERVAL_SECONDS",
            float("nan"),
            id="nan-capture-interval",
        ),
        pytest.param(
            "CAPTURE_RETRY_DELAY_SECONDS",
            -0.1,
            id="negative-retry-delay",
        ),
        pytest.param(
            "CAMERA_PIXEL_FORMAT",
            "",
            id="empty-pixel-format",
        ),
        pytest.param(
            "CAMERA_PIXEL_FORMAT",
            "   ",
            id="blank-pixel-format",
        ),
    ],
)
def test_constructor_raises_value_error_for_invalid_setting(
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    invalid_value: object,
) -> None:
    camera_factory = MagicMock()

    monkeypatch.setattr(
        entry_camera,
        setting_name,
        invalid_value,
    )

    with pytest.raises(ValueError) as captured:
        entry_camera.EntryCamera(
            camera_factory=camera_factory,
            sleep=MagicMock(),
        )

    assert not isinstance(
        captured.value,
        entry_camera.CameraInitializationError,
    )
    camera_factory.assert_not_called()


# [프레임 촬영과 이미지 계약]


def test_capture_sequence_returns_six_bgr_frames() -> None:
    rgb_image = make_rgb_image(
        red=10,
        green=20,
        blue=30,
    )
    camera, _ = make_camera(rgb_image)
    instance, camera, _, sleep = make_entry_camera(
        camera=camera,
    )

    frames = instance.capture_sequence()

    assert isinstance(frames, tuple)
    assert len(frames) == entry_camera.CAPTURE_FRAME_COUNT
    assert all(isinstance(frame, CapturedFrame) for frame in frames)
    assert tuple(frame.frame_index for frame in frames) == tuple(
        range(entry_camera.CAPTURE_FRAME_COUNT)
    )

    camera.capture_array.assert_has_calls(
        [
            call("main")
            for _ in range(entry_camera.CAPTURE_FRAME_COUNT)
        ]
    )
    assert camera.capture_array.call_count == (
        entry_camera.CAPTURE_FRAME_COUNT
    )

    for frame in frames:
        assert frame.image.dtype == np.uint8
        assert frame.image.shape == (
            entry_camera.CAMERA_HEIGHT,
            entry_camera.CAMERA_WIDTH,
            3,
        )
        assert tuple(frame.image[0, 0]) == (30, 20, 10)

    assert sleep.call_args_list == [
        call(entry_camera.CAMERA_WARMUP_SECONDS),
        call(entry_camera.CAPTURE_START_DELAY_SECONDS),
        *[
            call(entry_camera.CAPTURE_INTERVAL_SECONDS)
            for _ in range(entry_camera.CAPTURE_FRAME_COUNT - 1)
        ],
    ]
    assert call(
        entry_camera.CAPTURE_RETRY_DELAY_SECONDS
    ) not in sleep.call_args_list


def test_capture_sequence_returns_independent_images() -> None:
    rgb_image = make_rgb_image(
        red=11,
        green=22,
        blue=33,
    )
    camera, _ = make_camera(rgb_image)
    instance, _, _, _ = make_entry_camera(camera=camera)

    frames = instance.capture_sequence()
    expected_pixel = (33, 22, 11)

    assert all(
        not np.shares_memory(frame.image, rgb_image)
        for frame in frames
    )
    assert all(
        frames[index].image is not frames[index + 1].image
        for index in range(len(frames) - 1)
    )

    rgb_image[...] = 0

    assert all(
        tuple(frame.image[0, 0]) == expected_pixel
        for frame in frames
    )


@pytest.mark.parametrize(
    "image_factory",
    [
        pytest.param(
            lambda: None,
            id="none",
        ),
        pytest.param(
            lambda: object(),
            id="non-array",
        ),
        pytest.param(
            lambda: np.empty((0, 0, 3), dtype=np.uint8),
            id="empty-array",
        ),
        pytest.param(
            lambda: np.zeros(
                (
                    entry_camera.CAMERA_HEIGHT,
                    entry_camera.CAMERA_WIDTH,
                    3,
                ),
                dtype=np.float32,
            ),
            id="wrong-dtype",
        ),
        pytest.param(
            lambda: np.zeros((8, 12, 3), dtype=np.uint8),
            id="wrong-shape",
        ),
    ],
)
def test_capture_frame_rejects_invalid_camera_result(
    image_factory: Callable[[], object],
) -> None:
    camera, _ = make_camera()
    instance, camera, _, _ = make_entry_camera(camera=camera)
    camera.capture_array.return_value = image_factory()
    frame_index = 3

    with pytest.raises(
        entry_camera.FrameCaptureError
    ) as captured:
        instance._capture_frame(frame_index)

    assert f"frame_index={frame_index}" in str(captured.value)
    camera.capture_array.assert_called_once_with("main")


def test_capture_frame_preserves_camera_api_error_as_cause() -> None:
    camera, _ = make_camera()
    capture_error = RuntimeError("capture_array 실패")
    camera.capture_array.side_effect = capture_error
    instance, camera, _, _ = make_entry_camera(camera=camera)
    frame_index = 4

    with pytest.raises(
        entry_camera.FrameCaptureError
    ) as captured:
        instance._capture_frame(frame_index)

    assert captured.value.__cause__ is capture_error
    assert f"frame_index={frame_index}" in str(captured.value)
    camera.capture_array.assert_called_once_with("main")


# [재촬영과 촬영 예외]


def test_capture_sequence_retries_entire_sequence_after_frame_failure(
) -> None:
    first_frame = make_rgb_image(
        red=1,
        green=2,
        blue=3,
    )
    retry_frame = make_rgb_image(
        red=90,
        green=91,
        blue=92,
    )
    capture_error = RuntimeError("첫 촬영 묶음 실패")

    camera, _ = make_camera()
    camera.capture_array.side_effect = [
        first_frame,
        first_frame,
        capture_error,
        *[
            retry_frame
            for _ in range(entry_camera.CAPTURE_FRAME_COUNT)
        ],
    ]

    instance, camera, camera_factory, sleep = make_entry_camera(
        camera=camera,
    )

    frames = instance.capture_sequence()

    assert len(frames) == entry_camera.CAPTURE_FRAME_COUNT
    assert tuple(frame.frame_index for frame in frames) == tuple(
        range(entry_camera.CAPTURE_FRAME_COUNT)
    )
    assert all(
        tuple(frame.image[0, 0]) == (92, 91, 90)
        for frame in frames
    )
    assert camera.capture_array.call_count == (
        3 + entry_camera.CAPTURE_FRAME_COUNT
    )
    camera_factory.assert_called_once_with()

    assert sleep.call_args_list == [
        call(entry_camera.CAMERA_WARMUP_SECONDS),
        call(entry_camera.CAPTURE_START_DELAY_SECONDS),
        call(entry_camera.CAPTURE_INTERVAL_SECONDS),
        call(entry_camera.CAPTURE_INTERVAL_SECONDS),
        call(entry_camera.CAPTURE_RETRY_DELAY_SECONDS),
        *[
            call(entry_camera.CAPTURE_INTERVAL_SECONDS)
            for _ in range(entry_camera.CAPTURE_FRAME_COUNT - 1)
        ],
    ]


def test_capture_sequence_raises_after_all_attempts_fail() -> None:
    valid_image = make_rgb_image()
    first_error = RuntimeError("첫 번째 시도 실패")
    second_error = RuntimeError("두 번째 시도 실패")

    camera, _ = make_camera()
    camera.capture_array.side_effect = [
        valid_image,
        first_error,
        second_error,
    ]
    instance, camera, _, sleep = make_entry_camera(camera=camera)
    expected_attempts = entry_camera.CAPTURE_RETRY_COUNT + 1

    with pytest.raises(
        entry_camera.CaptureSequenceError
    ) as captured:
        instance.capture_sequence()

    assert isinstance(
        captured.value.__cause__,
        entry_camera.FrameCaptureError,
    )
    assert f"총 {expected_attempts}회" in str(captured.value)
    assert "frame_index=1" in str(captured.value)
    assert "frame_index=0" in str(captured.value)
    assert camera.capture_array.call_count == 3
    assert sleep.call_args_list == [
        call(entry_camera.CAMERA_WARMUP_SECONDS),
        call(entry_camera.CAPTURE_START_DELAY_SECONDS),
        call(entry_camera.CAPTURE_INTERVAL_SECONDS),
        call(entry_camera.CAPTURE_RETRY_DELAY_SECONDS),
    ]
    camera.stop.assert_not_called()
    camera.close.assert_not_called()

    camera.capture_array.side_effect = None
    camera.capture_array.return_value = valid_image

    frames = instance.capture_sequence()

    assert len(frames) == entry_camera.CAPTURE_FRAME_COUNT
    camera.stop.assert_not_called()
    camera.close.assert_not_called()


# [대기 예외와 종료 신호]


def test_interval_sleep_failure_is_retried_as_frame_capture_error() -> None:
    interval_error = RuntimeError("프레임 간 대기 실패")
    sleep = MagicMock(
        side_effect=[
            None,
            None,
            interval_error,
            None,
            *[
                None
                for _ in range(
                    entry_camera.CAPTURE_FRAME_COUNT - 1
                )
            ],
        ]
    )
    camera, _ = make_camera()
    instance, camera, _, sleep = make_entry_camera(
        camera=camera,
        sleep=sleep,
    )

    frames = instance.capture_sequence()

    assert len(frames) == entry_camera.CAPTURE_FRAME_COUNT
    assert camera.capture_array.call_count == (
        1 + entry_camera.CAPTURE_FRAME_COUNT
    )
    assert sleep.call_args_list == [
        call(entry_camera.CAMERA_WARMUP_SECONDS),
        call(entry_camera.CAPTURE_START_DELAY_SECONDS),
        call(entry_camera.CAPTURE_INTERVAL_SECONDS),
        call(entry_camera.CAPTURE_RETRY_DELAY_SECONDS),
        *[
            call(entry_camera.CAPTURE_INTERVAL_SECONDS)
            for _ in range(entry_camera.CAPTURE_FRAME_COUNT - 1)
        ],
    ]


def test_start_delay_failure_is_propagated_without_capture() -> None:
    start_delay_error = RuntimeError("촬영 시작 대기 실패")
    sleep = MagicMock(
        side_effect=[
            None,
            start_delay_error,
        ]
    )
    camera, _ = make_camera()
    instance, camera, _, _ = make_entry_camera(
        camera=camera,
        sleep=sleep,
    )

    with pytest.raises(RuntimeError) as captured:
        instance.capture_sequence()

    assert captured.value is start_delay_error
    camera.capture_array.assert_not_called()


def test_retry_delay_failure_is_propagated() -> None:
    retry_delay_error = RuntimeError("재촬영 대기 실패")
    sleep = MagicMock(
        side_effect=[
            None,
            None,
            retry_delay_error,
        ]
    )
    camera, _ = make_camera()
    camera.capture_array.side_effect = RuntimeError("첫 촬영 실패")
    instance, camera, _, _ = make_entry_camera(
        camera=camera,
        sleep=sleep,
    )

    with pytest.raises(RuntimeError) as captured:
        instance.capture_sequence()

    assert captured.value is retry_delay_error
    camera.capture_array.assert_called_once_with("main")


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(),
            id="system-exit",
        ),
    ],
)
def test_capture_array_termination_is_propagated_without_retry(
    termination: BaseException,
) -> None:
    camera, _ = make_camera()
    camera.capture_array.side_effect = termination
    instance, camera, _, sleep = make_entry_camera(camera=camera)

    with pytest.raises(type(termination)) as captured:
        instance.capture_sequence()

    assert captured.value is termination
    camera.capture_array.assert_called_once_with("main")
    assert sleep.call_args_list == [
        call(entry_camera.CAMERA_WARMUP_SECONDS),
        call(entry_camera.CAPTURE_START_DELAY_SECONDS),
    ]


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(),
            id="system-exit",
        ),
    ],
)
def test_interval_sleep_termination_is_propagated_without_retry(
    termination: BaseException,
) -> None:
    sleep = MagicMock(
        side_effect=[
            None,
            None,
            termination,
        ]
    )
    camera, _ = make_camera()
    instance, camera, _, _ = make_entry_camera(
        camera=camera,
        sleep=sleep,
    )

    with pytest.raises(type(termination)) as captured:
        instance.capture_sequence()

    assert captured.value is termination
    camera.capture_array.assert_called_once_with("main")


# [초기화 실패]


def test_factory_failure_is_wrapped_as_initialization_error() -> None:
    initialization_error = RuntimeError("camera factory 실패")
    camera_factory = MagicMock(side_effect=initialization_error)

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=camera_factory,
            sleep=MagicMock(),
        )

    assert captured.value.__cause__ is initialization_error
    camera_factory.assert_called_once_with()


def test_factory_none_result_raises_initialization_error() -> None:
    camera_factory = MagicMock(return_value=None)

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=camera_factory,
            sleep=MagicMock(),
        )

    assert isinstance(
        captured.value.__cause__,
        entry_camera.CameraInitializationError,
    )


def test_create_still_configuration_failure_closes_camera_without_start(
) -> None:
    camera, _ = make_camera()
    configuration_error = RuntimeError(
        "create_still_configuration 실패"
    )
    camera.create_still_configuration.side_effect = configuration_error

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=MagicMock(return_value=camera),
            sleep=MagicMock(),
        )

    assert captured.value.__cause__ is configuration_error
    camera.create_still_configuration.assert_called_once_with(
        main={
            "size": (
                entry_camera.CAMERA_WIDTH,
                entry_camera.CAMERA_HEIGHT,
            ),
            "format": entry_camera.CAMERA_PIXEL_FORMAT,
        }
    )
    camera.configure.assert_not_called()
    camera.start.assert_not_called()
    camera.stop.assert_not_called()
    camera.close.assert_called_once_with()


def test_configure_failure_closes_camera_without_stop() -> None:
    camera, configuration = make_camera()
    configure_error = RuntimeError("configure 실패")
    camera.configure.side_effect = configure_error

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=MagicMock(return_value=camera),
            sleep=MagicMock(),
        )

    camera.create_still_configuration.assert_called_once()
    camera.configure.assert_called_once_with(configuration)
    camera.stop.assert_not_called()
    camera.close.assert_called_once_with()
    assert captured.value.__cause__ is configure_error


def test_start_failure_closes_camera_without_stop() -> None:
    camera, _ = make_camera()
    start_error = RuntimeError("start 실패")
    camera.start.side_effect = start_error

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=MagicMock(return_value=camera),
            sleep=MagicMock(),
        )

    camera.stop.assert_not_called()
    camera.close.assert_called_once_with()
    assert captured.value.__cause__ is start_error


def test_warmup_failure_stops_and_closes_camera() -> None:
    camera, _ = make_camera()
    warmup_error = RuntimeError("warm-up 실패")
    sleep = MagicMock(side_effect=warmup_error)

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=MagicMock(return_value=camera),
            sleep=sleep,
        )

    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()
    assert captured.value.__cause__ is warmup_error


def test_warmup_keyboard_interrupt_cleans_up_and_propagates() -> None:
    camera, _ = make_camera()
    interruption = KeyboardInterrupt()
    sleep = MagicMock(side_effect=interruption)

    with pytest.raises(KeyboardInterrupt) as captured:
        entry_camera.EntryCamera(
            camera_factory=MagicMock(return_value=camera),
            sleep=sleep,
        )

    assert captured.value is interruption
    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()


def test_initialization_error_reports_cleanup_failure() -> None:
    camera, _ = make_camera()
    initialization_error = RuntimeError("configure 실패")
    cleanup_error = RuntimeError("close 실패")
    camera.configure.side_effect = initialization_error
    camera.close.side_effect = cleanup_error

    with pytest.raises(
        entry_camera.CameraInitializationError
    ) as captured:
        entry_camera.EntryCamera(
            camera_factory=MagicMock(return_value=camera),
            sleep=MagicMock(),
        )

    assert captured.value.__cause__ is initialization_error
    assert "자원 정리도 실패" in str(captured.value)
    camera.close.assert_called_once_with()


# [자원 정리]


def test_cleanup_stops_then_closes_and_is_idempotent() -> None:
    instance, camera, _, _ = make_entry_camera()
    calls = MagicMock()

    calls.attach_mock(camera.stop, "stop")
    calls.attach_mock(camera.close, "close")

    instance.cleanup()

    assert calls.mock_calls == [
        call.stop(),
        call.close(),
    ]

    with pytest.raises(entry_camera.CameraError):
        instance.capture_sequence()

    instance.cleanup()

    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()


def test_cleanup_stop_success_close_failure_retries_only_close() -> None:
    instance, camera, _, _ = make_entry_camera()
    close_error = RuntimeError("close 실패")
    camera.close.side_effect = [
        close_error,
        None,
    ]

    with pytest.raises(entry_camera.CameraError) as captured:
        instance.cleanup()

    assert captured.value.__cause__ is close_error
    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()

    instance.cleanup()

    camera.stop.assert_called_once_with()
    assert camera.close.call_count == 2

    instance.cleanup()

    camera.stop.assert_called_once_with()
    assert camera.close.call_count == 2


def test_cleanup_stop_failure_close_failure_retries_both() -> None:
    instance, camera, _, _ = make_entry_camera()
    stop_error = RuntimeError("stop 실패")
    close_error = RuntimeError("close 실패")
    calls = MagicMock()

    camera.stop.side_effect = [
        stop_error,
        None,
    ]
    camera.close.side_effect = [
        close_error,
        None,
    ]
    calls.attach_mock(camera.stop, "stop")
    calls.attach_mock(camera.close, "close")

    with pytest.raises(entry_camera.CameraError) as captured:
        instance.cleanup()

    assert captured.value.__cause__ is stop_error
    assert calls.mock_calls == [
        call.stop(),
        call.close(),
    ]

    instance.cleanup()

    assert camera.stop.call_count == 2
    assert camera.close.call_count == 2

    instance.cleanup()

    assert camera.stop.call_count == 2
    assert camera.close.call_count == 2


def test_cleanup_stop_failure_close_success_completes_cleanup() -> None:
    instance, camera, _, _ = make_entry_camera()
    stop_error = RuntimeError("stop 실패")
    camera.stop.side_effect = stop_error

    with pytest.raises(entry_camera.CameraError) as captured:
        instance.cleanup()

    assert captured.value.__cause__ is stop_error
    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()

    instance.cleanup()

    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()


@pytest.mark.parametrize(
    "termination",
    [
        pytest.param(
            KeyboardInterrupt(),
            id="keyboard-interrupt",
        ),
        pytest.param(
            SystemExit(),
            id="system-exit",
        ),
    ],
)
def test_cleanup_stop_termination_closes_then_propagates(
    termination: BaseException,
) -> None:
    instance, camera, _, _ = make_entry_camera()
    camera.stop.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        instance.cleanup()

    assert captured.value is termination
    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()

    instance.cleanup()

    camera.stop.assert_called_once_with()
    camera.close.assert_called_once_with()
