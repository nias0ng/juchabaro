import math
from enum import Enum, auto

from src.config.settings import (
    ENTRY_DISTANCE_THRESHOLD_CM,
    RELEASE_DISTANCE_THRESHOLD_CM,
    REQUIRED_DETECTION_COUNT,
    REQUIRED_RELEASE_COUNT,
)


class EntryState(Enum):
    IDLE = auto()
    DETECTING = auto()
    OCCUPIED = auto()
    RELEASING = auto()


class EntrySignal(Enum):
    NONE = auto()
    ENTRY_DETECTED = auto()


class EntryController:
    """거리 측정값을 바탕으로 차량 입차 상태를 관리한다."""

    def __init__(
        self,
        entry_threshold_cm: float = ENTRY_DISTANCE_THRESHOLD_CM,
        release_threshold_cm: float = RELEASE_DISTANCE_THRESHOLD_CM,
        required_detection_count: int = REQUIRED_DETECTION_COUNT,
        required_release_count: int = REQUIRED_RELEASE_COUNT,
    ) -> None:
        self._validate_settings(
            entry_threshold_cm=entry_threshold_cm,
            release_threshold_cm=release_threshold_cm,
            required_detection_count=required_detection_count,
            required_release_count=required_release_count,
        )

        self._entry_threshold_cm = float(entry_threshold_cm)
        self._release_threshold_cm = float(release_threshold_cm)
        self._required_detection_count = required_detection_count
        self._required_release_count = required_release_count

        self._state = EntryState.IDLE
        self._detection_count = 0
        self._release_count = 0

    @property
    def state(self) -> EntryState:
        return self._state

    def update(self, distance_cm: float | None) -> EntrySignal:
        """거리값을 반영하고 이번 측정에서 발생한 신호를 반환한다."""

        if distance_cm is None or not math.isfinite(distance_cm):
            return self._cancel_pending_transition()

        if distance_cm <= self._entry_threshold_cm:
            return self._handle_entry_distance()

        if distance_cm >= self._release_threshold_cm:
            return self._handle_release_distance()

        return self._cancel_pending_transition()

    @staticmethod
    def _validate_settings(
        *,
        entry_threshold_cm: float,
        release_threshold_cm: float,
        required_detection_count: int,
        required_release_count: int,
    ) -> None:
        for name, value in (
            ("entry_threshold_cm", entry_threshold_cm),
            ("release_threshold_cm", release_threshold_cm),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name}은 0보다 큰 유한한 수여야 합니다.")

        if entry_threshold_cm >= release_threshold_cm:
            raise ValueError(
                "입차 임계값은 이탈 임계값보다 작아야 합니다."
            )

        for name, value in (
            ("required_detection_count", required_detection_count),
            ("required_release_count", required_release_count),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(f"{name}은 1 이상의 정수여야 합니다.")

    def _handle_entry_distance(self) -> EntrySignal:
        if self._state in (
            EntryState.OCCUPIED,
            EntryState.RELEASING,
        ):
            self._state = EntryState.OCCUPIED
            self._release_count = 0
            return EntrySignal.NONE

        self._detection_count += 1

        if self._detection_count >= self._required_detection_count:
            self._state = EntryState.OCCUPIED
            self._detection_count = 0
            return EntrySignal.ENTRY_DETECTED

        self._state = EntryState.DETECTING
        return EntrySignal.NONE

    def _handle_release_distance(self) -> EntrySignal:
        if self._state in (
            EntryState.IDLE,
            EntryState.DETECTING,
        ):
            self._state = EntryState.IDLE
            self._detection_count = 0
            return EntrySignal.NONE

        self._release_count += 1

        if self._release_count >= self._required_release_count:
            self._state = EntryState.IDLE
            self._release_count = 0
            return EntrySignal.NONE

        self._state = EntryState.RELEASING
        return EntrySignal.NONE

    def _cancel_pending_transition(self) -> EntrySignal:
        self._detection_count = 0
        self._release_count = 0

        if self._state in (
            EntryState.IDLE,
            EntryState.DETECTING,
        ):
            self._state = EntryState.IDLE
        else:
            self._state = EntryState.OCCUPIED

        return EntrySignal.NONE
