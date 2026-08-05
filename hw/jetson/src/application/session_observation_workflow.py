"""TrackingBatch를 durable session correlation으로 반영한다.

이 workflow는 한 frame에서 관측한 PhysicalVehicle, EntryMatchAttempt
매칭, ContextBinding과 ParkingSessionMirror의 최소 correlation을 하나의
SQLite UnitOfWork로 commit한다. TrackSegment 종료와 일시적 미관측은
어떤 durable scope도 종료하지 않는다.

``not_present_confirmed_vehicle_ids``를 소비해 출차·child 정리를 하는
다중-scope transaction은 PhysicalPresence workflow의 별도 책임이다.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
import sqlite3
from datetime import datetime, timedelta

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
    require_positive,
)
from src.session.context_binding_coordinator import (
    ContextBindingCoordinator,
    ContextBindingError,
)
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    ContextBinding,
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork, require_write_transaction
from src.tracking.models import (
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleAbsenceProgress,
    PhysicalVehicleSnapshot,
    PhysicalVehicleState,
    TrackingBatch,
)


_BINDABLE_DECISIONS = frozenset(
    {EntryDecisionState.ALLOW, EntryDecisionState.REVIEW_ALLOW}
)
# 04 durable-state 계약의 [제안값]. frame별 FULL-sync를 피하되
# crash 시 잃는 trusted checkpoint를 최대 10초로 제한한다.
_DIRTY_CHECKPOINT_INTERVAL = timedelta(seconds=10)


@dataclass(frozen=True)
class SessionObservationResult:
    """주차 판정에 제공할 durable correlation projection."""

    session_contexts: dict[PhysicalVehicleId, SessionContext]
    entry_attempt_ids: dict[PhysicalVehicleId, EntryAttemptId]
    historical_attempts: tuple[EntryMatchAttempt, ...] = ()


class SessionObservationWorkflow:
    """Tracking 관측과 session correlation의 transaction boundary."""

    def __init__(
        self,
        *,
        entry_match_coordinator: EntryMatchCoordinator,
        context_binding_coordinator: ContextBindingCoordinator,
        absence_confirmation_seconds: float,
        trusted_sample_max_gap_seconds: float,
    ) -> None:
        require_positive(
            absence_confirmation_seconds,
            "absence_confirmation_seconds",
        )
        require_positive(
            trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        self._entry_match_coordinator = entry_match_coordinator
        self._context_binding_coordinator = context_binding_coordinator
        self._absence_confirmation_seconds = absence_confirmation_seconds
        self._trusted_sample_max_gap_seconds = trusted_sample_max_gap_seconds
        # 같은 관측 등급의 DB write를 10초 단위로 합치더라도, 그 사이의
        # 실제 마지막 관측 시각을 다음 UNKNOWN 전이에서 과거 checkpoint로
        # 되돌리지 않는다. restart 시에는 durable 하한부터 다시 시작한다.
        self._latest_reliable_observed_at_by_vehicle: dict[
            PhysicalVehicleId, datetime | None
        ] = {}

    def process(
        self,
        batch: TrackingBatch,
        *,
        connection: sqlite3.Connection,
    ) -> dict[PhysicalVehicleId, SessionContext]:
        """한 batch를 반영하고 관측 차량의 authoritative context를 반환한다.

        반환 mapping은 현재 batch에 관측된 PhysicalVehicle 중 active
        ContextBinding이 있는 항목만 포함한다. ended TrackSegment와
        unobserved PhysicalVehicle은 binding·vehicle 종료 근거가 아니다.
        NOT_PRESENT confirmation의 출차 처리는 별도 workflow가 소유하지만,
        같은 batch에서 확정한 대상을 새 binding으로 되살리지는 않는다.
        """

        if not connection.in_transaction:
            checkpoint = self.checkpoint_state()
            try:
                with UnitOfWork(connection):
                    return self.process(batch, connection=connection)
            except Exception:
                self.restore_state(checkpoint)
                raise

        attempt_repository = EntryMatchAttemptRepository(connection)
        vehicle_repository = PhysicalVehicleRepository(connection)
        mirror_repository = ParkingSessionMirrorRepository(connection)
        binding_repository = ContextBindingRepository(connection)

        observed_snapshots = _unique_observed_snapshots(batch)

        # 독립 호출은 자체 transaction을 소유하고, frame workflow
        # 내부 호출은 이미 열린 동일 transaction에 참여한다.
        transaction = nullcontext()
        with transaction:
            pending_attempts = list(attempt_repository.list_pending())
            expired_attempts = self._entry_match_coordinator.expire_due(
                pending_attempts,
                observed_at=batch.observed_at,
                observation=batch.observation,
            )
            for expired in expired_attempts:
                attempt_repository.save(
                    expired,
                    expected_record_version=expired.record_version - 1,
                )

            expired_ids = {expired.entry_attempt_id for expired in expired_attempts}
            pending_attempts = [
                attempt
                for attempt in pending_attempts
                if attempt.entry_attempt_id not in expired_ids
            ]

            active_bindings = list(binding_repository.list_active())
            observed_vehicles = {
                snapshot.physical_vehicle_id: self._ensure_observed_vehicle(
                    repository=vehicle_repository,
                    snapshot=snapshot,
                    observed_at=batch.observed_at,
                )
                for snapshot in observed_snapshots
            }
            unobserved_vehicles = self._ensure_unobserved_vehicles(
                repository=vehicle_repository,
                physical_vehicle_ids=batch.unobserved_physical_vehicle_ids,
                absence_progress_by_vehicle={
                    progress.physical_vehicle_id: progress
                    for progress in batch.absence_progress
                },
                batch_observation=batch.observation,
                observed_at=batch.observed_at,
            )
            departed_vehicle_ids = set(
                batch.not_present_confirmed_vehicle_ids
            )
            unbound_authoritative_attempts = list(
                attempt_repository.list_unbound_authoritative_matches()
            )
            self._bind_existing_authoritative_matches(
                attempts=unbound_authoritative_attempts,
                observed_at=batch.observed_at,
                vehicle_repository=vehicle_repository,
                mirror_repository=mirror_repository,
                binding_repository=binding_repository,
                active_bindings=active_bindings,
                excluded_physical_vehicle_ids=departed_vehicle_ids,
            )
            unavailable_for_new_match_ids = {
                binding.physical_vehicle_id for binding in active_bindings
            }
            unavailable_for_new_match_ids.update(
                attempt_repository.list_active_matched_physical_vehicle_ids()
            )
            matching_observation_trusted = (
                batch.full_area_observed
                and batch.all_detections_tracked
                and batch.all_identities_resolved
                and batch.observation.state is ObservationState.OBSERVED
            )

            matchable_bboxes = {
                snapshot.physical_vehicle_id: snapshot.bbox
                for snapshot in observed_snapshots
                if matching_observation_trusted
                and snapshot.observation.state is ObservationState.OBSERVED
                and observed_vehicles[snapshot.physical_vehicle_id].state
                is PhysicalVehicleState.ACTIVE
                and snapshot.physical_vehicle_id
                not in unavailable_for_new_match_ids
            }
            matched = self._entry_match_coordinator.match_earliest(
                pending_attempts,
                observed_vehicle_bboxes=matchable_bboxes,
                observed_at=batch.observed_at,
            )
            if matched is not None:
                attempt_repository.save(
                    matched,
                    expected_record_version=matched.record_version - 1,
                )
                if matched.decision_state in _BINDABLE_DECISIONS:
                    physical_vehicle_id = matched.matched_physical_vehicle_id
                    if physical_vehicle_id is None:
                        raise RuntimeError(
                            "MATCHED attempt lost its PhysicalVehicle identity"
                        )
                    session_id = matched.authoritative_session_id
                    if session_id is None:
                        raise RuntimeError(
                            "bindable attempt lost its session identity"
                        )
                    existing_mirror = mirror_repository.get(session_id)
                    if self._allows_active_binding(existing_mirror):
                        vehicle = observed_vehicles[physical_vehicle_id]
                        binding, mirror = self._plan_binding(
                            attempt=matched,
                            vehicle=vehicle,
                            observed_at=batch.observed_at,
                            existing_bindings=active_bindings,
                            mirror_repository=mirror_repository,
                        )
                        self._save_mirror(mirror_repository, mirror)
                        binding_repository.add(binding)
                        active_bindings.append(binding)

            self._refresh_mirror_observations(
                current_vehicles={**unobserved_vehicles, **observed_vehicles},
                observed_at=batch.observed_at,
                active_bindings=active_bindings,
                mirror_repository=mirror_repository,
            )

            contexts = self._contexts_for_observed_vehicles(
                observed_snapshots,
                active_bindings,
            )

        return contexts

    def apply(
        self,
        batch: TrackingBatch,
        *,
        connection: sqlite3.Connection,
    ) -> SessionObservationResult:
        """상위 frame UnitOfWork 안에서 session 관측과 correlation을 반영한다.

        이 메서드는 transaction을 commit하지 않는다. 반환한
        ``entry_attempt_ids``는 session이 없는 DENY·REVIEW 차량의
        Incident correlation까지 포함한다.
        """

        require_write_transaction(connection)
        contexts = self.process(batch, connection=connection)
        attempt_repository = EntryMatchAttemptRepository(connection)
        binding_repository = ContextBindingRepository(connection)
        entry_attempt_ids: dict[PhysicalVehicleId, EntryAttemptId] = {}
        for snapshot in _unique_observed_snapshots(batch):
            binding = binding_repository.get_active_by_physical_vehicle_id(
                snapshot.physical_vehicle_id
            )
            if binding is not None:
                entry_attempt_ids[snapshot.physical_vehicle_id] = (
                    binding.entry_attempt_id
                )
                continue
            attempt = attempt_repository.get_matched_by_physical_vehicle_id(
                snapshot.physical_vehicle_id
            )
            if attempt is not None:
                entry_attempt_ids[snapshot.physical_vehicle_id] = (
                    attempt.entry_attempt_id
                )
        departed_physical_vehicle_ids = set(
            batch.not_present_confirmed_vehicle_ids
        )
        vehicle_repository = PhysicalVehicleRepository(connection)
        mirror_repository = ParkingSessionMirrorRepository(connection)
        historical_attempts = tuple(
            attempt
            for attempt in attempt_repository.list_unbound_authoritative_matches()
            if self._requires_historical_correlation(
                attempt,
                departed_physical_vehicle_ids=departed_physical_vehicle_ids,
                vehicle_repository=vehicle_repository,
                mirror_repository=mirror_repository,
            )
        )
        for attempt in historical_attempts:
            physical_vehicle_id = attempt.matched_physical_vehicle_id
            if physical_vehicle_id is not None:
                entry_attempt_ids[physical_vehicle_id] = (
                    attempt.entry_attempt_id
                )
        return SessionObservationResult(
            session_contexts=contexts,
            entry_attempt_ids=entry_attempt_ids,
            historical_attempts=historical_attempts,
        )

    def checkpoint_state(
        self,
    ) -> dict[PhysicalVehicleId, datetime | None]:
        """DB rollback과 함께 되돌릴 runtime observation cache를 복사한다."""

        return dict(self._latest_reliable_observed_at_by_vehicle)

    def restore_state(
        self,
        checkpoint: dict[PhysicalVehicleId, datetime | None],
    ) -> None:
        """commit 실패 전 runtime observation cache로 복구한다."""

        self._latest_reliable_observed_at_by_vehicle = dict(checkpoint)

    def _bind_existing_authoritative_matches(
        self,
        *,
        attempts: list[EntryMatchAttempt],
        observed_at: datetime,
        vehicle_repository: PhysicalVehicleRepository,
        mirror_repository: ParkingSessionMirrorRepository,
        binding_repository: ContextBindingRepository,
        active_bindings: list[ContextBinding],
        excluded_physical_vehicle_ids: set[PhysicalVehicleId],
    ) -> None:
        """물리 매칭 뒤 REVIEW_ALLOW로 확정된 attempt를 binding한다.

        TrackSegment가 이미 끝났어도 durable PhysicalVehicle이 ACTIVE면
        기존 매칭 결과를 재사용한다. 한번이라도 binding이 생긴
        entryAttemptId는 ENDED 상태에서도 새 binding을 만들지 않는다.
        """

        for attempt in attempts:
            if attempt.decision_state not in _BINDABLE_DECISIONS:
                continue
            physical_vehicle_id = attempt.matched_physical_vehicle_id
            if physical_vehicle_id is None:
                raise RuntimeError("MATCHED attempt lost its PhysicalVehicle identity")
            if physical_vehicle_id in excluded_physical_vehicle_ids:
                # NOT_PRESENT 출차 transaction이 아직 별도 단계에 있더라도,
                # 확정 이후 도착한 REVIEW_ALLOW가 active binding을 새로
                # 만드는 역전은 방지한다.
                continue
            vehicle = vehicle_repository.get(physical_vehicle_id)
            if vehicle is None:
                raise RuntimeError("MATCHED attempt references a missing PhysicalVehicle")
            if vehicle.state is not PhysicalVehicleState.ACTIVE:
                # RETIRED target의 historical correlation은 PhysicalPresence workflow가
                # 원래 occurredAt 순서로 다룬다.
                continue

            session_id = attempt.authoritative_session_id
            if session_id is None:
                raise RuntimeError("bindable attempt lost its session identity")
            existing_mirror = mirror_repository.get(session_id)
            if not self._allows_active_binding(existing_mirror):
                # 행정 종료 후 매칭은 active binding이 아닌
                # exit-only/historical correlation workflow의 책임이다.
                continue

            binding, mirror = self._plan_binding(
                attempt=attempt,
                vehicle=vehicle,
                observed_at=observed_at,
                existing_bindings=active_bindings,
                mirror_repository=mirror_repository,
            )
            self._save_mirror(mirror_repository, mirror)
            binding_repository.add(binding)
            active_bindings.append(binding)

    @staticmethod
    def _allows_active_binding(mirror: ParkingSessionMirror | None) -> bool:
        """현재 session 상태가 active ContextBinding을 허용하는지 판정한다."""

        return mirror is None or (
            mirror.administrative_state is SessionAdministrativeState.ACTIVE
            and mirror.physical_presence_state is not PhysicalPresenceState.EXITED
            and mirror.exit_correlation_enabled
        )

    def _requires_historical_correlation(
        self,
        attempt: EntryMatchAttempt,
        *,
        departed_physical_vehicle_ids: set[PhysicalVehicleId],
        vehicle_repository: PhysicalVehicleRepository,
        mirror_repository: ParkingSessionMirrorRepository,
    ) -> bool:
        """active binding으로 되돌리지 않을 correlation을 분리한다."""

        physical_vehicle_id = attempt.matched_physical_vehicle_id
        session_id = attempt.authoritative_session_id
        if physical_vehicle_id is None or session_id is None:
            raise RuntimeError(
                "authoritative historical match lost correlation identity"
            )
        if physical_vehicle_id in departed_physical_vehicle_ids:
            return True
        vehicle = vehicle_repository.get(physical_vehicle_id)
        if vehicle is None:
            raise RuntimeError(
                "authoritative historical match references a missing PhysicalVehicle"
            )
        if vehicle.state is not PhysicalVehicleState.ACTIVE:
            return True
        return not self._allows_active_binding(
            mirror_repository.get(session_id)
        )

    def _ensure_observed_vehicle(
        self,
        *,
        repository: PhysicalVehicleRepository,
        snapshot: PhysicalVehicleSnapshot,
        observed_at: datetime,
    ) -> PhysicalVehicle:
        observation = snapshot.observation

        # 현재 adapter는 ByteTrack이 track ID를 확정한 detection만
        # PhysicalVehicleSnapshot으로 낸다. ID가 없는 tentative detection은
        # 부재 판정만 멈추고 aggregate를 만들지 않으므로, 첫 snapshot은
        # 현재 배포에서 identity 확정이며 durable state를 ACTIVE로 시작한다.
        candidate = PhysicalVehicle(
            physical_vehicle_id=snapshot.physical_vehicle_id,
            state=PhysicalVehicleState.ACTIVE,
            observation=observation,
            absence_trusted_seconds=0.0,
            absence_confirmation_seconds=self._absence_confirmation_seconds,
            trusted_sample_max_gap_seconds=(
                self._trusted_sample_max_gap_seconds
            ),
            record_version=1,
            created_at=observed_at,
            updated_at=observed_at,
        )
        existing = repository.get(snapshot.physical_vehicle_id)
        if existing is None:
            existing = repository.ensure(candidate)

        if existing.state in {
            PhysicalVehicleState.RETIRED,
            PhysicalVehicleState.CANCELED,
        }:
            # 확정 종료한 identity를 새 관측으로 암묵적 재활성화하지
            # 않는다. EntityResolver가 새 PhysicalVehicleId를 만들어야 한다.
            return existing

        if observed_at < existing.updated_at:
            # 느리게 도착한 frame이 더 최신 durable checkpoint를 되돌리지 않는다.
            self._remember_reliable_observation(
                existing.physical_vehicle_id,
                existing.observation.last_reliable_observed_at,
            )
            return existing

        self._remember_reliable_observation(
            existing.physical_vehicle_id,
            observation.last_reliable_observed_at,
        )

        if (
            existing.state is PhysicalVehicleState.ACTIVE
            and existing.observation.state is observation.state
            and existing.observation.reason is observation.reason
            and existing.absence_trusted_seconds == 0
        ):
            current = replace(existing, observation=observation)
            if observed_at - existing.updated_at < _DIRTY_CHECKPOINT_INTERVAL:
                # bbox·frame은 ephemeral이다. 최신 관측은 현재 frame의
                # binding·mirror에 사용하되, 동일 등급을 5fps로
                # SQLite FULL-sync하지 않는다.
                return current

            updated = replace(
                current,
                record_version=existing.record_version + 1,
                updated_at=observed_at,
            )
            repository.save(
                updated,
                expected_record_version=existing.record_version,
            )
            return updated

        updated = replace(
            existing,
            state=PhysicalVehicleState.ACTIVE,
            observation=observation,
            absence_trusted_seconds=0.0,
            absence_confirmed_at=None,
            record_version=existing.record_version + 1,
            updated_at=max(observed_at, existing.updated_at),
        )
        repository.save(
            updated,
            expected_record_version=existing.record_version,
        )
        return updated

    def _ensure_unobserved_vehicles(
        self,
        *,
        repository: PhysicalVehicleRepository,
        physical_vehicle_ids: tuple[PhysicalVehicleId, ...],
        absence_progress_by_vehicle: dict[
            PhysicalVehicleId, PhysicalVehicleAbsenceProgress
        ],
        batch_observation: ObservationStatus,
        observed_at: datetime,
    ) -> dict[PhysicalVehicleId, PhysicalVehicle]:
        """미관측 차량을 terminal로 바꾸지 않고 관측 축만 갱신한다."""

        vehicles: dict[PhysicalVehicleId, PhysicalVehicle] = {}
        for physical_vehicle_id in physical_vehicle_ids:
            existing = repository.get(physical_vehicle_id)
            if existing is None:
                raise RuntimeError(
                    "unobserved signal references a missing PhysicalVehicle"
                )
            if existing.state is not PhysicalVehicleState.ACTIVE:
                vehicles[physical_vehicle_id] = existing
                continue
            if observed_at < existing.updated_at:
                vehicles[physical_vehicle_id] = existing
                continue

            self._remember_reliable_observation(
                physical_vehicle_id,
                existing.observation.last_reliable_observed_at,
            )
            last_reliable_observed_at = (
                self._latest_reliable_observed_at_by_vehicle.get(
                    physical_vehicle_id
                )
            )
            if batch_observation.state is ObservationState.OBSERVED:
                next_observation = ObservationStatus(
                    state=ObservationState.UNKNOWN,
                    reason=ObservationReason.TRACK_LOST,
                    last_reliable_observed_at=last_reliable_observed_at,
                )
            else:
                next_observation = ObservationStatus(
                    state=batch_observation.state,
                    reason=batch_observation.reason,
                    last_reliable_observed_at=last_reliable_observed_at,
                )

            absence_progress = absence_progress_by_vehicle[physical_vehicle_id]
            trusted_seconds = max(
                existing.absence_trusted_seconds,
                absence_progress.trusted_seconds,
            )
            confirmed_at = existing.absence_confirmed_at
            if absence_progress.confirmed_at is not None:
                if (
                    confirmed_at is not None
                    and confirmed_at != absence_progress.confirmed_at
                ):
                    raise RuntimeError(
                        "NOT_PRESENT_CONFIRMED occurredAt cannot change"
                    )
                confirmed_at = absence_progress.confirmed_at
            observation_changed = existing.observation != next_observation
            progress_changed = (
                existing.absence_trusted_seconds != trusted_seconds
            )
            confirmation_changed = existing.absence_confirmed_at != confirmed_at
            if (
                not observation_changed
                and not progress_changed
                and not confirmation_changed
            ):
                vehicles[physical_vehicle_id] = existing
                continue

            current = replace(
                existing,
                observation=next_observation,
                absence_trusted_seconds=trusted_seconds,
                absence_confirmed_at=confirmed_at,
            )
            checkpoint_due = (
                observation_changed
                or confirmation_changed
                or observed_at - existing.updated_at >= _DIRTY_CHECKPOINT_INTERVAL
            )
            if not checkpoint_due:
                vehicles[physical_vehicle_id] = current
                continue

            updated = replace(
                current,
                record_version=existing.record_version + 1,
                updated_at=observed_at,
            )
            repository.save(
                updated,
                expected_record_version=existing.record_version,
            )
            vehicles[physical_vehicle_id] = updated

        return vehicles

    def _remember_reliable_observation(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        observed_at: datetime | None,
    ) -> None:
        current = self._latest_reliable_observed_at_by_vehicle.get(
            physical_vehicle_id
        )
        if observed_at is not None and (current is None or observed_at > current):
            self._latest_reliable_observed_at_by_vehicle[
                physical_vehicle_id
            ] = observed_at

    def _plan_binding(
        self,
        *,
        attempt: EntryMatchAttempt,
        vehicle: PhysicalVehicle,
        observed_at: datetime,
        existing_bindings: list[ContextBinding],
        mirror_repository: ParkingSessionMirrorRepository,
    ) -> tuple[ContextBinding, ParkingSessionMirror]:
        context = attempt.authoritative_context
        session_id = attempt.authoritative_session_id
        if context is None or session_id is None:
            raise RuntimeError("bindable attempt lost its authoritative context")

        existing_mirror = mirror_repository.get(session_id)
        if existing_mirror is None:
            mirror = ParkingSessionMirror(
                parking_session_id=session_id,
                entry_attempt_id=attempt.entry_attempt_id,
                physical_vehicle_id=vehicle.physical_vehicle_id,
                administrative_state=SessionAdministrativeState.ACTIVE,
                physical_presence_state=PhysicalPresenceState.INSIDE,
                physical_observation=vehicle.observation,
                context_revision=0,
                last_context=context,
                record_version=1,
                publication_revision=0,
                created_at=attempt.created_at,
                updated_at=observed_at,
            )
        else:
            if existing_mirror.entry_attempt_id not in {
                None,
                attempt.entry_attempt_id,
            }:
                raise ContextBindingError(
                    "session mirror is correlated with another entryAttemptId"
                )
            if existing_mirror.physical_vehicle_id not in {
                None,
                vehicle.physical_vehicle_id,
            }:
                raise ContextBindingError(
                    "session mirror is correlated with another PhysicalVehicle"
                )
            latest_context = existing_mirror.last_context or context
            mirror = replace(
                existing_mirror,
                entry_attempt_id=attempt.entry_attempt_id,
                physical_vehicle_id=vehicle.physical_vehicle_id,
                physical_presence_state=PhysicalPresenceState.INSIDE,
                physical_observation=vehicle.observation,
                last_context=latest_context,
                record_version=existing_mirror.record_version + 1,
                updated_at=max(observed_at, existing_mirror.updated_at),
            )

        binding = self._context_binding_coordinator.bind(
            attempt=attempt,
            physical_vehicle=vehicle,
            session_mirror=mirror,
            existing_bindings=existing_bindings,
            bound_at=observed_at,
        )
        return binding, mirror

    @staticmethod
    def _refresh_mirror_observations(
        *,
        current_vehicles: dict[PhysicalVehicleId, PhysicalVehicle],
        observed_at: datetime,
        active_bindings: list[ContextBinding],
        mirror_repository: ParkingSessionMirrorRepository,
    ) -> None:
        """active mirror의 관측 등급을 차량 정본과 동기화한다.

        state·reason 변경은 즉시 저장하고, 동일 등급의 시각만
        바뀐 경우에는 PhysicalVehicle과 동일하게 10초 간격을 둔다.
        """

        bindings_by_vehicle = {
            binding.physical_vehicle_id: binding
            for binding in active_bindings
        }
        for physical_vehicle_id, vehicle in current_vehicles.items():
            binding = bindings_by_vehicle.get(physical_vehicle_id)
            if binding is None:
                continue
            mirror = mirror_repository.get(binding.parking_session_id)
            if mirror is None:
                raise RuntimeError("active ContextBinding references a missing session mirror")
            if mirror.physical_vehicle_id != physical_vehicle_id:
                raise ContextBindingError(
                    "active ContextBinding and session mirror vehicle identity differ"
                )

            current = mirror.physical_observation
            next_observation = vehicle.observation
            quality_unchanged = (
                current.state is next_observation.state
                and current.reason is next_observation.reason
            )
            if current == next_observation:
                continue
            if (
                quality_unchanged
                and observed_at - mirror.updated_at < _DIRTY_CHECKPOINT_INTERVAL
            ):
                continue

            updated = replace(
                mirror,
                physical_observation=next_observation,
                record_version=mirror.record_version + 1,
                updated_at=max(observed_at, mirror.updated_at),
            )
            mirror_repository.save(
                updated,
                expected_record_version=mirror.record_version,
            )

    @staticmethod
    def _save_mirror(
        repository: ParkingSessionMirrorRepository,
        mirror: ParkingSessionMirror,
    ) -> None:
        existing = repository.get(mirror.parking_session_id)
        if existing is None:
            repository.add(mirror)
            return
        repository.save(
            mirror,
            expected_record_version=existing.record_version,
        )

    def _contexts_for_observed_vehicles(
        self,
        snapshots: tuple[PhysicalVehicleSnapshot, ...],
        active_bindings: list[ContextBinding],
    ) -> dict[PhysicalVehicleId, SessionContext]:
        contexts: dict[PhysicalVehicleId, SessionContext] = {}
        for snapshot in snapshots:
            context = self._context_binding_coordinator.active_context_for(
                active_bindings,
                snapshot.physical_vehicle_id,
            )
            if context is not None:
                contexts[snapshot.physical_vehicle_id] = context
        return contexts


def _unique_observed_snapshots(
    batch: TrackingBatch,
) -> tuple[PhysicalVehicleSnapshot, ...]:
    """한 PhysicalVehicle이 여러 segment로 재식별된 frame을 한 번만 처리한다."""

    unique: dict[PhysicalVehicleId, PhysicalVehicleSnapshot] = {}
    for snapshot in batch.vehicles:
        unique.setdefault(snapshot.physical_vehicle_id, snapshot)
    return tuple(unique.values())
