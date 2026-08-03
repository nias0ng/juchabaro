"""subject 차량 하나가 victim 차량 하나의 egress 하나를 막는 관계 수명주기를 관리한다.

정상 geometry 관측만 confirm·clear timer에 더한다. degraded 또는 ``UNKNOWN``
sample은 이미 누적한 하한을 보존한 채 sample 연결만 끊으며 terminal 전이를
만들지 않는다. 실제 출차는 cache timeout이 아니라 상위 owner가 확정한 사실을
``physical_exit``으로 전달해 처리한다.

``confirm_trusted_seconds``는 confirm debounce만의 값이 아니라 한 관계 동안
누적한 trusted BLOCKING 관측 시간이다. 두 trusted sample 간격이 설정값을
넘으면 그 간격을 0초로 처리해 capture·inference stall을 보충하지 않는다.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
import math
from typing import Protocol
from uuid import uuid4

from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    BlockingRelation,
    BlockingRelationId,
    BlockingRelationState,
    PresenceSignal,
    ZoneId,
)
from src.parking.time_guard import ensure_forward_observation
from src.tracking.models import PhysicalVehicleId


CANDIDATE_NOT_CONFIRMED = "CANDIDATE_NOT_CONFIRMED"
BLOCKING_RELATION_CLEAR_CONFIRMED = "BLOCKING_RELATION_CLEAR_CONFIRMED"
PHYSICAL_EXIT = "PHYSICAL_EXIT"

_NON_TERMINAL_STATES = {
    BlockingRelationState.CANDIDATE,
    BlockingRelationState.BLOCKING,
    BlockingRelationState.CLEAR_PENDING,
}

_RelationKey = tuple[PhysicalVehicleId, PhysicalVehicleId, ZoneId]


class BlockingRelationTracker(Protocol):
    """신뢰 가능한 차단 geometry sample을 BlockingRelation snapshot으로 변환한다."""

    def update(
        self,
        *,
        subject_physical_vehicle_id: PhysicalVehicleId,
        victim_physical_vehicle_id: PhysicalVehicleId,
        egress_zone_id: ZoneId,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation | None:
        """현재 snapshot 또는 이번 sample에서 생긴 terminal 전이를 반환한다."""

        ...

    def active_relations(
        self, physical_vehicle_id: PhysicalVehicleId
    ) -> tuple[BlockingRelation, ...]:
        """PhysicalVehicle이 subject 또는 victim인 모든 non-terminal 관계를 반환한다."""

        ...

    def all_active_relations(self) -> tuple[BlockingRelation, ...]:
        """차량 필터 없이 현재 tracker가 들고 있는 모든 non-terminal 관계를 반환한다."""

        ...

    def physical_exit(
        self, *, physical_vehicle_id: PhysicalVehicleId, observed_at: datetime
    ) -> tuple[BlockingRelation, ...]:
        """확정된 실제 출차 사실로 관련 active 관계를 모두 종료한다."""

        ...

    def checkpoint_state(self) -> object:
        """application transaction 전 rollback checkpoint를 반환한다."""

        ...

    def restore_state(self, checkpoint: object) -> None:
        """commit 실패 전 runtime state로 복구한다."""

        ...

    def restore_active(self, relations: tuple[BlockingRelation, ...]) -> None:
        """restart 시 durable nonterminal 관계를 끊은 timer chain으로 복원한다."""

        ...


@dataclass
class _RelationSlot:
    relation: BlockingRelation
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


class InMemoryBlockingRelationTracker:
    """``(subject, victim, egress zone)`` triple마다 non-terminal 관계 하나를 추적한다."""

    def __init__(
        self,
        *,
        confirm_duration_seconds: float,
        clear_duration_seconds: float,
        trusted_sample_max_gap_seconds: float,
    ) -> None:
        if not all(
            math.isfinite(value) and value >= 0
            for value in (confirm_duration_seconds, clear_duration_seconds)
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
        self._confirm_duration_seconds = confirm_duration_seconds
        self._clear_duration_seconds = clear_duration_seconds
        self._trusted_sample_max_gap_seconds = trusted_sample_max_gap_seconds
        self._slots: dict[_RelationKey, _RelationSlot] = {}

    def checkpoint_state(self) -> object:
        """mutable slot을 transaction rollback용으로 복사한다."""

        return deepcopy(self._slots)

    def restore_state(self, checkpoint: object) -> None:
        """``checkpoint_state``가 생성한 slot snapshot을 복구한다."""

        if not isinstance(checkpoint, dict):
            raise TypeError("invalid BlockingRelationTracker checkpoint")
        self._slots = deepcopy(checkpoint)

    def restore_active(self, relations: tuple[BlockingRelation, ...]) -> None:
        """SQLite active snapshot을 wall-clock 보충 없이 복원한다."""

        restored: dict[_RelationKey, _RelationSlot] = {}
        for relation in relations:
            if relation.state not in _NON_TERMINAL_STATES:
                raise ValueError("only nonterminal BlockingRelation may be restored")
            key = (
                relation.subject_physical_vehicle_id,
                relation.victim_physical_vehicle_id,
                relation.egress_zone_id,
            )
            if key in restored:
                raise ValueError("duplicate active BlockingRelation restore key")
            restored[key] = _RelationSlot(
                relation=relation,
                # process downtime을 trusted duration으로 더하지 않는다.
                trusted_anchor_at=None,
            )
        self._slots = restored

    def update(
        self,
        *,
        subject_physical_vehicle_id: PhysicalVehicleId,
        victim_physical_vehicle_id: PhysicalVehicleId,
        egress_zone_id: ZoneId,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation | None:
        """한 차단 geometry sample을 적용해 현재 또는 terminal 관계 snapshot을 반환한다."""

        if subject_physical_vehicle_id == victim_physical_vehicle_id:
            raise ValueError("blocking relation subject and victim must differ")

        key = (subject_physical_vehicle_id, victim_physical_vehicle_id, egress_zone_id)
        slot = self._slots.get(key)
        ensure_forward_observation(
            observed_at,
            None if slot is None else slot.relation.updated_at,
        )
        if (
            signal is PresenceSignal.UNKNOWN
            and observation.state is ObservationState.OBSERVED
        ):
            raise ValueError(
                "UNKNOWN presence signal requires DEGRADED or UNKNOWN observation"
            )

        if slot is not None and slot.relation.state not in _NON_TERMINAL_STATES:
            del self._slots[key]
            slot = None

        if not _is_reliable(signal, observation):
            if slot is None:
                return None
            slot.break_chain()
            slot.relation = self._replace_observation(slot.relation, observation, observed_at)
            return slot.relation

        if slot is None:
            if signal is PresenceSignal.ABSENT:
                return None
            return self._open_candidate(
                key,
                subject_physical_vehicle_id,
                victim_physical_vehicle_id,
                egress_zone_id,
                observation,
                observed_at,
            )

        if slot.relation.state is BlockingRelationState.CANDIDATE:
            relation = self._advance_candidate(slot, signal, observation, observed_at)
        elif slot.relation.state is BlockingRelationState.BLOCKING:
            relation = self._advance_blocking(slot, signal, observation, observed_at)
        else:
            relation = self._advance_clear_pending(slot, signal, observation, observed_at)

        if relation.state not in _NON_TERMINAL_STATES:
            del self._slots[key]
        return relation

    def active_relations(
        self, physical_vehicle_id: PhysicalVehicleId
    ) -> tuple[BlockingRelation, ...]:
        """PhysicalVehicle이 subject 또는 victim인 모든 non-terminal 관계를 조회한다."""

        return tuple(
            slot.relation
            for (subject_id, victim_id, _), slot in self._slots.items()
            if physical_vehicle_id in (subject_id, victim_id)
            and slot.relation.state in _NON_TERMINAL_STATES
        )

    def all_active_relations(self) -> tuple[BlockingRelation, ...]:
        """차량 필터 없이 현재 tracker가 들고 있는 모든 non-terminal 관계를 조회한다."""

        return tuple(
            slot.relation
            for slot in self._slots.values()
            if slot.relation.state in _NON_TERMINAL_STATES
        )

    def physical_exit(
        self, *, physical_vehicle_id: PhysicalVehicleId, observed_at: datetime
    ) -> tuple[BlockingRelation, ...]:
        """확정된 실제 출차로 관련 active 관계를 모두 terminal로 만든다."""

        ensure_forward_observation(observed_at)
        active = [
            (key, slot)
            for key, slot in self._slots.items()
            if physical_vehicle_id in (key[0], key[1])
            and slot.relation.state in _NON_TERMINAL_STATES
        ]
        for _, slot in active:
            ensure_forward_observation(observed_at, slot.relation.updated_at)

        terminated: list[BlockingRelation] = []
        exit_observation = ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=observed_at,
        )
        for key, slot in active:
            if slot.relation.state is BlockingRelationState.CANDIDATE:
                relation = replace(
                    slot.relation,
                    state=BlockingRelationState.CANCELED,
                    observation=exit_observation,
                    record_version=slot.relation.record_version + 1,
                    updated_at=observed_at,
                    terminated_at=observed_at,
                    termination_reason=PHYSICAL_EXIT,
                )
            else:
                relation = replace(
                    slot.relation,
                    state=BlockingRelationState.RESOLVED,
                    observation=exit_observation,
                    record_version=slot.relation.record_version + 1,
                    updated_at=observed_at,
                    resolved_at=observed_at,
                    terminated_at=observed_at,
                    termination_reason=PHYSICAL_EXIT,
                )
            terminated.append(relation)
            del self._slots[key]
        return tuple(terminated)

    def _open_candidate(
        self,
        key: _RelationKey,
        subject_physical_vehicle_id: PhysicalVehicleId,
        victim_physical_vehicle_id: PhysicalVehicleId,
        egress_zone_id: ZoneId,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation:
        relation = BlockingRelation(
            blocking_relation_id=BlockingRelationId(uuid4()),
            subject_physical_vehicle_id=subject_physical_vehicle_id,
            victim_physical_vehicle_id=victim_physical_vehicle_id,
            egress_zone_id=egress_zone_id,
            state=BlockingRelationState.CANDIDATE,
            observation=observation,
            confirm_trusted_seconds=0.0,
            clear_trusted_seconds=0.0,
            confirm_duration_seconds=self._confirm_duration_seconds,
            clear_duration_seconds=self._clear_duration_seconds,
            record_version=1,
            created_at=observed_at,
            updated_at=observed_at,
        )
        slot = _RelationSlot(relation=relation, trusted_anchor_at=observed_at)
        self._slots[key] = slot
        if self._confirm_duration_seconds == 0.0:
            slot.relation = replace(
                relation,
                state=BlockingRelationState.BLOCKING,
                confirmed_at=observed_at,
            )
        return slot.relation

    def _advance_candidate(
        self,
        slot: _RelationSlot,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation:
        if signal is PresenceSignal.ABSENT:
            slot.relation = replace(
                slot.relation,
                state=BlockingRelationState.CANCELED,
                observation=observation,
                record_version=slot.relation.record_version + 1,
                updated_at=observed_at,
                terminated_at=observed_at,
                termination_reason=CANDIDATE_NOT_CONFIRMED,
            )
            return slot.relation

        trusted = slot.relation.confirm_trusted_seconds + slot.trusted_delta(
            observed_at,
            max_gap_seconds=self._trusted_sample_max_gap_seconds,
        )
        confirmed = trusted >= slot.relation.confirm_duration_seconds
        slot.relation = replace(
            slot.relation,
            state=(
                BlockingRelationState.BLOCKING
                if confirmed
                else BlockingRelationState.CANDIDATE
            ),
            observation=observation,
            confirm_trusted_seconds=trusted,
            record_version=slot.relation.record_version + 1,
            updated_at=observed_at,
            confirmed_at=observed_at if confirmed else None,
        )
        return slot.relation

    def _advance_blocking(
        self,
        slot: _RelationSlot,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation:
        if signal is PresenceSignal.PRESENT:
            trusted = slot.relation.confirm_trusted_seconds + slot.trusted_delta(
                observed_at,
                max_gap_seconds=self._trusted_sample_max_gap_seconds,
            )
            slot.relation = replace(
                slot.relation,
                observation=observation,
                confirm_trusted_seconds=trusted,
                record_version=slot.relation.record_version + 1,
                updated_at=observed_at,
            )
            return slot.relation

        slot.trusted_anchor_at = observed_at
        slot.relation = replace(
            slot.relation,
            state=BlockingRelationState.CLEAR_PENDING,
            observation=observation,
            clear_trusted_seconds=0.0,
            record_version=slot.relation.record_version + 1,
            updated_at=observed_at,
        )
        if slot.relation.clear_duration_seconds == 0.0:
            slot.relation = self._resolve_clear(slot.relation, observation, observed_at)
        return slot.relation

    def _advance_clear_pending(
        self,
        slot: _RelationSlot,
        signal: PresenceSignal,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation:
        if signal is PresenceSignal.PRESENT:
            slot.trusted_anchor_at = observed_at
            slot.relation = replace(
                slot.relation,
                state=BlockingRelationState.BLOCKING,
                observation=observation,
                clear_trusted_seconds=0.0,
                record_version=slot.relation.record_version + 1,
                updated_at=observed_at,
            )
            return slot.relation

        trusted = slot.relation.clear_trusted_seconds + slot.trusted_delta(
            observed_at,
            max_gap_seconds=self._trusted_sample_max_gap_seconds,
        )
        slot.relation = replace(
            slot.relation,
            observation=observation,
            clear_trusted_seconds=trusted,
            record_version=slot.relation.record_version + 1,
            updated_at=observed_at,
        )
        if trusted >= slot.relation.clear_duration_seconds:
            slot.relation = self._resolve_clear(slot.relation, observation, observed_at)
        return slot.relation

    @staticmethod
    def _resolve_clear(
        relation: BlockingRelation,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation:
        return replace(
            relation,
            state=BlockingRelationState.RESOLVED,
            observation=observation,
            updated_at=observed_at,
            resolved_at=observed_at,
            terminated_at=observed_at,
            termination_reason=BLOCKING_RELATION_CLEAR_CONFIRMED,
        )

    @staticmethod
    def _replace_observation(
        relation: BlockingRelation,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> BlockingRelation:
        observation = _preserve_last_reliable(observation, relation.observation)
        return replace(
            relation,
            observation=observation,
            record_version=relation.record_version + 1,
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
