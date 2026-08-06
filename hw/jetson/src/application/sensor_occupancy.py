"""ToF 거리 관측을 구역별 안정된 점유 상태로 축약한다.

이 모듈은 센서와 구역의 결속, 거리 hysteresis, 확인시간 및 관측 신뢰도만
관리한다. 하드웨어 접근, polling, 동시성, 영속화와 외부 publication은
상위 composition 계층의 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import math
from numbers import Real

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
    require_aware,
)
from src.parking.models import ZoneId
from src.parking.time_guard import ensure_forward_observation
from src.sensors.models import (
    TOF_SENSOR_TYPE,
    SensorObservation,
    SensorReadFailure,
)


class OccupancyState(str, Enum):
    """구역의 안정된 점유 상태."""

    UNKNOWN = "UNKNOWN"
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"


def _finite_number(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name}는 bool이 아닌 유한한 숫자여야 합니다.")

    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 숫자여야 합니다."
        ) from exc

    if not math.isfinite(normalized):
        raise ValueError(f"{field_name}는 bool이 아닌 유한한 숫자여야 합니다.")

    if minimum is not None:
        valid = (
            normalized >= minimum
            if minimum_inclusive
            else normalized > minimum
        )
        if not valid:
            comparison = "이상" if minimum_inclusive else "초과"
            raise ValueError(
                f"{field_name}는 {minimum:g} {comparison}이어야 합니다."
            )

    return normalized


def _validate_sensor_id(sensor_id: object) -> None:
    if not isinstance(sensor_id, str) or not sensor_id.strip():
        raise ValueError("sensor_id는 공백이 아닌 문자열이어야 합니다.")


def _validate_zone_id(zone_id: object) -> None:
    if (
        isinstance(zone_id, bool)
        or not isinstance(zone_id, int)
        or zone_id <= 0
    ):
        raise ValueError("zone_id는 양의 정수여야 합니다.")


@dataclass(frozen=True, kw_only=True)
class SensorZoneBinding:
    """하나의 물리 센서를 하나의 구역에 결속한다."""

    sensor_id: str
    zone_id: ZoneId

    def __post_init__(self) -> None:
        _validate_sensor_id(self.sensor_id)
        _validate_zone_id(self.zone_id)


@dataclass(frozen=True, kw_only=True)
class OccupancyPolicy:
    """거리 경계와 상태 확정·관측 신뢰시간 정책.

    관측이 stale해진 간격을 candidate의 연속 evidence로 인정하지 않도록
    stale 시간은 trusted sample 최대 간격 이상이어야 한다.
    """

    enter_distance_mm: float
    exit_distance_mm: float
    enter_confirm_seconds: float
    exit_confirm_seconds: float
    trusted_sample_max_gap_seconds: float
    stale_after_seconds: float

    def __post_init__(self) -> None:
        normalized = {
            "enter_distance_mm": _finite_number(
                self.enter_distance_mm,
                field_name="enter_distance_mm",
                minimum=0.0,
                minimum_inclusive=False,
            ),
            "exit_distance_mm": _finite_number(
                self.exit_distance_mm,
                field_name="exit_distance_mm",
                minimum=0.0,
                minimum_inclusive=False,
            ),
            "enter_confirm_seconds": _finite_number(
                self.enter_confirm_seconds,
                field_name="enter_confirm_seconds",
                minimum=0.0,
            ),
            "exit_confirm_seconds": _finite_number(
                self.exit_confirm_seconds,
                field_name="exit_confirm_seconds",
                minimum=0.0,
            ),
            "trusted_sample_max_gap_seconds": _finite_number(
                self.trusted_sample_max_gap_seconds,
                field_name="trusted_sample_max_gap_seconds",
                minimum=0.0,
                minimum_inclusive=False,
            ),
            "stale_after_seconds": _finite_number(
                self.stale_after_seconds,
                field_name="stale_after_seconds",
                minimum=0.0,
                minimum_inclusive=False,
            ),
        }
        if normalized["enter_distance_mm"] >= normalized["exit_distance_mm"]:
            raise ValueError(
                "enter_distance_mm는 exit_distance_mm보다 작아야 합니다."
            )
        if (
            normalized["stale_after_seconds"]
            < normalized["trusted_sample_max_gap_seconds"]
        ):
            raise ValueError(
                "stale_after_seconds는 trusted_sample_max_gap_seconds "
                "이상이어야 합니다."
            )

        for field_name, value in normalized.items():
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True, kw_only=True)
class ZoneOccupancySnapshot:
    """한 센서·구역의 현재 안정 상태와 candidate 및 관측 진단값."""

    sensor_id: str
    zone_id: ZoneId

    stable_state: OccupancyState
    stable_since: datetime | None

    candidate_target: OccupancyState | None
    candidate_started_at: datetime | None
    candidate_elapsed_seconds: float

    observation: ObservationStatus

    last_distance_mm: float | None
    last_input_at: datetime | None
    last_failure: SensorReadFailure | None

    revision: int

    def __post_init__(self) -> None:
        _validate_sensor_id(self.sensor_id)
        _validate_zone_id(self.zone_id)

        if self.candidate_target not in {
            None,
            OccupancyState.VACANT,
            OccupancyState.OCCUPIED,
        }:
            raise ValueError(
                "candidate_target은 VACANT, OCCUPIED 또는 None이어야 합니다."
            )

        candidate_elapsed = _finite_number(
            self.candidate_elapsed_seconds,
            field_name="candidate_elapsed_seconds",
            minimum=0.0,
        )
        object.__setattr__(
            self,
            "candidate_elapsed_seconds",
            candidate_elapsed,
        )

        if self.candidate_target is None:
            if self.candidate_started_at is not None:
                raise ValueError(
                    "candidate가 없으면 candidate_started_at은 None이어야 합니다."
                )
            if candidate_elapsed != 0.0:
                raise ValueError(
                    "candidate가 없으면 candidate_elapsed_seconds는 0이어야 합니다."
                )
        elif self.candidate_started_at is None:
            raise ValueError(
                "candidate가 있으면 candidate_started_at이 필요합니다."
            )

        if self.stable_state is OccupancyState.UNKNOWN:
            if self.stable_since is not None:
                raise ValueError(
                    "UNKNOWN stable state에는 stable_since가 없어야 합니다."
                )
        elif self.stable_since is None:
            raise ValueError(
                "VACANT 또는 OCCUPIED stable state에는 stable_since가 필요합니다."
            )

        for field_name in (
            "stable_since",
            "candidate_started_at",
            "last_input_at",
        ):
            require_aware(getattr(self, field_name), field_name)

        if self.last_distance_mm is not None:
            normalized_distance = _finite_number(
                self.last_distance_mm,
                field_name="last_distance_mm",
                minimum=0.0,
            )
            object.__setattr__(
                self,
                "last_distance_mm",
                normalized_distance,
            )

        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("revision은 0 이상의 정수여야 합니다.")

    @property
    def last_reliable_observed_at(self) -> datetime | None:
        """현재 관측 상태가 보존하는 마지막 정상 관측 시각."""

        return self.observation.last_reliable_observed_at


@dataclass(frozen=True, kw_only=True)
class OccupancyTransition:
    """실제 stable 점유 상태 변경 한 건."""

    sensor_id: str
    zone_id: ZoneId
    previous_state: OccupancyState
    current_state: OccupancyState

    candidate_started_at: datetime
    confirmed_at: datetime
    confirming_distance_mm: float

    revision: int

    def __post_init__(self) -> None:
        _validate_sensor_id(self.sensor_id)
        _validate_zone_id(self.zone_id)

        if self.previous_state is self.current_state:
            raise ValueError("previous_state와 current_state는 달라야 합니다.")
        if self.current_state not in {
            OccupancyState.VACANT,
            OccupancyState.OCCUPIED,
        }:
            raise ValueError(
                "current_state는 VACANT 또는 OCCUPIED여야 합니다."
            )

        require_aware(self.candidate_started_at, "candidate_started_at")
        require_aware(self.confirmed_at, "confirmed_at")
        if self.confirmed_at < self.candidate_started_at:
            raise ValueError(
                "confirmed_at은 candidate_started_at보다 빠를 수 없습니다."
            )

        object.__setattr__(
            self,
            "confirming_distance_mm",
            _finite_number(
                self.confirming_distance_mm,
                field_name="confirming_distance_mm",
                minimum=0.0,
            ),
        )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("transition revision은 양의 정수여야 합니다.")


@dataclass(frozen=True, kw_only=True)
class OccupancyUpdate:
    """입력 한 건으로 갱신된 snapshot과 선택적인 stable 전이."""

    snapshot: ZoneOccupancySnapshot
    transition: OccupancyTransition | None

    def __post_init__(self) -> None:
        if self.transition is None:
            return
        if (
            self.transition.sensor_id != self.snapshot.sensor_id
            or self.transition.zone_id != self.snapshot.zone_id
            or self.transition.current_state is not self.snapshot.stable_state
            or self.transition.revision != self.snapshot.revision
        ):
            raise ValueError(
                "transition은 결과 snapshot의 센서, 구역, 상태와 revision이 "
                "일치해야 합니다."
            )


@dataclass
class _SensorSlot:
    snapshot: ZoneOccupancySnapshot
    last_input_monotonic: float | None = None
    last_reliable_monotonic: float | None = None
    candidate_started_monotonic: float | None = None
    last_supporting_monotonic: float | None = None


class OccupancyStateManager:
    """센서별 입력을 서로 독립적인 구역 점유 상태로 축약한다.

    호출자는 센서별 wall-clock과 monotonic 시각을 감소하지 않는 순서로
    전달해야 한다. wall-clock은 공개 timestamp에 사용하고 monotonic 시각은
    시스템 시각 보정에 영향받지 않는 gap·확인시간 계산에만 사용한다.

    이 객체는 thread-safe하지 않으며 단일 mutation owner가 직렬 호출해야 한다.
    """

    def __init__(
        self,
        *,
        bindings: tuple[SensorZoneBinding, ...],
        policy: OccupancyPolicy,
    ) -> None:
        if not bindings:
            raise ValueError("bindings는 하나 이상이어야 합니다.")
        if any(
            not isinstance(binding, SensorZoneBinding)
            for binding in bindings
        ):
            raise TypeError(
                "bindings의 모든 항목은 SensorZoneBinding이어야 합니다."
            )

        sensor_ids = [binding.sensor_id for binding in bindings]
        zone_ids = [binding.zone_id for binding in bindings]
        if len(sensor_ids) != len(set(sensor_ids)):
            raise ValueError("bindings에 중복된 sensor_id가 있습니다.")
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("bindings에 중복된 zone_id가 있습니다.")

        self._policy = policy
        self._sensor_order = tuple(sensor_ids)
        self._sensor_id_by_zone = {
            binding.zone_id: binding.sensor_id for binding in bindings
        }
        self._slots = {
            binding.sensor_id: _SensorSlot(
                snapshot=ZoneOccupancySnapshot(
                    sensor_id=binding.sensor_id,
                    zone_id=binding.zone_id,
                    stable_state=OccupancyState.UNKNOWN,
                    stable_since=None,
                    candidate_target=None,
                    candidate_started_at=None,
                    candidate_elapsed_seconds=0.0,
                    observation=ObservationStatus(
                        state=ObservationState.UNKNOWN,
                        reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
                    ),
                    last_distance_mm=None,
                    last_input_at=None,
                    last_failure=None,
                    revision=0,
                )
            )
            for binding in bindings
        }

    def apply_observation(
        self,
        observation: SensorObservation,
        *,
        monotonic_now: float,
    ) -> OccupancyUpdate:
        """정상 ToF 거리 한 건을 적용하고 갱신 결과를 반환한다.

        입력 계약 위반은 센서 장애로 변환하지 않고 `ValueError`로 알린다.
        stable 상태는 확인시간을 충족했을 때만 변경한다.
        """

        if not isinstance(observation, SensorObservation):
            raise ValueError("observation은 SensorObservation이어야 합니다.")
        if observation.sensor_type != TOF_SENSOR_TYPE:
            raise ValueError(
                f"sensor_type은 {TOF_SENSOR_TYPE!r}이어야 합니다."
            )

        distance_mm = _finite_number(
            observation.value,
            field_name="observation.value",
            minimum=0.0,
        )
        slot, normalized_monotonic = self._validated_input(
            sensor_id=observation.sensor_id,
            observed_at=observation.observed_at,
            monotonic_now=monotonic_now,
        )

        previous = slot.snapshot
        revision = previous.revision + 1
        evidence = self._evidence_for_distance(distance_mm)
        transition: OccupancyTransition | None = None

        candidate_target: OccupancyState | None = None
        candidate_started_at: datetime | None = None
        candidate_elapsed_seconds = 0.0
        candidate_started_monotonic: float | None = None
        last_supporting_monotonic: float | None = None

        if evidence is not None and evidence is not previous.stable_state:
            continuing = (
                previous.candidate_target is evidence
                and slot.candidate_started_monotonic is not None
                and slot.last_supporting_monotonic is not None
                and normalized_monotonic
                - slot.last_supporting_monotonic
                <= self._policy.trusted_sample_max_gap_seconds
            )

            if continuing:
                candidate_target = evidence
                candidate_started_at = previous.candidate_started_at
                candidate_started_monotonic = (
                    slot.candidate_started_monotonic
                )
                candidate_elapsed_seconds = (
                    normalized_monotonic
                    - candidate_started_monotonic
                )
            else:
                candidate_target = evidence
                candidate_started_at = observation.observed_at
                candidate_started_monotonic = normalized_monotonic

            last_supporting_monotonic = normalized_monotonic
            required_seconds = (
                self._policy.enter_confirm_seconds
                if evidence is OccupancyState.OCCUPIED
                else self._policy.exit_confirm_seconds
            )

            if candidate_elapsed_seconds >= required_seconds:
                transition = OccupancyTransition(
                    sensor_id=previous.sensor_id,
                    zone_id=previous.zone_id,
                    previous_state=previous.stable_state,
                    current_state=evidence,
                    candidate_started_at=candidate_started_at,
                    confirmed_at=observation.observed_at,
                    confirming_distance_mm=distance_mm,
                    revision=revision,
                )
                stable_state = evidence
                stable_since = observation.observed_at
                candidate_target = None
                candidate_started_at = None
                candidate_elapsed_seconds = 0.0
                candidate_started_monotonic = None
                last_supporting_monotonic = None
            else:
                stable_state = previous.stable_state
                stable_since = previous.stable_since
        else:
            # stable과 같은 근거나 hysteresis는 진행 중 candidate를 취소한다.
            stable_state = previous.stable_state
            stable_since = previous.stable_since

        snapshot = replace(
            previous,
            stable_state=stable_state,
            stable_since=stable_since,
            candidate_target=candidate_target,
            candidate_started_at=candidate_started_at,
            candidate_elapsed_seconds=candidate_elapsed_seconds,
            observation=ObservationStatus(
                state=ObservationState.OBSERVED,
                last_reliable_observed_at=observation.observed_at,
            ),
            last_distance_mm=distance_mm,
            last_input_at=observation.observed_at,
            revision=revision,
        )

        slot.snapshot = snapshot
        slot.last_input_monotonic = normalized_monotonic
        slot.last_reliable_monotonic = normalized_monotonic
        slot.candidate_started_monotonic = candidate_started_monotonic
        slot.last_supporting_monotonic = last_supporting_monotonic

        return OccupancyUpdate(
            snapshot=snapshot,
            transition=transition,
        )

    def apply_failure(
        self,
        failure: SensorReadFailure,
        *,
        monotonic_now: float,
    ) -> OccupancyUpdate:
        """센서 실패를 적용하되 확정된 점유 상태는 보존한다.

        장애는 빈 구역의 근거가 아니므로 candidate만 끊는다. 관측 신뢰도는
        마지막 정상 관측 이후의 monotonic 경과시간으로 판정한다.
        """

        if not isinstance(failure, SensorReadFailure):
            raise ValueError("failure는 SensorReadFailure여야 합니다.")

        slot, normalized_monotonic = self._validated_input(
            sensor_id=failure.sensor_id,
            observed_at=failure.observed_at,
            monotonic_now=monotonic_now,
        )
        previous = slot.snapshot

        if slot.last_reliable_monotonic is None:
            observation_state = ObservationState.UNKNOWN
        else:
            elapsed = normalized_monotonic - slot.last_reliable_monotonic
            observation_state = (
                ObservationState.UNKNOWN
                if elapsed >= self._policy.stale_after_seconds
                else ObservationState.DEGRADED
            )

        snapshot = replace(
            previous,
            candidate_target=None,
            candidate_started_at=None,
            candidate_elapsed_seconds=0.0,
            observation=ObservationStatus(
                state=observation_state,
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
                last_reliable_observed_at=(
                    previous.last_reliable_observed_at
                ),
            ),
            last_input_at=failure.observed_at,
            last_failure=failure,
            revision=previous.revision + 1,
        )

        slot.snapshot = snapshot
        slot.last_input_monotonic = normalized_monotonic
        slot.candidate_started_monotonic = None
        slot.last_supporting_monotonic = None

        return OccupancyUpdate(snapshot=snapshot, transition=None)

    def snapshot_for_sensor(
        self,
        sensor_id: str,
    ) -> ZoneOccupancySnapshot:
        """sensor ID에 대응하는 immutable snapshot을 반환한다."""

        return self._slot_for_sensor(sensor_id).snapshot

    def snapshot_for_zone(
        self,
        zone_id: ZoneId,
    ) -> ZoneOccupancySnapshot:
        """zone ID에 대응하는 immutable snapshot을 반환한다."""

        try:
            sensor_id = self._sensor_id_by_zone[zone_id]
        except KeyError as exc:
            raise ValueError(f"알 수 없는 zone_id입니다: {zone_id!r}") from exc
        return self._slots[sensor_id].snapshot

    def snapshots(self) -> tuple[ZoneOccupancySnapshot, ...]:
        """binding 입력 순서대로 모든 immutable snapshot을 반환한다."""

        return tuple(
            self._slots[sensor_id].snapshot
            for sensor_id in self._sensor_order
        )

    def _validated_input(
        self,
        *,
        sensor_id: str,
        observed_at: datetime,
        monotonic_now: float,
    ) -> tuple[_SensorSlot, float]:
        slot = self._slot_for_sensor(sensor_id)
        ensure_forward_observation(
            observed_at,
            slot.snapshot.last_input_at,
        )
        normalized_monotonic = _finite_number(
            monotonic_now,
            field_name="monotonic_now",
            minimum=0.0,
        )
        if (
            slot.last_input_monotonic is not None
            and normalized_monotonic < slot.last_input_monotonic
        ):
            raise ValueError(
                "monotonic_now가 해당 센서의 직전 입력보다 감소했습니다."
            )
        return slot, normalized_monotonic

    def _slot_for_sensor(self, sensor_id: str) -> _SensorSlot:
        try:
            return self._slots[sensor_id]
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"알 수 없는 sensor_id입니다: {sensor_id!r}"
            ) from exc

    def _evidence_for_distance(
        self,
        distance_mm: float,
    ) -> OccupancyState | None:
        if distance_mm <= self._policy.enter_distance_mm:
            return OccupancyState.OCCUPIED
        if distance_mm >= self._policy.exit_distance_mm:
            return OccupancyState.VACANT
        return None
