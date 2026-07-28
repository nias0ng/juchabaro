import math
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
    from src.sensors import ultrasonic_sensor


def make_gpio() -> MagicMock:
    gpio = MagicMock()
    gpio.BCM = gpio_stub.BCM
    gpio.OUT = gpio_stub.OUT
    gpio.IN = gpio_stub.IN
    gpio.LOW = gpio_stub.LOW
    gpio.HIGH = gpio_stub.HIGH
    return gpio


def make_sensor(
    *,
    gpio: MagicMock | None = None,
    monotonic: MagicMock | None = None,
) -> tuple[
    ultrasonic_sensor.UltrasonicSensor,
    MagicMock,
    MagicMock,
]:
    if gpio is None:
        gpio = make_gpio()
    if monotonic is None:
        monotonic = MagicMock(return_value=0.0)

    sleep = MagicMock()
    sensor = ultrasonic_sensor.UltrasonicSensor(
        gpio=gpio,
        monotonic=monotonic,
        sleep=sleep,
    )

    return sensor, gpio, sleep


def test_constructor_initializes_gpio() -> None:
    _, gpio, _ = make_sensor()

    gpio.setmode.assert_called_once_with(gpio.BCM)
    assert gpio.setup.call_args_list == [
        call(ultrasonic_sensor.TRIGGER_PIN, gpio.OUT),
        call(ultrasonic_sensor.ECHO_PIN, gpio.IN),
    ]
    gpio.output.assert_called_once_with(
        ultrasonic_sensor.TRIGGER_PIN,
        gpio.LOW,
    )


def test_constructor_waits_for_sensor_stabilization() -> None:
    _, _, sleep = make_sensor()

    sleep.assert_called_once_with(
        ultrasonic_sensor.STABILIZATION_SECONDS
    )


def test_measure_returns_expected_distance_for_valid_echo_duration() -> None:
    sensor, _, _ = make_sensor()
    echo_start_time = 1.0
    echo_duration_seconds = 0.001
    echo_end_time = echo_start_time + echo_duration_seconds
    expected_distance = (
        (echo_end_time - echo_start_time)
        * ultrasonic_sensor.SOUND_SPEED_CM_PER_SECOND
        / 2
    )

    with patch.object(
        sensor,
        "_wait_for_echo_level",
        side_effect=[echo_start_time, echo_end_time],
    ):
        result = sensor.measure()

    assert result == pytest.approx(expected_distance)


def test_measure_sends_trigger_pulse_in_order() -> None:
    sensor, gpio, sleep = make_sensor()
    gpio.output.reset_mock()
    sleep.reset_mock()

    # gpio.output()과 sleep() 사이의 전체 호출 순서를 검증하기 위한 부모 Mock
    pulse_calls = MagicMock()
    pulse_calls.attach_mock(gpio.output, "output")
    pulse_calls.attach_mock(sleep, "sleep")

    with patch.object(
        sensor,
        "_wait_for_echo_level",
        side_effect=[1.0, 1.001],
    ):
        sensor.measure()

    assert pulse_calls.mock_calls == [
        call.output(
            ultrasonic_sensor.TRIGGER_PIN,
            gpio.HIGH,
        ),
        call.sleep(
            ultrasonic_sensor.TRIGGER_PULSE_SECONDS
        ),
        call.output(
            ultrasonic_sensor.TRIGGER_PIN,
            gpio.LOW,
        ),
    ]


def test_measure_returns_none_when_echo_rising_times_out() -> None:
    gpio = make_gpio()
    gpio.input.return_value = gpio.LOW

    wait_started_at = 0.0
    timeout_margin_seconds = 0.001
    timeout_exceeded_at = (
        wait_started_at
        + ultrasonic_sensor.ECHO_TIMEOUT_SECONDS
        + timeout_margin_seconds
    )
    monotonic = MagicMock(
        side_effect=[
            wait_started_at,
            timeout_exceeded_at,
        ]
    )
    sensor, _, _ = make_sensor(gpio=gpio, monotonic=monotonic)

    result = sensor.measure()

    assert result is None


def test_measure_returns_none_when_echo_falling_times_out() -> None:
    gpio = make_gpio()
    gpio.input.side_effect = [gpio.HIGH, gpio.HIGH]

    rising_wait_started_at = 0.0
    echo_detected_at = 0.001
    falling_wait_started_at = echo_detected_at
    timeout_margin_seconds = 0.001
    timeout_exceeded_at = (
        falling_wait_started_at
        + ultrasonic_sensor.ECHO_TIMEOUT_SECONDS
        + timeout_margin_seconds
    )
    monotonic = MagicMock(
        side_effect=[
            rising_wait_started_at,
            echo_detected_at,
            falling_wait_started_at,
            timeout_exceeded_at,
        ]
    )
    sensor, _, _ = make_sensor(gpio=gpio, monotonic=monotonic)

    result = sensor.measure()

    assert result is None


def test_measure_returns_none_below_minimum_distance() -> None:
    sensor, _, _ = make_sensor()
    distance_cm = ultrasonic_sensor.MIN_VALID_DISTANCE_CM - 0.1
    elapsed_seconds = (
        distance_cm * 2 / ultrasonic_sensor.SOUND_SPEED_CM_PER_SECOND
    )

    with patch.object(
        sensor,
        "_wait_for_echo_level",
        side_effect=[1.0, 1.0 + elapsed_seconds],
    ):
        result = sensor.measure()

    assert result is None


def test_measure_returns_none_above_maximum_distance() -> None:
    sensor, _, _ = make_sensor()
    distance_cm = ultrasonic_sensor.MAX_VALID_DISTANCE_CM + 0.1
    elapsed_seconds = (
        distance_cm * 2 / ultrasonic_sensor.SOUND_SPEED_CM_PER_SECOND
    )

    with patch.object(
        sensor,
        "_wait_for_echo_level",
        side_effect=[1.0, 1.0 + elapsed_seconds],
    ):
        result = sensor.measure()

    assert result is None


def test_measure_returns_none_for_nan() -> None:
    sensor, _, _ = make_sensor()

    with patch.object(
        sensor,
        "_wait_for_echo_level",
        side_effect=[0.0, math.nan],
    ):
        result = sensor.measure()

    assert result is None


def test_measure_returns_none_for_infinity() -> None:
    sensor, _, _ = make_sensor()

    with patch.object(
        sensor,
        "_wait_for_echo_level",
        side_effect=[0.0, math.inf],
    ):
        result = sensor.measure()

    assert result is None


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        pytest.param("GPIO_MODE", "BOARD", id="non-bcm-mode"),
        pytest.param(
            "ECHO_PIN",
            ultrasonic_sensor.TRIGGER_PIN,
            id="same-trigger-and-echo-pin",
        ),
        pytest.param(
            "TRIGGER_PULSE_SECONDS",
            0.0,
            id="non-positive-trigger-pulse",
        ),
        pytest.param(
            "STABILIZATION_SECONDS",
            0.0,
            id="non-positive-stabilization",
        ),
        pytest.param(
            "ECHO_TIMEOUT_SECONDS",
            0.0,
            id="non-positive-echo-timeout",
        ),
        pytest.param(
            "SOUND_SPEED_CM_PER_SECOND",
            0.0,
            id="non-positive-sound-speed",
        ),
        pytest.param(
            "MIN_VALID_DISTANCE_CM",
            ultrasonic_sensor.MAX_VALID_DISTANCE_CM,
            id="minimum-distance-equals-maximum",
        ),
        pytest.param(
            "MAX_VALID_DISTANCE_CM",
            ultrasonic_sensor.MIN_VALID_DISTANCE_CM - 0.1,
            id="maximum-distance-below-minimum",
        ),
    ],
)
def test_constructor_raises_for_invalid_setting(
    setting_name: str,
    invalid_value: object,
) -> None:
    gpio = make_gpio()

    with patch.object(ultrasonic_sensor, setting_name, invalid_value):
        with pytest.raises(ValueError):
            ultrasonic_sensor.UltrasonicSensor(
                gpio=gpio,
                monotonic=MagicMock(),
                sleep=MagicMock(),
            )


def test_cleanup_releases_only_sensor_pins() -> None:
    sensor, gpio, _ = make_sensor()

    sensor.cleanup()

    gpio.cleanup.assert_called_once_with(
        (
            ultrasonic_sensor.TRIGGER_PIN,
            ultrasonic_sensor.ECHO_PIN,
        )
    )
