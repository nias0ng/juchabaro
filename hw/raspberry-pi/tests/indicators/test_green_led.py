"""
실제 Raspberry Pi GPIO 없이 GreenLed의 출력과 자원 관리 계약을 검증한다.

설정 검증, 논리 극성, 동기 점등, 예외 복구 및 핀 단위 cleanup을 mock으로
확인한다. 실제 LED 회로와 시간 경과, Backend 입차 판정 연결은 검증하지
않는다.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, call, patch

import pytest


gpio_stub = ModuleType("RPi.GPIO")
gpio_stub.BCM = 11
gpio_stub.OUT = 0
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
    from src.indicators import green_led


ALLOW_DURATION_SECONDS = 3.0


# [테스트 생성 도우미]


def make_gpio() -> MagicMock:
    """GreenLed가 사용하는 최소 GPIO 인터페이스를 가진 mock을 생성한다."""

    gpio = MagicMock()
    gpio.BCM = gpio_stub.BCM
    gpio.OUT = gpio_stub.OUT
    gpio.LOW = gpio_stub.LOW
    gpio.HIGH = gpio_stub.HIGH
    return gpio


def make_led(
    *,
    gpio: MagicMock | None = None,
    sleep: MagicMock | None = None,
) -> tuple[green_led.GreenLed, MagicMock, MagicMock]:
    """주입한 mock과 함께 초기화된 GreenLed를 반환한다."""

    if gpio is None:
        gpio = make_gpio()
    if sleep is None:
        sleep = MagicMock()

    led = green_led.GreenLed(
        gpio=gpio,
        sleep=sleep,
    )
    return led, gpio, sleep


# [설정 검증과 초기화]


@pytest.mark.parametrize(
    ("setting_name", "invalid_value"),
    [
        pytest.param(
            "GPIO_MODE",
            "BOARD",
            id="non-bcm-mode",
        ),
        pytest.param(
            "GREEN_LED_PIN",
            True,
            id="boolean-pin",
        ),
        pytest.param(
            "GREEN_LED_PIN",
            17.0,
            id="non-integer-pin",
        ),
        pytest.param(
            "GREEN_LED_PIN",
            -1,
            id="negative-pin",
        ),
        pytest.param(
            "GREEN_LED_ACTIVE_HIGH",
            1,
            id="non-boolean-active-high",
        ),
    ],
)
def test_constructor_rejects_invalid_setting_without_gpio_access(
    monkeypatch: pytest.MonkeyPatch,
    setting_name: str,
    invalid_value: object,
) -> None:
    gpio = make_gpio()
    sleep = MagicMock()
    monkeypatch.setattr(
        green_led,
        setting_name,
        invalid_value,
    )

    with pytest.raises(ValueError):
        green_led.GreenLed(
            gpio=gpio,
            sleep=sleep,
        )

    gpio.setmode.assert_not_called()
    gpio.setup.assert_not_called()
    gpio.output.assert_not_called()
    gpio.cleanup.assert_not_called()
    sleep.assert_not_called()


def test_constructor_rejects_unsupported_gpio_mode() -> None:
    gpio = make_gpio()
    gpio.BCM = None

    with pytest.raises(ValueError):
        green_led.GreenLed(
            gpio=gpio,
            sleep=MagicMock(),
        )

    gpio.setmode.assert_not_called()
    gpio.setup.assert_not_called()
    gpio.output.assert_not_called()
    gpio.cleanup.assert_not_called()


@pytest.mark.parametrize(
    ("active_high", "expected_off_level"),
    [
        pytest.param(
            True,
            gpio_stub.LOW,
            id="active-high",
        ),
        pytest.param(
            False,
            gpio_stub.HIGH,
            id="active-low",
        ),
    ],
)
def test_constructor_initializes_gpio_in_order(
    monkeypatch: pytest.MonkeyPatch,
    active_high: bool,
    expected_off_level: int,
) -> None:
    gpio = make_gpio()
    calls = MagicMock()
    monkeypatch.setattr(
        green_led,
        "GREEN_LED_ACTIVE_HIGH",
        active_high,
    )

    calls.attach_mock(gpio.setmode, "setmode")
    calls.attach_mock(gpio.setup, "setup")
    calls.attach_mock(gpio.output, "output")

    green_led.GreenLed(
        gpio=gpio,
        sleep=MagicMock(),
    )

    assert calls.mock_calls == [
        call.setmode(gpio.BCM),
        call.setup(green_led.GREEN_LED_PIN, gpio.OUT),
        call.output(
            green_led.GREEN_LED_PIN,
            expected_off_level,
        ),
    ]


# [공개 LED 제어]


@pytest.mark.parametrize(
    ("active_high", "expected_on_level", "expected_off_level"),
    [
        pytest.param(
            True,
            gpio_stub.HIGH,
            gpio_stub.LOW,
            id="active-high",
        ),
        pytest.param(
            False,
            gpio_stub.LOW,
            gpio_stub.HIGH,
            id="active-low",
        ),
    ],
)
def test_turn_on_and_off_use_polarity_levels(
    monkeypatch: pytest.MonkeyPatch,
    active_high: bool,
    expected_on_level: int,
    expected_off_level: int,
) -> None:
    monkeypatch.setattr(
        green_led,
        "GREEN_LED_ACTIVE_HIGH",
        active_high,
    )
    led, gpio, _ = make_led()
    gpio.output.reset_mock()

    led.turn_on()
    led.turn_off()

    assert gpio.output.call_args_list == [
        call(
            green_led.GREEN_LED_PIN,
            expected_on_level,
        ),
        call(
            green_led.GREEN_LED_PIN,
            expected_off_level,
        ),
    ]


def test_turn_on_propagates_gpio_error() -> None:
    led, gpio, _ = make_led()
    gpio.output.reset_mock()
    gpio_error = RuntimeError("GPIO ON 실패")
    gpio.output.side_effect = gpio_error

    with pytest.raises(RuntimeError) as captured:
        led.turn_on()

    assert captured.value is gpio_error
    gpio.output.assert_called_once_with(
        green_led.GREEN_LED_PIN,
        gpio.HIGH,
    )


# [허용 점등]


@pytest.mark.parametrize(
    "invalid_duration",
    [
        pytest.param(True, id="boolean"),
        pytest.param(0, id="zero"),
        pytest.param(-0.1, id="negative"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param("3.0", id="string"),
        pytest.param(object(), id="object"),
    ],
)
def test_indicate_allow_rejects_invalid_duration_without_output(
    invalid_duration: object,
) -> None:
    led, gpio, sleep = make_led()
    gpio.output.reset_mock()

    with pytest.raises(ValueError):
        led.indicate_allow(invalid_duration)

    gpio.output.assert_not_called()
    sleep.assert_not_called()


def test_indicate_allow_turns_on_waits_and_turns_off_in_order() -> None:
    led, gpio, sleep = make_led()
    calls = MagicMock()
    gpio.output.reset_mock()

    calls.attach_mock(gpio.output, "output")
    calls.attach_mock(sleep, "sleep")

    led.indicate_allow(ALLOW_DURATION_SECONDS)

    assert calls.mock_calls == [
        call.output(
            green_led.GREEN_LED_PIN,
            gpio.HIGH,
        ),
        call.sleep(ALLOW_DURATION_SECONDS),
        call.output(
            green_led.GREEN_LED_PIN,
            gpio.LOW,
        ),
    ]


@pytest.mark.parametrize(
    "sleep_error",
    [
        pytest.param(
            RuntimeError("sleep 실패"),
            id="runtime-error",
        ),
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
def test_indicate_allow_preserves_sleep_error_and_turns_off(
    sleep_error: BaseException,
) -> None:
    sleep = MagicMock(side_effect=sleep_error)
    led, gpio, _ = make_led(sleep=sleep)
    gpio.output.reset_mock()

    with pytest.raises(type(sleep_error)) as captured:
        led.indicate_allow(ALLOW_DURATION_SECONDS)

    assert captured.value is sleep_error
    assert gpio.output.call_args_list == [
        call(
            green_led.GREEN_LED_PIN,
            gpio.HIGH,
        ),
        call(
            green_led.GREEN_LED_PIN,
            gpio.LOW,
        ),
    ]


def test_indicate_allow_attempts_off_after_turn_on_failure() -> None:
    led, gpio, sleep = make_led()
    gpio.output.reset_mock()
    on_error = RuntimeError("GPIO ON 실패")
    gpio.output.side_effect = [
        on_error,
        None,
    ]

    with pytest.raises(RuntimeError) as captured:
        led.indicate_allow(ALLOW_DURATION_SECONDS)

    assert captured.value is on_error
    assert gpio.output.call_args_list == [
        call(
            green_led.GREEN_LED_PIN,
            gpio.HIGH,
        ),
        call(
            green_led.GREEN_LED_PIN,
            gpio.LOW,
        ),
    ]
    sleep.assert_not_called()


def test_indicate_allow_records_off_failure_on_operation_error() -> None:
    operation_error = RuntimeError("sleep 실패")
    off_error = OSError("GPIO OFF 실패")
    sleep = MagicMock(side_effect=operation_error)
    led, gpio, _ = make_led(sleep=sleep)
    gpio.output.reset_mock()
    gpio.output.side_effect = [
        None,
        off_error,
    ]

    with pytest.raises(RuntimeError) as captured:
        led.indicate_allow(ALLOW_DURATION_SECONDS)

    assert captured.value is operation_error
    assert any(
        repr(off_error) in note
        for note in captured.value.__notes__
    )


def test_indicate_allow_propagates_final_off_failure() -> None:
    led, gpio, sleep = make_led()
    gpio.output.reset_mock()
    off_error = RuntimeError("최종 GPIO OFF 실패")
    gpio.output.side_effect = [
        None,
        off_error,
    ]

    with pytest.raises(RuntimeError) as captured:
        led.indicate_allow(ALLOW_DURATION_SECONDS)

    assert captured.value is off_error
    sleep.assert_called_once_with(ALLOW_DURATION_SECONDS)


# [초기화 실패]


@pytest.mark.parametrize(
    ("failure_stage", "cleanup_expected"),
    [
        pytest.param(
            "setmode",
            False,
            id="setmode-failure",
        ),
        pytest.param(
            "setup",
            True,
            id="setup-failure",
        ),
        pytest.param(
            "initial-off",
            True,
            id="initial-off-failure",
        ),
    ],
)
def test_constructor_cleans_partial_initialization_as_required(
    failure_stage: str,
    cleanup_expected: bool,
) -> None:
    gpio = make_gpio()
    initialization_error = RuntimeError(
        f"{failure_stage} 실패"
    )

    if failure_stage == "setmode":
        gpio.setmode.side_effect = initialization_error
    elif failure_stage == "setup":
        gpio.setup.side_effect = initialization_error
    else:
        gpio.output.side_effect = [
            initialization_error,
            None,
        ]

    with pytest.raises(RuntimeError) as captured:
        green_led.GreenLed(
            gpio=gpio,
            sleep=MagicMock(),
        )

    assert captured.value is initialization_error

    if cleanup_expected:
        gpio.cleanup.assert_called_once_with(
            green_led.GREEN_LED_PIN
        )
    else:
        gpio.cleanup.assert_not_called()


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
def test_constructor_cleans_pin_and_preserves_termination(
    termination: BaseException,
) -> None:
    gpio = make_gpio()
    gpio.setup.side_effect = termination

    with pytest.raises(type(termination)) as captured:
        green_led.GreenLed(
            gpio=gpio,
            sleep=MagicMock(),
        )

    assert captured.value is termination
    gpio.cleanup.assert_called_once_with(
        green_led.GREEN_LED_PIN
    )


def test_constructor_preserves_initialization_error_when_cleanup_fails(
) -> None:
    gpio = make_gpio()
    initialization_error = RuntimeError("초기 OFF 출력 실패")
    cleanup_error = OSError("GPIO cleanup 실패")
    gpio.output.side_effect = [
        initialization_error,
        None,
    ]
    gpio.cleanup.side_effect = cleanup_error

    with pytest.raises(RuntimeError) as captured:
        green_led.GreenLed(
            gpio=gpio,
            sleep=MagicMock(),
        )

    assert captured.value is initialization_error
    assert any(
        f"pin={green_led.GREEN_LED_PIN}" in note
        and repr(cleanup_error) in note
        for note in captured.value.__notes__
    )
    gpio.cleanup.assert_called_once_with(
        green_led.GREEN_LED_PIN
    )


# [자원 정리]


def test_cleanup_turns_off_releases_owned_pin_and_is_idempotent() -> None:
    led, gpio, _ = make_led()
    calls = MagicMock()
    gpio.output.reset_mock()
    gpio.cleanup.reset_mock()

    calls.attach_mock(gpio.output, "output")
    calls.attach_mock(gpio.cleanup, "cleanup")

    led.cleanup()
    led.cleanup()

    assert calls.mock_calls == [
        call.output(
            green_led.GREEN_LED_PIN,
            gpio.LOW,
        ),
        call.cleanup(green_led.GREEN_LED_PIN),
    ]
    gpio.cleanup.assert_called_once_with(
        green_led.GREEN_LED_PIN
    )


def test_cleanup_off_failure_completes_pin_cleanup() -> None:
    led, gpio, _ = make_led()
    gpio.output.reset_mock()
    gpio.cleanup.reset_mock()
    off_error = RuntimeError("cleanup OFF 실패")
    gpio.output.side_effect = off_error

    with pytest.raises(RuntimeError) as captured:
        led.cleanup()

    assert captured.value is off_error
    gpio.output.assert_called_once_with(
        green_led.GREEN_LED_PIN,
        gpio.LOW,
    )
    gpio.cleanup.assert_called_once_with(
        green_led.GREEN_LED_PIN
    )

    led.cleanup()

    gpio.output.assert_called_once()
    gpio.cleanup.assert_called_once()


def test_cleanup_pin_failure_can_be_retried_and_disables_control(
) -> None:
    led, gpio, _ = make_led()
    gpio.output.reset_mock()
    gpio.cleanup.reset_mock()
    cleanup_error = RuntimeError("GPIO cleanup 실패")
    gpio.cleanup.side_effect = [
        cleanup_error,
        None,
    ]

    with pytest.raises(RuntimeError) as captured:
        led.cleanup()

    assert captured.value is cleanup_error

    with pytest.raises(RuntimeError):
        led.turn_on()

    led.cleanup()

    assert gpio.output.call_args_list == [
        call(
            green_led.GREEN_LED_PIN,
            gpio.LOW,
        ),
        call(
            green_led.GREEN_LED_PIN,
            gpio.LOW,
        ),
    ]
    assert gpio.cleanup.call_args_list == [
        call(green_led.GREEN_LED_PIN),
        call(green_led.GREEN_LED_PIN),
    ]


@pytest.mark.parametrize(
    "method_name",
    [
        pytest.param("turn_on", id="turn-on"),
        pytest.param("turn_off", id="turn-off"),
        pytest.param("indicate_allow", id="indicate-allow"),
    ],
)
def test_public_control_is_rejected_after_cleanup(
    method_name: str,
) -> None:
    led, gpio, sleep = make_led()
    led.cleanup()
    gpio.output.reset_mock()
    gpio.cleanup.reset_mock()
    sleep.reset_mock()

    method = getattr(led, method_name)

    with pytest.raises(RuntimeError):
        if method_name == "indicate_allow":
            method(0)
        else:
            method()

    gpio.output.assert_not_called()
    gpio.cleanup.assert_not_called()
    sleep.assert_not_called()
