"""삼상태 규칙 신호를 durable Incident 수명주기로 축약한다.

RuleEvaluator는 현재 술어만 계산한다. 이 reducer가 Candidate 생성, 신뢰 시간
누적, OPEN/CLEAR_PENDING/terminal 전이와 publication revision을 단독 소유한다.
UNKNOWN과 일시 미관측은 상태를 끝내지 않고 현재 timer sample chain만 끊는다.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Protocol
from uuid import uuid4

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
    require_non_negative,
    require_positive,
)
from src.parking.models import (
    BlockingRelationId,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentKeyScope,
    IncidentReduction,
    IncidentSignal,
    IncidentSignalValue,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ZoneId,
    ZoneVisitId,
)
from src.parking.time_guard import ensure_forward_observation
from src.session.models import EntryAttemptId
from src.tracking.models import ParkingSessionId, PhysicalVehicleId


@dataclass(frozen=True)
class _LastSample:
    """현재 process에서 직전 trusted-duration sample의 연속성을 표시한다."""

    value: IncidentSignalValue
    confirmable: bool


class IncidentReducer(Protocol):
    """Incident 상태 변경과 선택적 publication을 만드는 경계."""

    def reduce(
        self,
        signal: IncidentSignal,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        entry_attempt_id: EntryAttemptId | None = None,
        parking_session_id: ParkingSessionId | None = None,
        zone_id: ZoneId | None = None,
        victim_physical_vehicle_id: PhysicalVehicleId | None = None,
    ) -> IncidentReduction | None:
        """규칙 신호 하나를 적용한다. 완전 무동작일 때만 ``None``이다."""

        ...

    def terminate_zone_visit(
        self,
        zone_visit_id: ZoneVisitId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str = "ZONE_VISIT_ENDED",
    ) -> tuple[IncidentReduction, ...]:
        """방문을 scope로 하는 모든 nonterminal Incident를 직접 끝낸다."""

        ...

    def terminate_blocking_relation(
        self,
        blocking_relation_id: BlockingRelationId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str = "BLOCKING_RELATION_RESOLVED",
    ) -> tuple[IncidentReduction, ...]:
        """차단 관계를 scope로 하는 nonterminal Incident를 직접 끝낸다."""

        ...

    def terminate_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str = "PHYSICAL_VEHICLE_LEFT",
    ) -> tuple[IncidentReduction, ...]:
        """subject 또는 victim 차량에 연결된 Incident를 직접 끝낸다."""

        ...

    def pause_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> tuple[IncidentReduction, ...]:
        """차량 일시 미관측 동안 관련 Incident의 timer chain을 끊는다."""

        ...

    def checkpoint_state(self) -> object:
        """application transaction 전 rollback checkpoint를 반환한다."""

        ...

    def restore_state(self, checkpoint: object) -> None:
        """commit 실패 전 runtime state로 복구한다."""

        ...

    def restore_active(self, incidents: tuple[Incident, ...]) -> None:
        """restart 시 durable nonterminal Incident index를 복원한다."""

        ...


class InMemoryIncidentReducer:
    """process 내부 저장소를 사용하는 IncidentReducer 구현.

    이 구현은 lifecycle 동작과 테스트를 위한 reference implementation이다.
    호출자는 반환된 모든 ``IncidentReduction.incident``를 durable 저장 경계에
    반영해야 하며, ``transitions``가 있으면 같은 transaction에서 outbox를
    만들어야 한다. 이미 terminal인 local-only Incident의 늦은 correlation은
    durable pending handoff workflow가 별도로 materialize한다.
    """

    def __init__(
        self,
        *,
        trusted_sample_max_gap_seconds: float,
        confirm_duration_seconds: float = 0.0,
        clear_duration_seconds: float = 0.0,
    ) -> None:
        require_positive(
            trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        if trusted_sample_max_gap_seconds < 1e-6:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        require_non_negative(confirm_duration_seconds, "confirm_duration_seconds")
        require_non_negative(clear_duration_seconds, "clear_duration_seconds")
        self._trusted_sample_max_gap_seconds = trusted_sample_max_gap_seconds
        self._confirm_duration_seconds = confirm_duration_seconds
        self._clear_duration_seconds = clear_duration_seconds
        self._records: dict[IncidentId, Incident] = {}
        self._latest_id_by_key: dict[IncidentKey, IncidentId] = {}
        self._active_id_by_key: dict[IncidentKey, IncidentId] = {}
        self._last_sample_by_id: dict[IncidentId, _LastSample] = {}

    def checkpoint_state(self) -> object:
        """Incident index와 trusted sample chain을 함께 복사한다."""

        return deepcopy(
            (
                self._records,
                self._latest_id_by_key,
                self._active_id_by_key,
                self._last_sample_by_id,
            )
        )

    def restore_state(self, checkpoint: object) -> None:
        """``checkpoint_state``가 생성한 reducer snapshot을 복구한다."""

        if not isinstance(checkpoint, tuple) or len(checkpoint) != 4:
            raise TypeError("invalid IncidentReducer checkpoint")
        restored = deepcopy(checkpoint)
        (
            self._records,
            self._latest_id_by_key,
            self._active_id_by_key,
            self._last_sample_by_id,
        ) = restored

    def restore_active(self, incidents: tuple[Incident, ...]) -> None:
        """SQLite active snapshot을 trusted sample 연속성 없이 복원한다."""

        records: dict[IncidentId, Incident] = {}
        latest_by_key: dict[IncidentKey, IncidentId] = {}
        active_by_key: dict[IncidentKey, IncidentId] = {}
        for incident in incidents:
            if incident.state in {
                IncidentState.RESOLVED,
                IncidentState.CANCELED,
            }:
                raise ValueError("only nonterminal Incident may be restored")
            if incident.incident_id in records or incident.key in active_by_key:
                raise ValueError("duplicate active Incident restore identity")
            records[incident.incident_id] = incident
            latest_by_key[incident.key] = incident.incident_id
            active_by_key[incident.key] = incident.incident_id
        self._records = records
        self._latest_id_by_key = latest_by_key
        self._active_id_by_key = active_by_key
        # restart 전 sample과 재시작 후 sample을 연결하지 않는다.
        self._last_sample_by_id = {}

    def reduce(
        self,
        signal: IncidentSignal,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        entry_attempt_id: EntryAttemptId | None = None,
        parking_session_id: ParkingSessionId | None = None,
        zone_id: ZoneId | None = None,
        victim_physical_vehicle_id: PhysicalVehicleId | None = None,
    ) -> IncidentReduction | None:
        """신호를 적용해 aggregate update와 선택적 publication을 반환한다.

        ``MATCHED``만 새 Candidate를 만든다. ``UNKNOWN``은 기존 상태와 timer를
        보존하지만 직전 trusted sample 연속성을 끊는다. OPEN이 correlation 없이
        먼저 확정된 경우에는 publication revision 0으로 유지하며, 뒤 신호에
        authoritative correlation이 오면 같은 Incident의 revision 1 OPEN을 만든다.
        """

        latest = self._latest_for_key(signal.key)
        ensure_forward_observation(
            signal.observed_at,
            None if latest is None else latest.updated_at,
        )
        if (
            signal.key.scope_type is IncidentKeyScope.PHYSICAL_VEHICLE
            and signal.key.scope_id != physical_vehicle_id
        ):
            raise ValueError(
                "physical-vehicle IncidentKey must match physical_vehicle_id"
            )

        current = self._active_for_key(signal.key)
        effective_value = (
            signal.value
            if observation.state is ObservationState.OBSERVED
            else IncidentSignalValue.UNKNOWN
        )
        if current is None:
            if effective_value is not IncidentSignalValue.MATCHED:
                return None
            current = self._new_candidate(
                signal,
                physical_vehicle_id=physical_vehicle_id,
                observation=observation,
                entry_attempt_id=entry_attempt_id,
                parking_session_id=parking_session_id,
                zone_id=zone_id,
                victim_physical_vehicle_id=victim_physical_vehicle_id,
            )
            is_new = True
        else:
            self._validate_context(
                current,
                physical_vehicle_id=physical_vehicle_id,
                entry_attempt_id=entry_attempt_id,
                parking_session_id=parking_session_id,
                zone_id=zone_id,
                victim_physical_vehicle_id=victim_physical_vehicle_id,
            )
            current = self._with_context(
                current,
                entry_attempt_id=entry_attempt_id,
                parking_session_id=parking_session_id,
                zone_id=zone_id,
                victim_physical_vehicle_id=victim_physical_vehicle_id,
            )
            is_new = False

        materialized_open: IncidentTransition | None = None
        if self._can_materialize(current):
            current = replace(current, publication_revision=1)
            open_snapshot = replace(
                current,
                state=IncidentState.OPEN,
                clear_trusted_seconds=0.0,
                updated_at=signal.observed_at,
            )
            materialized_open = IncidentTransition(
                transition_type=IncidentTransitionType.OPEN,
                incident=open_snapshot,
            )

        if effective_value is IncidentSignalValue.UNKNOWN:
            paused = replace(
                current,
                observation=self._observation_for_value(
                    effective_value, observation, current
                ),
                record_version=current.record_version + (0 if is_new else 1),
                updated_at=signal.observed_at,
            )
            self._save_active(paused)
            self._last_sample_by_id.pop(paused.incident_id, None)
            return self._prepend_transition(
                IncidentReduction(paused), materialized_open
            )

        if current.state is IncidentState.CANDIDATE:
            reduction = self._reduce_candidate(
                current,
                signal,
                observation=observation,
                is_new=is_new,
            )
        elif current.state is IncidentState.OPEN:
            reduction = self._reduce_open(
                current, signal, observation=observation
            )
        elif current.state is IncidentState.CLEAR_PENDING:
            reduction = self._reduce_clear_pending(
                current, signal, observation=observation
            )
        else:
            raise RuntimeError("active Incident index contains a terminal aggregate")
        return self._prepend_transition(reduction, materialized_open)

    def terminate_zone_visit(
        self,
        zone_visit_id: ZoneVisitId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str = "ZONE_VISIT_ENDED",
    ) -> tuple[IncidentReduction, ...]:
        """방문 종료 사실로 해당 visit-scope Incident를 즉시 끝낸다."""

        return self._terminate_matching(
            lambda incident: (
                incident.key.scope_type is IncidentKeyScope.ZONE_VISIT
                and incident.key.scope_id == zone_visit_id
            ),
            observation=observation,
            observed_at=observed_at,
            reason=reason,
        )

    def terminate_blocking_relation(
        self,
        blocking_relation_id: BlockingRelationId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str = "BLOCKING_RELATION_RESOLVED",
    ) -> tuple[IncidentReduction, ...]:
        """관계 종료 사실로 해당 relation-scope Incident를 즉시 끝낸다."""

        return self._terminate_matching(
            lambda incident: (
                incident.key.scope_type is IncidentKeyScope.BLOCKING_RELATION
                and incident.key.scope_id == blocking_relation_id
            ),
            observation=observation,
            observed_at=observed_at,
            reason=reason,
        )

    def terminate_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str = "PHYSICAL_VEHICLE_LEFT",
    ) -> tuple[IncidentReduction, ...]:
        """물리 부재가 확인된 subject/victim의 Incident를 즉시 끝낸다."""

        return self._terminate_matching(
            lambda incident: (
                incident.physical_vehicle_id == physical_vehicle_id
                or incident.victim_physical_vehicle_id == physical_vehicle_id
            ),
            observation=observation,
            observed_at=observed_at,
            reason=reason,
        )

    def pause_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        observation: ObservationStatus,
        observed_at: datetime,
    ) -> tuple[IncidentReduction, ...]:
        """일시 미관측된 subject/victim의 상태를 유지하고 timer를 멈춘다."""

        matched = self._matching_active(
            lambda candidate: (
                candidate.physical_vehicle_id == physical_vehicle_id
                or candidate.victim_physical_vehicle_id == physical_vehicle_id
            )
        )
        for incident in matched:
            ensure_forward_observation(observed_at, incident.updated_at)

        reductions: list[IncidentReduction] = []
        for incident in matched:
            paused = replace(
                incident,
                observation=self._paused_observation(
                    observation,
                    incident,
                    reason=ObservationReason.TRACK_LOST,
                ),
                record_version=incident.record_version + 1,
                updated_at=observed_at,
            )
            self._save_active(paused)
            self._last_sample_by_id.pop(paused.incident_id, None)
            reductions.append(IncidentReduction(paused))
        return tuple(reductions)

    def snapshot(self) -> tuple[Incident, ...]:
        """생성 순서대로 nonterminal과 terminal Incident snapshot을 반환한다."""

        return tuple(self._records.values())

    def active_snapshot(self) -> tuple[Incident, ...]:
        """현재 nonterminal Incident snapshot만 생성 순서대로 반환한다."""

        active_ids = set(self._active_id_by_key.values())
        return tuple(
            incident
            for incident_id, incident in self._records.items()
            if incident_id in active_ids
        )

    def _reduce_candidate(
        self,
        current: Incident,
        signal: IncidentSignal,
        *,
        observation: ObservationStatus,
        is_new: bool,
    ) -> IncidentReduction:
        if signal.value is IncidentSignalValue.NOT_MATCHED:
            canceled = replace(
                current,
                state=IncidentState.CANCELED,
                observation=observation,
                record_version=current.record_version + (0 if is_new else 1),
                updated_at=signal.observed_at,
                terminated_at=signal.observed_at,
                termination_reason="PREDICATE_NOT_MATCHED_BEFORE_CONFIRMATION",
            )
            self._save_terminal(canceled)
            return IncidentReduction(canceled)

        trusted_seconds = current.confirm_trusted_seconds
        if signal.confirmable:
            trusted_seconds += self._trusted_delta(
                current,
                expected_value=IncidentSignalValue.MATCHED,
                require_confirmable=True,
                observed_at=signal.observed_at,
            )

        if (
            signal.confirmable
            and trusted_seconds >= current.confirm_duration_seconds
        ):
            opened = replace(
                current,
                state=IncidentState.OPEN,
                observation=observation,
                confirm_trusted_seconds=trusted_seconds,
                clear_trusted_seconds=0.0,
                record_version=current.record_version + (0 if is_new else 1),
                publication_revision=(1 if self._has_correlation(current) else 0),
                confirmed_at=signal.observed_at,
                updated_at=signal.observed_at,
            )
            self._save_active(opened)
            self._remember_sample(opened, signal.value, signal.confirmable)
            if opened.publication_revision == 0:
                return IncidentReduction(opened)
            return self._published_reduction(opened, IncidentTransitionType.OPEN)

        candidate = replace(
            current,
            observation=observation,
            confirm_trusted_seconds=trusted_seconds,
            record_version=current.record_version + (0 if is_new else 1),
            updated_at=signal.observed_at,
        )
        self._save_active(candidate)
        self._remember_sample(candidate, signal.value, signal.confirmable)
        return IncidentReduction(candidate)

    def _reduce_open(
        self,
        current: Incident,
        signal: IncidentSignal,
        *,
        observation: ObservationStatus,
    ) -> IncidentReduction:
        if signal.value is IncidentSignalValue.MATCHED:
            opened = replace(
                current,
                observation=observation,
                clear_trusted_seconds=0.0,
                record_version=current.record_version + 1,
                updated_at=signal.observed_at,
            )
            self._save_active(opened)
            self._remember_sample(opened, signal.value, signal.confirmable)
            return IncidentReduction(opened)

        clear_pending = replace(
            current,
            state=IncidentState.CLEAR_PENDING,
            observation=observation,
            clear_trusted_seconds=0.0,
            record_version=current.record_version + 1,
            updated_at=signal.observed_at,
        )
        if current.clear_duration_seconds == 0:
            return self._resolve(
                clear_pending,
                observed_at=signal.observed_at,
                observation=observation,
                reason="PREDICATE_CLEAR_CONFIRMED",
                increment_record=False,
            )

        self._save_active(clear_pending)
        self._remember_sample(clear_pending, signal.value, signal.confirmable)
        return IncidentReduction(clear_pending)

    def _reduce_clear_pending(
        self,
        current: Incident,
        signal: IncidentSignal,
        *,
        observation: ObservationStatus,
    ) -> IncidentReduction:
        if signal.value is IncidentSignalValue.MATCHED:
            opened = replace(
                current,
                state=IncidentState.OPEN,
                observation=observation,
                clear_trusted_seconds=0.0,
                record_version=current.record_version + 1,
                updated_at=signal.observed_at,
            )
            self._save_active(opened)
            self._remember_sample(opened, signal.value, signal.confirmable)
            return IncidentReduction(opened)

        trusted_seconds = current.clear_trusted_seconds + self._trusted_delta(
            current,
            expected_value=IncidentSignalValue.NOT_MATCHED,
            require_confirmable=False,
            observed_at=signal.observed_at,
        )
        if trusted_seconds >= current.clear_duration_seconds:
            ready = replace(current, clear_trusted_seconds=trusted_seconds)
            return self._resolve(
                ready,
                observed_at=signal.observed_at,
                observation=observation,
                reason="PREDICATE_CLEAR_CONFIRMED",
            )

        clear_pending = replace(
            current,
            observation=observation,
            clear_trusted_seconds=trusted_seconds,
            record_version=current.record_version + 1,
            updated_at=signal.observed_at,
        )
        self._save_active(clear_pending)
        self._remember_sample(clear_pending, signal.value, signal.confirmable)
        return IncidentReduction(clear_pending)

    def _terminate_matching(
        self,
        predicate: Callable[[Incident], bool],
        *,
        observation: ObservationStatus,
        observed_at: datetime,
        reason: str,
    ) -> tuple[IncidentReduction, ...]:
        if observation.state is not ObservationState.OBSERVED:
            raise ValueError(
                "direct Incident termination requires OBSERVED observation"
            )
        if not reason:
            raise ValueError("termination reason must not be empty")
        matched = self._matching_active(predicate)
        for incident in matched:
            ensure_forward_observation(observed_at, incident.updated_at)

        reductions: list[IncidentReduction] = []
        for incident in matched:
            if incident.state is IncidentState.CANDIDATE:
                canceled = replace(
                    incident,
                    state=IncidentState.CANCELED,
                    observation=observation,
                    record_version=incident.record_version + 1,
                    updated_at=observed_at,
                    terminated_at=observed_at,
                    termination_reason=reason,
                )
                self._save_terminal(canceled)
                reductions.append(IncidentReduction(canceled))
            else:
                reductions.append(
                    self._resolve(
                        incident,
                        observed_at=observed_at,
                        observation=observation,
                        reason=reason,
                    )
                )
        return tuple(reductions)

    def _resolve(
        self,
        current: Incident,
        *,
        observed_at: datetime,
        observation: ObservationStatus,
        reason: str,
        increment_record: bool = True,
    ) -> IncidentReduction:
        publication_revision = (
            current.publication_revision + 1
            if current.publication_revision > 0
            else 0
        )
        resolved = replace(
            current,
            state=IncidentState.RESOLVED,
            observation=observation,
            record_version=current.record_version + (1 if increment_record else 0),
            publication_revision=publication_revision,
            updated_at=observed_at,
            resolved_at=observed_at,
            terminated_at=observed_at,
            termination_reason=reason,
        )
        self._save_terminal(resolved)
        if publication_revision == 0:
            return IncidentReduction(resolved)
        return self._published_reduction(resolved, IncidentTransitionType.RESOLVE)

    def _trusted_delta(
        self,
        current: Incident,
        *,
        expected_value: IncidentSignalValue,
        require_confirmable: bool,
        observed_at: datetime,
    ) -> float:
        previous = self._last_sample_by_id.get(current.incident_id)
        if (
            previous is None
            or previous.value is not expected_value
            or (require_confirmable and not previous.confirmable)
            or current.observation.state is not ObservationState.OBSERVED
        ):
            return 0.0
        elapsed_seconds = (observed_at - current.updated_at).total_seconds()
        if elapsed_seconds > current.trusted_sample_max_gap_seconds:
            return 0.0
        return elapsed_seconds

    def _new_candidate(
        self,
        signal: IncidentSignal,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        observation: ObservationStatus,
        entry_attempt_id: EntryAttemptId | None,
        parking_session_id: ParkingSessionId | None,
        zone_id: ZoneId | None,
        victim_physical_vehicle_id: PhysicalVehicleId | None,
    ) -> Incident:
        return Incident(
            incident_id=IncidentId(uuid4()),
            key=signal.key,
            physical_vehicle_id=physical_vehicle_id,
            state=IncidentState.CANDIDATE,
            observation=observation,
            confirm_trusted_seconds=0.0,
            clear_trusted_seconds=0.0,
            confirm_duration_seconds=self._confirm_duration_seconds,
            clear_duration_seconds=self._clear_duration_seconds,
            record_version=1,
            publication_revision=0,
            first_observed_at=signal.observed_at,
            created_at=signal.observed_at,
            updated_at=signal.observed_at,
            trusted_sample_max_gap_seconds=self._trusted_sample_max_gap_seconds,
            entry_attempt_id=entry_attempt_id,
            parking_session_id=parking_session_id,
            zone_id=zone_id,
            victim_physical_vehicle_id=victim_physical_vehicle_id,
        )

    def _validate_context(
        self,
        current: Incident,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        entry_attempt_id: EntryAttemptId | None,
        parking_session_id: ParkingSessionId | None,
        zone_id: ZoneId | None,
        victim_physical_vehicle_id: PhysicalVehicleId | None,
    ) -> None:
        if current.physical_vehicle_id != physical_vehicle_id:
            raise ValueError("Incident physical_vehicle_id cannot change")
        fixed_context: list[tuple[str, object | None]] = [
            ("entry_attempt_id", entry_attempt_id),
            ("parking_session_id", parking_session_id),
            ("victim_physical_vehicle_id", victim_physical_vehicle_id),
        ]
        if current.key.scope_type is not IncidentKeyScope.PHYSICAL_VEHICLE:
            fixed_context.append(("zone_id", zone_id))
        for name, incoming in fixed_context:
            existing = getattr(current, name)
            if existing is not None and incoming is not None and existing != incoming:
                raise ValueError(f"Incident {name} cannot change")

    @staticmethod
    def _with_context(
        current: Incident,
        *,
        entry_attempt_id: EntryAttemptId | None,
        parking_session_id: ParkingSessionId | None,
        zone_id: ZoneId | None,
        victim_physical_vehicle_id: PhysicalVehicleId | None,
    ) -> Incident:
        return replace(
            current,
            entry_attempt_id=(
                current.entry_attempt_id
                if current.entry_attempt_id is not None
                else entry_attempt_id
            ),
            parking_session_id=(
                current.parking_session_id
                if current.parking_session_id is not None
                else parking_session_id
            ),
            zone_id=current.zone_id if current.zone_id is not None else zone_id,
            victim_physical_vehicle_id=(
                current.victim_physical_vehicle_id
                if current.victim_physical_vehicle_id is not None
                else victim_physical_vehicle_id
            ),
        )

    @staticmethod
    def _has_correlation(incident: Incident) -> bool:
        return (
            incident.entry_attempt_id is not None
            or incident.parking_session_id is not None
        )

    def _can_materialize(self, incident: Incident) -> bool:
        return (
            incident.state in {IncidentState.OPEN, IncidentState.CLEAR_PENDING}
            and incident.publication_revision == 0
            and self._has_correlation(incident)
        )

    @staticmethod
    def _prepend_transition(
        reduction: IncidentReduction,
        transition: IncidentTransition | None,
    ) -> IncidentReduction:
        if transition is None:
            return reduction
        return IncidentReduction(
            reduction.incident,
            (transition, *reduction.transitions),
        )

    @staticmethod
    def _published_reduction(
        incident: Incident, transition_type: IncidentTransitionType
    ) -> IncidentReduction:
        transition = IncidentTransition(
            transition_type=transition_type,
            incident=incident,
        )
        return IncidentReduction(incident, (transition,))

    def _observation_for_value(
        self,
        value: IncidentSignalValue,
        observation: ObservationStatus,
        current: Incident,
    ) -> ObservationStatus:
        if value is not IncidentSignalValue.UNKNOWN:
            return observation
        return self._paused_observation(
            observation,
            current,
            reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        )

    @staticmethod
    def _paused_observation(
        observation: ObservationStatus,
        current: Incident,
        *,
        reason: ObservationReason,
    ) -> ObservationStatus:
        if observation.state is not ObservationState.OBSERVED:
            if observation.last_reliable_observed_at is not None:
                return observation
            return replace(
                observation,
                last_reliable_observed_at=(
                    current.observation.last_reliable_observed_at
                ),
            )
        last_reliable = (
            current.observation.last_reliable_observed_at
            if current.observation.last_reliable_observed_at is not None
            else observation.last_reliable_observed_at
        )
        return ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=reason,
            last_reliable_observed_at=last_reliable,
        )

    def _remember_sample(
        self,
        incident: Incident,
        value: IncidentSignalValue,
        confirmable: bool,
    ) -> None:
        self._last_sample_by_id[incident.incident_id] = _LastSample(
            value=value,
            confirmable=confirmable,
        )

    def _save_active(self, incident: Incident) -> None:
        self._records[incident.incident_id] = incident
        self._latest_id_by_key[incident.key] = incident.incident_id
        self._active_id_by_key[incident.key] = incident.incident_id

    def _save_terminal(self, incident: Incident) -> None:
        self._records[incident.incident_id] = incident
        self._latest_id_by_key[incident.key] = incident.incident_id
        self._active_id_by_key.pop(incident.key, None)
        self._last_sample_by_id.pop(incident.incident_id, None)

    def _active_for_key(self, key: IncidentKey) -> Incident | None:
        incident_id = self._active_id_by_key.get(key)
        return None if incident_id is None else self._records[incident_id]

    def _latest_for_key(self, key: IncidentKey) -> Incident | None:
        incident_id = self._latest_id_by_key.get(key)
        return None if incident_id is None else self._records[incident_id]

    def _matching_active(
        self, predicate: Callable[[Incident], bool]
    ) -> tuple[Incident, ...]:
        return tuple(
            self._records[incident_id]
            for incident_id in self._active_id_by_key.values()
            if predicate(self._records[incident_id])
        )
