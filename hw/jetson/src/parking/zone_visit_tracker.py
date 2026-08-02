"""PhysicalVehicle 하나가 zone 하나를 연속 방문하는 수명주기를 관리한다.

정상 공간 관측만 진입·이탈 timer에 더한다. degraded 또는 ``UNKNOWN`` sample은
이미 누적한 하한을 보존한 채 sample 연결만 끊으며 terminal 전이를 만들지
않는다. 실제 출차는 cache timeout이 아니라 상위 owner가 확정한 사실을
``physical_exit``으로 전달해 처리한다.

``entry_trusted_seconds``는 진입 debounce만의 값이 아니라 한 visit 동안
누적한 trusted ``PRESENT`` 점유 시간이다. ``EXITING``과 관측 공백은
점유 시간에 더하지 않고, 두 trusted sample 간격이 설정값을 넘으면
그 간격을 0초로 처리해 capture·inference stall을 보충하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
from typing import Protocol
from uuid import uuid4

from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    PresenceSignal,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.time_guard import ensure_forward_observation
from src.tracking.models import PhysicalVehicleId


ENTRY_NOT_CONFIRMED = "ENTRY_NOT_CONFIRMED"
ZONE_EXIT_CONFIRMED = "ZONE_EXIT_CONFIRMED"
PHYSICAL_EXIT = "PHYSICAL_EXIT"

_NON_TERMINAL_STATES = {
    ZoneVisitState.ENTERING,
    ZoneVisitState.INSIDE,
    ZoneVisitState.EXITING,
}


class ZoneVisitTracker(Protocol):
    """신뢰 가능한 공간 sample을 ZoneVisit snapshot으로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit | None:
        """현재 snapshot 또는 이번 sample에서 생긴 terminal 전이를 반환한다."""

        ...

    def active_visits(self, physical_vehicle_id: PhysicalVehicleId) -> tuple[ZoneVisit, ...]:
        """PhysicalVehicle이 소유한 모든 non-terminal visit을 반환한다."""

        ...

    def pause_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> tuple[ZoneVisit, ...]:
        """snapshot 없는 관측 공백을 기록하고 trusted timer 연결을 끊는다."""

        ...

    def physical_exit(
        self, *, physical_vehicle_id: PhysicalVehicleId, observed_at: datetime
    ) -> tuple[ZoneVisit, ...]:
        """확정된 실제 출차 사실로 모든 active visit을 종료한다."""

        ...


@dataclass
class _VisitSlot:
    visit: ZoneVisit
    trusted_anchor_at: datetime | None

    def break_chain(self) -> None:
        self.trusted_anchor_at = None

    def trusted_delta(
        self,
        observed_at: datetime,
        *,
        max_gap_seconds: float,
    ) -> float:
        delta = 0.0
        if self.trusted_anchor_at is not None:
            delta = (observed_at - self.trusted_anchor_at).total_seconds()
        self.trusted_anchor_at = observed_at
        return 0.0 if delta > max_gap_seconds else delta


class InMemoryZoneVisitTracker:
    """``(PhysicalVehicle, zone)`` 쌍마다 non-terminal visit 하나를 추적한다."""

    def __init__(
        self,
        *,
        zone_definition_version: ZoneDefinitionVersion,
        entry_confirm_seconds: float,
        exit_confirm_seconds: float,
        trusted_sample_max_gap_seconds: float,
    ) -> None:
        if zone_definition_version <= 0:
            raise ValueError("zone_definition_version must be positive")
        if not all(
            math.isfinite(value) and value >= 0
            for value in (entry_confirm_seconds, exit_confirm_seconds)
        ):
            raise ValueError("confirmation thresholds must be finite and non-negative")
        if (
            not math.isfinite(trusted_sample_max_gap_seconds)
            or trusted_sample_max_gap_seconds <= 0
            or trusted_sample_max_gap_seconds < 1e-6
        ):
            raise ValueError(
                "trusted_sample_max_gap_seconds must be finite and at least one microsecond"
            )
        self._zone_definition_version = zone_definition_version
        self._entry_confirm_seconds = entry_confirm_seconds
        self._exit_confirm_seconds = exit_confirm_seconds
        self._trusted_sample_max_gap_seconds = trusted_sample_max_gap_seconds
        self._slots: dict[tuple[PhysicalVehicleId, ZoneId], _VisitSlot] = {}

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit | None:
        """한 공간 sample을 적용해 현재 또는 terminal visit snapshot을 반환한다."""

        key = (physical_vehicle_id, zone_id)
        slot = self._slots.get(key)
        ensure_forward_observation(
            observed_at,
            None if slot is None else slot.visit.updated_at,
        )
        if (
            signal is PresenceSignal.UNKNOWN
            and observation.state is ObservationState.OBSERVED
        ):
            raise ValueError(
                "UNKNOWN presence signal requires DEGRADED or UNKNOWN observation"
            )

        if slot is not None and slot.visit.state not in _NON_TERMINAL_STATES:
            del self._slots[key]
            slot = None

        if not _is_reliable(signal, observation):
            if slot is None:
                return None
            slot.break_chain()
            slot.visit = self._replace_observation(slot.visit, observation, observed_at)
            return slot.visit

        if slot is None:
            if signal is PresenceSignal.ABSENT:
                return None
            return self._open_candidate(key, physical_vehicle_id, zone_id, observation, observed_at)

        if slot.visit.state is ZoneVisitState.ENTERING:
            visit = self._advance_entering(slot, signal, observation, observed_at)
        elif slot.visit.state is ZoneVisitState.INSIDE:
            visit = self._advance_inside(slot, signal, observation, observed_at)
        else:
            visit = self._advance_exiting(slot, signal, observation, observed_at)

        if visit.state not in _NON_TERMINAL_STATES:
            del self._slots[key]
        return visit

    def active_visits(self, physical_vehicle_id: PhysicalVehicleId) -> tuple[ZoneVisit, ...]:
        """PhysicalVehicle이 소유한 모든 non-terminal visit을 조회한다."""

        return tuple(
            slot.visit
            for (vehicle_id, _), slot in self._slots.items()
            if vehicle_id == physical_vehicle_id and slot.visit.state in _NON_TERMINAL_STATES
        )

    def pause_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> tuple[ZoneVisit, ...]:
        """snapshot 없는 공백 동안 active visit을 유지하고 timer만 멈춘다."""

        ensure_forward_observation(observed_at)
        active_slots = [
            slot
            for (vehicle_id, _), slot in self._slots.items()
            if vehicle_id == physical_vehicle_id
            and slot.visit.state in _NON_TERMINAL_STATES
        ]
        for slot in active_slots:
            ensure_forward_observation(observed_at, slot.visit.updated_at)

        paused: list[ZoneVisit] = []
        for slot in active_slots:
            slot.break_chain()
            slot.visit = self._replace_observation(
                slot.visit,
                observation,
                observed_at,
            )
            paused.append(slot.visit)
        return tuple(paused)

    def physical_exit(
        self, *, physical_vehicle_id: PhysicalVehicleId, observed_at: datetime
    ) -> tuple[ZoneVisit, ...]:
        """확정된 실제 출차로 모든 active visit을 terminal로 만든다."""

        ensure_forward_observation(observed_at)
        active = [
            (key, slot)
            for key, slot in self._slots.items()
            if key[0] == physical_vehicle_id
            and slot.visit.state in _NON_TERMINAL_STATES
        ]
        for _, slot in active:
            ensure_forward_observation(observed_at, slot.visit.updated_at)

        terminated: list[ZoneVisit] = []
        exit_observation = ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=observed_at,
        )
        for key, slot in active:
            state = (
                ZoneVisitState.CANCELED
                if slot.visit.state is ZoneVisitState.ENTERING
                else ZoneVisitState.ENDED
            )
            terminated.append(
                replace(
                    slot.visit,
                    state=state,
                    observation=exit_observation,
                    record_version=slot.visit.record_version + 1,
                    updated_at=observed_at,
                    ended_at=observed_at,
                    termination_reason=PHYSICAL_EXIT,
                )
            )
            del self._slots[key]
        return tuple(terminated)

    def _open_candidate(
        self,
        key: tuple[PhysicalVehicleId, ZoneId],
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit:
        visit = ZoneVisit(
            visit_id=ZoneVisitId(uuid4()),
            physical_vehicle_id=physical_vehicle_id,
            zone_id=zone_id,
            zone_definition_version=self._zone_definition_version,
            state=ZoneVisitState.ENTERING,
            observation=observation,
            entry_trusted_seconds=0.0,
            exit_trusted_seconds=0.0,
            entry_confirmation_seconds=self._entry_confirm_seconds,
            exit_confirmation_seconds=self._exit_confirm_seconds,
            record_version=1,
            created_at=observed_at,
            updated_at=observed_at,
            trusted_sample_max_gap_seconds=self._trusted_sample_max_gap_seconds,
            entered_candidate_at=observed_at,
        )
        slot = _VisitSlot(visit=visit, trusted_anchor_at=observed_at)
        self._slots[key] = slot
        if self._entry_confirm_seconds == 0.0:
            slot.visit = replace(
                visit,
                state=ZoneVisitState.INSIDE,
                entered_at=observed_at,
            )
        return slot.visit

    def _advance_entering(
        self,
        slot: _VisitSlot,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit:
        if signal is PresenceSignal.ABSENT:
            slot.visit = replace(
                slot.visit,
                state=ZoneVisitState.CANCELED,
                observation=observation,
                record_version=slot.visit.record_version + 1,
                updated_at=observed_at,
                ended_at=observed_at,
                termination_reason=ENTRY_NOT_CONFIRMED,
            )
            return slot.visit

        trusted = slot.visit.entry_trusted_seconds + slot.trusted_delta(
            observed_at,
            max_gap_seconds=slot.visit.trusted_sample_max_gap_seconds,
        )
        state = (
            ZoneVisitState.INSIDE
            if trusted >= slot.visit.entry_confirmation_seconds
            else ZoneVisitState.ENTERING
        )
        slot.visit = replace(
            slot.visit,
            state=state,
            observation=observation,
            entry_trusted_seconds=trusted,
            record_version=slot.visit.record_version + 1,
            updated_at=observed_at,
            entered_at=slot.visit.entered_candidate_at if state is ZoneVisitState.INSIDE else None,
        )
        return slot.visit

    def _advance_inside(
        self,
        slot: _VisitSlot,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit:
        if signal is PresenceSignal.PRESENT:
            trusted = slot.visit.entry_trusted_seconds + slot.trusted_delta(
                observed_at,
                max_gap_seconds=slot.visit.trusted_sample_max_gap_seconds,
            )
            slot.visit = replace(
                slot.visit,
                observation=observation,
                entry_trusted_seconds=trusted,
                record_version=slot.visit.record_version + 1,
                updated_at=observed_at,
            )
            return slot.visit

        slot.trusted_anchor_at = observed_at
        slot.visit = replace(
            slot.visit,
            state=ZoneVisitState.EXITING,
            observation=observation,
            exit_trusted_seconds=0.0,
            record_version=slot.visit.record_version + 1,
            updated_at=observed_at,
            exit_candidate_at=observed_at,
        )
        if slot.visit.exit_confirmation_seconds == 0.0:
            slot.visit = self._end_confirmed_exit(slot.visit, observation, observed_at)
        return slot.visit

    def _advance_exiting(
        self,
        slot: _VisitSlot,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit:
        if signal is PresenceSignal.PRESENT:
            slot.trusted_anchor_at = observed_at
            slot.visit = replace(
                slot.visit,
                state=ZoneVisitState.INSIDE,
                observation=observation,
                exit_trusted_seconds=0.0,
                record_version=slot.visit.record_version + 1,
                updated_at=observed_at,
                exit_candidate_at=None,
            )
            return slot.visit

        trusted = slot.visit.exit_trusted_seconds + slot.trusted_delta(
            observed_at,
            max_gap_seconds=slot.visit.trusted_sample_max_gap_seconds,
        )
        slot.visit = replace(
            slot.visit,
            observation=observation,
            exit_trusted_seconds=trusted,
            record_version=slot.visit.record_version + 1,
            updated_at=observed_at,
        )
        if trusted >= slot.visit.exit_confirmation_seconds:
            slot.visit = self._end_confirmed_exit(slot.visit, observation, observed_at)
        return slot.visit

    @staticmethod
    def _end_confirmed_exit(
        visit: ZoneVisit,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit:
        return replace(
            visit,
            state=ZoneVisitState.ENDED,
            observation=observation,
            updated_at=observed_at,
            ended_at=visit.exit_candidate_at or observed_at,
            termination_reason=ZONE_EXIT_CONFIRMED,
        )

    @staticmethod
    def _replace_observation(
        visit: ZoneVisit,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> ZoneVisit:
        observation = _preserve_last_reliable(observation, visit.observation)
        return replace(
            visit,
            observation=observation,
            record_version=visit.record_version + 1,
            updated_at=observed_at,
        )


def _is_reliable(signal: PresenceSignal, observation: ObservationStatus) -> bool:
    return signal is not PresenceSignal.UNKNOWN and observation.state is ObservationState.OBSERVED


def _preserve_last_reliable(
    observation: ObservationStatus,
    previous: ObservationStatus,
) -> ObservationStatus:
    if observation.last_reliable_observed_at is not None:
        return observation
    return replace(
        observation,
        last_reliable_observed_at=previous.last_reliable_observed_at,
    )
