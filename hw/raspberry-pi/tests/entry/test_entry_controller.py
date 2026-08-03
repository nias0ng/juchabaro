import math

import pytest

from src.entry.entry_controller import (
    EntryController,
    EntrySignal,
    EntryState,
)


ENTRY_THRESHOLD_CM = 6.0
RELEASE_THRESHOLD_CM = 10.0
ENTRY_DISTANCE_CM = 5.0
MIDDLE_DISTANCE_CM = 8.0
RELEASE_DISTANCE_CM = 11.0
REQUIRED_DETECTION_COUNT = 3
REQUIRED_RELEASE_COUNT = 3


def make_controller(
    *,
    entry_threshold_cm: float = ENTRY_THRESHOLD_CM,
    release_threshold_cm: float = RELEASE_THRESHOLD_CM,
    required_detection_count: int = REQUIRED_DETECTION_COUNT,
    required_release_count: int = REQUIRED_RELEASE_COUNT,
) -> EntryController:
    return EntryController(
        entry_threshold_cm=entry_threshold_cm,
        release_threshold_cm=release_threshold_cm,
        required_detection_count=required_detection_count,
        required_release_count=required_release_count,
    )


def move_to_occupied(controller: EntryController) -> None:
    for _ in range(REQUIRED_DETECTION_COUNT):
        controller.update(ENTRY_DISTANCE_CM)


def test_constructor_starts_in_idle_state() -> None:
    controller = make_controller()

    assert controller.state is EntryState.IDLE


def test_first_entry_measurement_moves_to_detecting() -> None:
    controller = make_controller()

    signal = controller.update(ENTRY_DISTANCE_CM)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.DETECTING


def test_entry_measurements_return_none_before_required_count() -> None:
    controller = make_controller()

    signals = [
        controller.update(ENTRY_DISTANCE_CM)
        for _ in range(REQUIRED_DETECTION_COUNT - 1)
    ]

    assert signals == [
        EntrySignal.NONE
    ] * (REQUIRED_DETECTION_COUNT - 1)
    assert controller.state is EntryState.DETECTING


def test_required_entry_measurement_returns_signal_and_occupied() -> None:
    controller = make_controller()

    for _ in range(REQUIRED_DETECTION_COUNT - 1):
        controller.update(ENTRY_DISTANCE_CM)

    signal = controller.update(ENTRY_DISTANCE_CM)

    assert signal is EntrySignal.ENTRY_DETECTED
    assert controller.state is EntryState.OCCUPIED


def test_detection_count_one_confirms_entry_immediately() -> None:
    controller = make_controller(required_detection_count=1)

    signal = controller.update(ENTRY_DISTANCE_CM)

    assert signal is EntrySignal.ENTRY_DETECTED
    assert controller.state is EntryState.OCCUPIED


def test_occupied_does_not_emit_duplicate_entry_signal() -> None:
    controller = make_controller()
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signals = [
        controller.update(ENTRY_DISTANCE_CM)
        for _ in range(5)
    ]

    assert signals == [EntrySignal.NONE] * 5
    assert controller.state is EntryState.OCCUPIED


def test_middle_distance_keeps_occupied() -> None:
    controller = make_controller()
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signal = controller.update(MIDDLE_DISTANCE_CM)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.OCCUPIED


@pytest.mark.parametrize(
    "interruption_distance_cm",
    [
        pytest.param(
            MIDDLE_DISTANCE_CM,
            id="middle-distance",
        ),
        pytest.param(
            RELEASE_DISTANCE_CM,
            id="release-distance",
        ),
    ],
)
def test_detection_interruption_returns_to_idle_and_resets_count(
    interruption_distance_cm: float,
) -> None:
    controller = make_controller()
    controller.update(ENTRY_DISTANCE_CM)
    assert controller.state is EntryState.DETECTING

    signal = controller.update(interruption_distance_cm)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE

    signals = [
        controller.update(ENTRY_DISTANCE_CM)
        for _ in range(REQUIRED_DETECTION_COUNT - 1)
    ]

    assert signals == [
        EntrySignal.NONE
    ] * (REQUIRED_DETECTION_COUNT - 1)
    assert controller.state is EntryState.DETECTING

    final_signal = controller.update(ENTRY_DISTANCE_CM)

    assert final_signal is EntrySignal.ENTRY_DETECTED
    assert controller.state is EntryState.OCCUPIED


@pytest.mark.parametrize(
    "invalid_distance_cm",
    [
        pytest.param(None, id="none"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
    ],
)
def test_invalid_measurement_keeps_idle(
    invalid_distance_cm: float | None,
) -> None:
    controller = make_controller()

    signal = controller.update(invalid_distance_cm)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE


@pytest.mark.parametrize(
    "invalid_distance_cm",
    [
        pytest.param(None, id="none"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
    ],
)
def test_invalid_measurement_cancels_detection_and_resets_count(
    invalid_distance_cm: float | None,
) -> None:
    controller = make_controller()
    controller.update(ENTRY_DISTANCE_CM)
    assert controller.state is EntryState.DETECTING

    signal = controller.update(invalid_distance_cm)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE

    signals = [
        controller.update(ENTRY_DISTANCE_CM)
        for _ in range(REQUIRED_DETECTION_COUNT - 1)
    ]

    assert signals == [
        EntrySignal.NONE
    ] * (REQUIRED_DETECTION_COUNT - 1)
    assert controller.state is EntryState.DETECTING

    final_signal = controller.update(ENTRY_DISTANCE_CM)

    assert final_signal is EntrySignal.ENTRY_DETECTED
    assert controller.state is EntryState.OCCUPIED


def test_first_release_measurement_moves_to_releasing() -> None:
    controller = make_controller()
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signal = controller.update(RELEASE_DISTANCE_CM)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.RELEASING


def test_release_measurements_return_none_before_required_count() -> None:
    controller = make_controller()
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signals = [
        controller.update(RELEASE_DISTANCE_CM)
        for _ in range(REQUIRED_RELEASE_COUNT - 1)
    ]

    assert signals == [
        EntrySignal.NONE
    ] * (REQUIRED_RELEASE_COUNT - 1)
    assert controller.state is EntryState.RELEASING


def test_required_release_measurement_returns_none_and_idle() -> None:
    controller = make_controller()
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signals = [
        controller.update(RELEASE_DISTANCE_CM)
        for _ in range(REQUIRED_RELEASE_COUNT)
    ]

    assert signals == [
        EntrySignal.NONE
    ] * REQUIRED_RELEASE_COUNT
    assert controller.state is EntryState.IDLE


def test_release_count_one_returns_to_idle_immediately() -> None:
    controller = make_controller(required_release_count=1)
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signal = controller.update(RELEASE_DISTANCE_CM)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE


def test_entry_can_be_detected_again_after_vehicle_release() -> None:
    controller = make_controller()

    first_entry_signals = [
        controller.update(ENTRY_DISTANCE_CM)
        for _ in range(REQUIRED_DETECTION_COUNT)
    ]

    assert first_entry_signals == [
        EntrySignal.NONE
    ] * (REQUIRED_DETECTION_COUNT - 1) + [
        EntrySignal.ENTRY_DETECTED
    ]
    assert controller.state is EntryState.OCCUPIED

    duplicate_signal = controller.update(ENTRY_DISTANCE_CM)

    assert duplicate_signal is EntrySignal.NONE
    assert controller.state is EntryState.OCCUPIED

    release_signals = [
        controller.update(RELEASE_DISTANCE_CM)
        for _ in range(REQUIRED_RELEASE_COUNT)
    ]

    assert release_signals == [
        EntrySignal.NONE
    ] * REQUIRED_RELEASE_COUNT
    assert controller.state is EntryState.IDLE

    second_entry_signals = [
        controller.update(ENTRY_DISTANCE_CM)
        for _ in range(REQUIRED_DETECTION_COUNT)
    ]

    assert second_entry_signals == [
        EntrySignal.NONE
    ] * (REQUIRED_DETECTION_COUNT - 1) + [
        EntrySignal.ENTRY_DETECTED
    ]
    assert controller.state is EntryState.OCCUPIED


@pytest.mark.parametrize(
    "interruption_distance_cm",
    [
        pytest.param(
            ENTRY_DISTANCE_CM,
            id="entry-distance",
        ),
        pytest.param(
            MIDDLE_DISTANCE_CM,
            id="middle-distance",
        ),
        pytest.param(None, id="none"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
    ],
)
def test_releasing_interruption_returns_to_occupied_and_resets_count(
    interruption_distance_cm: float | None,
) -> None:
    controller = make_controller()
    move_to_occupied(controller)
    controller.update(RELEASE_DISTANCE_CM)
    assert controller.state is EntryState.RELEASING

    signal = controller.update(interruption_distance_cm)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.OCCUPIED

    signals = [
        controller.update(RELEASE_DISTANCE_CM)
        for _ in range(REQUIRED_RELEASE_COUNT - 1)
    ]

    assert signals == [
        EntrySignal.NONE
    ] * (REQUIRED_RELEASE_COUNT - 1)
    assert controller.state is EntryState.RELEASING

    final_signal = controller.update(RELEASE_DISTANCE_CM)

    assert final_signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE


@pytest.mark.parametrize(
    "invalid_distance_cm",
    [
        pytest.param(None, id="none"),
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="positive-infinity"),
        pytest.param(-math.inf, id="negative-infinity"),
    ],
)
def test_invalid_measurement_keeps_occupied(
    invalid_distance_cm: float | None,
) -> None:
    controller = make_controller()
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signal = controller.update(invalid_distance_cm)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.OCCUPIED


def test_entry_threshold_is_included_in_entry_zone() -> None:
    controller = make_controller(required_detection_count=1)

    signal = controller.update(ENTRY_THRESHOLD_CM)

    assert signal is EntrySignal.ENTRY_DETECTED
    assert controller.state is EntryState.OCCUPIED


def test_release_threshold_is_included_in_release_zone() -> None:
    controller = make_controller(required_release_count=1)
    move_to_occupied(controller)
    assert controller.state is EntryState.OCCUPIED

    signal = controller.update(RELEASE_THRESHOLD_CM)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE


def test_distance_between_thresholds_is_middle_zone() -> None:
    controller = make_controller()

    signal = controller.update(MIDDLE_DISTANCE_CM)

    assert signal is EntrySignal.NONE
    assert controller.state is EntryState.IDLE


@pytest.mark.parametrize(
    (
        "entry_threshold_cm",
        "release_threshold_cm",
    ),
    [
        pytest.param(
            0.0,
            RELEASE_THRESHOLD_CM,
            id="zero-entry-threshold",
        ),
        pytest.param(
            -0.1,
            RELEASE_THRESHOLD_CM,
            id="negative-entry-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            0.0,
            id="zero-release-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            -0.1,
            id="negative-release-threshold",
        ),
        pytest.param(
            math.nan,
            RELEASE_THRESHOLD_CM,
            id="nan-entry-threshold",
        ),
        pytest.param(
            math.inf,
            RELEASE_THRESHOLD_CM,
            id="positive-infinite-entry-threshold",
        ),
        pytest.param(
            -math.inf,
            RELEASE_THRESHOLD_CM,
            id="negative-infinite-entry-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            math.nan,
            id="nan-release-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            math.inf,
            id="positive-infinite-release-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            -math.inf,
            id="negative-infinite-release-threshold",
        ),
        pytest.param(
            "6.0",
            RELEASE_THRESHOLD_CM,
            id="non-numeric-entry-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            "10.0",
            id="non-numeric-release-threshold",
        ),
        pytest.param(
            True,
            RELEASE_THRESHOLD_CM,
            id="boolean-entry-threshold",
        ),
        pytest.param(
            ENTRY_THRESHOLD_CM,
            False,
            id="boolean-release-threshold",
        ),
        pytest.param(
            RELEASE_THRESHOLD_CM,
            RELEASE_THRESHOLD_CM,
            id="equal-thresholds",
        ),
        pytest.param(
            RELEASE_THRESHOLD_CM + 0.1,
            RELEASE_THRESHOLD_CM,
            id="entry-threshold-above-release",
        ),
    ],
)
def test_constructor_raises_for_invalid_threshold_settings(
    entry_threshold_cm: object,
    release_threshold_cm: object,
) -> None:
    with pytest.raises(ValueError):
        EntryController(
            entry_threshold_cm=entry_threshold_cm,
            release_threshold_cm=release_threshold_cm,
            required_detection_count=REQUIRED_DETECTION_COUNT,
            required_release_count=REQUIRED_RELEASE_COUNT,
        )


@pytest.mark.parametrize(
    (
        "required_detection_count",
        "required_release_count",
    ),
    [
        pytest.param(
            0,
            REQUIRED_RELEASE_COUNT,
            id="zero-detection-count",
        ),
        pytest.param(
            -1,
            REQUIRED_RELEASE_COUNT,
            id="negative-detection-count",
        ),
        pytest.param(
            REQUIRED_DETECTION_COUNT,
            0,
            id="zero-release-count",
        ),
        pytest.param(
            REQUIRED_DETECTION_COUNT,
            -1,
            id="negative-release-count",
        ),
        pytest.param(
            1.0,
            REQUIRED_RELEASE_COUNT,
            id="float-detection-count",
        ),
        pytest.param(
            REQUIRED_DETECTION_COUNT,
            1.0,
            id="float-release-count",
        ),
        pytest.param(
            True,
            REQUIRED_RELEASE_COUNT,
            id="boolean-detection-count",
        ),
        pytest.param(
            REQUIRED_DETECTION_COUNT,
            False,
            id="boolean-release-count",
        ),
    ],
)
def test_constructor_raises_for_invalid_count_settings(
    required_detection_count: object,
    required_release_count: object,
) -> None:
    with pytest.raises(ValueError):
        EntryController(
            entry_threshold_cm=ENTRY_THRESHOLD_CM,
            release_threshold_cm=RELEASE_THRESHOLD_CM,
            required_detection_count=required_detection_count,
            required_release_count=required_release_count,
        )
