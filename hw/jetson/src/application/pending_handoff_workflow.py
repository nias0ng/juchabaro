"""correlation 전 local fact를 늦은 durable publication으로 연결한다.

ParkingEpisode·Incident의 domain snapshot은 session correlation이 없어도
먼저 확정될 수 있다. 이 workflow는 그 fact의 original occurredAt을
``pending_handoffs``에 남겨 두었다가 authoritative correlation이 생기면
aggregate revision 순서로 publication projection을 재구성한다.

wire endpoint·DTO·serializer는 결정하지 않는다. 반환한 transition은
``FrameObservationWorkflow``의 ``PublicationPreparer``가 exact bytes로 바꾸며,
marker·aggregate·outbox는 모두 호출자의 같은 SQLite Unit of Work에
참여한다.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import sqlite3
from uuid import NAMESPACE_URL, UUID, uuid5

from src.application.physical_presence_workflow import (
    ABSENCE_WITHOUT_EXIT_EVIDENCE,
    SessionExitTransition,
)
from src.application.session_observation_workflow import SessionObservationResult
from src.domain.models import ObservationStatus, require_aware
from src.parking.models import (
    Incident,
    IncidentId,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingPipelineResult,
    ParkingState,
    ParkingTransition,
    ParkingTransitionType,
)
from src.parking.parking_episode_tracker import MOVEMENT_CONFIRMED, PHYSICAL_EXIT
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    ParkingSessionMirror,
    PhysicalExitEvidence,
    PhysicalPresenceState,
    PhysicalTerminationOrigin,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.aggregate_repositories import (
    IncidentRepository,
    ParkingEpisodeRepository,
)
from src.storage.codecs import datetime_to_epoch_microseconds
from src.storage.models import PendingHandoffRecord, PendingHandoffState
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PendingHandoffRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import require_write_transaction
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


_HANDOFF_RETENTION = timedelta(days=7)
_UNBOUND_CONTEXT_EXPIRED = "UNBOUND_CONTEXT_EXPIRED"
_CORRELATION_CONFLICT = "CORRELATION_CONFLICT"
_BINDABLE_DECISIONS = frozenset(
    {EntryDecisionState.ALLOW, EntryDecisionState.REVIEW_ALLOW}
)


@dataclass(frozen=True)
class HistoricalCorrelationResult:
    """active binding 없이 보존한 session correlation의 projection."""

    session_contexts: dict[PhysicalVehicleId, SessionContext]
    entry_attempt_ids: dict[PhysicalVehicleId, EntryAttemptId]
    session_exit_transitions: tuple[SessionExitTransition, ...]


@dataclass(frozen=True)
class PendingMaterializationResult:
    """늦은 correlation으로 publication 가능해진 aggregate 결과.

    ``parking_result``는 기존 aggregate consumer 호환을 유지한다.
    최종 outbox enqueue는 aggregate 종류별 tuple이 아닌
    ``ordered_transitions``를 소비해야 original occurredAt 순서를
    보존한다.
    """

    parking_result: ParkingPipelineResult
    ordered_transitions: tuple[ParkingTransition | IncidentTransition, ...] = ()


class PendingHandoffWorkflow:
    """pending publication marker의 생성·소비·만료를 소유한다."""

    def capture(
        self,
        result: ParkingPipelineResult,
        *,
        connection: sqlite3.Connection,
    ) -> None:
        """correlation 없이 확정된 OPEN·PARKED fact를 marker로 남긴다."""

        require_write_transaction(connection)
        repository = PendingHandoffRepository(connection)
        episodes = _latest_by_id(
            result.parking_episode_updates,
            "episode_id",
        )
        for episode in episodes.values():
            self._capture_parking_episode(repository, episode)

        incidents = _latest_by_id(result.incident_updates, "incident_id")
        for incident in incidents.values():
            self._capture_incident(repository, incident)

    def correlate_historical_sessions(
        self,
        attempts: tuple[EntryMatchAttempt, ...],
        *,
        observed_at: datetime,
        connection: sqlite3.Connection,
    ) -> HistoricalCorrelationResult:
        """departed·ADMIN_CLOSED target을 active binding 없이 mirror에 연결한다."""

        require_write_transaction(connection)
        require_aware(observed_at, "observed_at")
        vehicle_repository = PhysicalVehicleRepository(connection)
        mirror_repository = ParkingSessionMirrorRepository(connection)
        session_contexts: dict[PhysicalVehicleId, SessionContext] = {}
        entry_attempt_ids: dict[PhysicalVehicleId, EntryAttemptId] = {}
        exits: list[SessionExitTransition] = []

        for attempt in attempts:
            physical_vehicle_id = attempt.matched_physical_vehicle_id
            session_id = attempt.authoritative_session_id
            context = attempt.authoritative_context
            if (
                physical_vehicle_id is None
                or session_id is None
                or context is None
                or attempt.decision_state not in _BINDABLE_DECISIONS
            ):
                raise RuntimeError(
                    "historical correlation requires MATCHED ALLOW context"
                )
            vehicle = vehicle_repository.get(physical_vehicle_id)
            if vehicle is None:
                raise RuntimeError(
                    "historical correlation references a missing PhysicalVehicle"
                )
            if vehicle.state is PhysicalVehicleState.CANCELED:
                continue

            mirror = mirror_repository.get(session_id)
            if mirror is not None:
                if mirror.entry_attempt_id not in {
                    None,
                    attempt.entry_attempt_id,
                }:
                    raise RuntimeError(
                        "historical session is linked to another entryAttemptId"
                    )
                if mirror.physical_vehicle_id not in {
                    None,
                    physical_vehicle_id,
                }:
                    raise RuntimeError(
                        "historical session is linked to another PhysicalVehicle"
                    )
                if not mirror.exit_correlation_enabled:
                    # 이미 분류한 conflict는 매 frame 예외로 되풀이하지
                    # 않는다. 기존 authoritative mirror가 있을 때만
                    # 그 identity를 유지하고 session-scoped handoff는 보류한다.
                    _, authoritative_attempt_id = (
                        self._competing_exit_correlation(
                            physical_vehicle_id,
                            excluding_session_id=session_id,
                            connection=connection,
                        )
                    )
                    if authoritative_attempt_id is not None:
                        entry_attempt_ids[physical_vehicle_id] = (
                            authoritative_attempt_id
                        )
                    continue

            has_competing_correlation, authoritative_attempt_id = (
                self._competing_exit_correlation(
                    physical_vehicle_id,
                    excluding_session_id=session_id,
                    connection=connection,
                )
            )
            if has_competing_correlation:
                disabled = self._disable_historical_correlation(
                    attempt=attempt,
                    mirror=mirror,
                    vehicle_observation=vehicle.observation,
                    updated_at=observed_at,
                )
                self._save_mirror(mirror_repository, mirror, disabled)
                if authoritative_attempt_id is not None:
                    entry_attempt_ids[physical_vehicle_id] = (
                        authoritative_attempt_id
                    )
                continue

            entry_attempt_ids[physical_vehicle_id] = attempt.entry_attempt_id
            if mirror is None or (
                mirror.administrative_state
                is SessionAdministrativeState.ACTIVE
            ):
                session_contexts[physical_vehicle_id] = context

            if vehicle.state is PhysicalVehicleState.RETIRED:
                if vehicle.terminated_at is None:
                    raise RuntimeError("RETIRED PhysicalVehicle lost terminated_at")
                if (
                    mirror is not None
                    and mirror.physical_presence_state
                    is PhysicalPresenceState.EXITED
                ):
                    continue
                if vehicle.termination_reason == ABSENCE_WITHOUT_EXIT_EVIDENCE:
                    # 출차 구역 통과가 관측되지 않은 부재는 출차가 아니다(565).
                    # 이 시점에는 ZoneVisit이 이미 종료돼 재계산할 수 없으므로
                    # departure가 영속한 사유를 그대로 신뢰한다. 확인할 수 없는
                    # 출차 상태를 mirror에 만들어 두지 않는다.
                    continue
                updated = self._historical_mirror(
                    attempt=attempt,
                    vehicle=vehicle,
                    mirror=mirror,
                    presence_state=PhysicalPresenceState.EXITED,
                    updated_at=observed_at,
                )
                self._save_mirror(mirror_repository, mirror, updated)
                exits.append(
                    SessionExitTransition(
                        parking_session_id=session_id,
                        physical_vehicle_id=physical_vehicle_id,
                        publication_revision=updated.publication_revision,
                        occurred_at=vehicle.terminated_at,
                        origin=(
                            PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
                        ),
                        evidence=PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL,
                    )
                )
                continue

            if vehicle.state is not PhysicalVehicleState.ACTIVE:
                continue
            if (
                mirror is not None
                and mirror.physical_presence_state
                is PhysicalPresenceState.INSIDE
                and mirror.physical_vehicle_id == physical_vehicle_id
            ):
                continue
            updated = self._historical_mirror(
                attempt=attempt,
                vehicle=vehicle,
                mirror=mirror,
                presence_state=PhysicalPresenceState.INSIDE,
                updated_at=observed_at,
            )
            self._save_mirror(mirror_repository, mirror, updated)

        return HistoricalCorrelationResult(
            session_contexts=session_contexts,
            entry_attempt_ids=entry_attempt_ids,
            session_exit_transitions=tuple(exits),
        )

    def materialize(
        self,
        session_result: SessionObservationResult,
        historical_result: HistoricalCorrelationResult,
        *,
        materialized_at: datetime,
        connection: sqlite3.Connection,
    ) -> PendingMaterializationResult:
        """waiting marker를 authoritative correlation으로 publication한다."""

        require_write_transaction(connection)
        require_aware(materialized_at, "materialized_at")
        session_contexts = {
            **session_result.session_contexts,
            **historical_result.session_contexts,
        }
        entry_attempt_ids = {
            **session_result.entry_attempt_ids,
            **historical_result.entry_attempt_ids,
        }
        grouped: dict[tuple[str, str], list[PendingHandoffRecord]] = (
            defaultdict(list)
        )
        for marker in PendingHandoffRepository(connection).list_waiting():
            grouped[(marker.aggregate_type, marker.aggregate_id)].append(marker)

        parking_updates: list[ParkingEpisode] = []
        parking_transitions: list[ParkingTransition] = []
        incident_updates: list[Incident] = []
        incident_transitions: list[IncidentTransition] = []
        for (aggregate_type, aggregate_id), markers in grouped.items():
            if aggregate_type == "ParkingEpisode":
                update, transitions = self._materialize_parking_episode(
                    aggregate_id,
                    markers,
                    session_contexts=session_contexts,
                    materialized_at=materialized_at,
                    connection=connection,
                )
                if update is not None:
                    parking_updates.append(update)
                    parking_transitions.extend(transitions)
                continue
            if aggregate_type == "Incident":
                update, transitions = self._materialize_incident(
                    aggregate_id,
                    markers,
                    session_contexts=session_contexts,
                    entry_attempt_ids=entry_attempt_ids,
                    materialized_at=materialized_at,
                    connection=connection,
                )
                if update is not None:
                    incident_updates.append(update)
                    incident_transitions.extend(transitions)
                continue
            raise RuntimeError(
                f"unsupported pending handoff aggregate: {aggregate_type}"
            )

        return PendingMaterializationResult(
            parking_result=ParkingPipelineResult(
                zone_visit_updates=(),
                parking_episode_updates=tuple(parking_updates),
                parking_transitions=tuple(parking_transitions),
                incident_updates=tuple(incident_updates),
                incident_transitions=tuple(incident_transitions),
                blocking_relation_updates=(),
            ),
            ordered_transitions=tuple(
                sorted(
                    (*parking_transitions, *incident_transitions),
                    key=_pending_transition_order,
                )
            ),
        )

    def mark_materialized(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        transition_type: str,
        occurred_at: datetime,
        delivery_id: str,
        updated_at_us: int,
        connection: sqlite3.Connection,
    ) -> None:
        """enqueue된 exact delivery와 같은 fact marker를 연결한다."""

        require_write_transaction(connection)
        repository = PendingHandoffRepository(connection)
        marker = repository.get_by_identity(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            transition_type=transition_type,
            original_occurred_at_us=datetime_to_epoch_microseconds(occurred_at),
        )
        if marker is None:
            return
        if marker.workflow_state is PendingHandoffState.MATERIALIZED:
            if marker.materialized_delivery_id != delivery_id:
                raise RuntimeError(
                    "pending handoff is linked to another delivery identity"
                )
            return
        if marker.workflow_state is PendingHandoffState.EXPIRED:
            raise RuntimeError("expired pending handoff cannot be materialized")
        repository.mark_materialized(
            marker.handoff_id,
            expected_record_version=marker.record_version,
            delivery_id=delivery_id,
            updated_at_us=max(updated_at_us, marker.updated_at_us),
        )

    def expire_due(
        self,
        *,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> int:
        """terminal·uncorrelated marker만 7일 retention 후 만료한다."""

        require_write_transaction(connection)
        require_aware(now, "now")
        now_us = datetime_to_epoch_microseconds(now)
        repository = PendingHandoffRepository(connection)
        expired_count = 0
        for marker in repository.list_due(now_us=now_us):
            terminal_at, physical_vehicle_id = self._terminal_scope(
                marker,
                connection=connection,
            )
            if terminal_at is None or physical_vehicle_id is None:
                continue
            attempt = self._authoritative_attempt_for_vehicle(
                physical_vehicle_id,
                connection=connection,
            )
            if self._has_materializable_correlation(
                marker,
                physical_vehicle_id=physical_vehicle_id,
                attempt=attempt,
                connection=connection,
            ):
                # 지금 실제로 publication을 만들 수 있는 marker는
                # 연령으로 숨기지 않고 materializer 오류로 드러낸다.
                continue
            if (
                attempt is not None
                and attempt.decision_state is EntryDecisionState.REVIEW_PENDING
            ):
                continue

            expiry = terminal_at + _HANDOFF_RETENTION
            if attempt is not None:
                expiry = max(expiry, attempt.updated_at + _HANDOFF_RETENTION)
            expiry_us = datetime_to_epoch_microseconds(expiry)
            current = marker
            if expiry_us > current.expires_at_us:
                current = repository.extend_expiry(
                    current.handoff_id,
                    expected_record_version=current.record_version,
                    expires_at_us=expiry_us,
                    updated_at_us=max(now_us, current.updated_at_us),
                )
            if now_us < current.expires_at_us:
                continue
            repository.mark_expired(
                current.handoff_id,
                expected_record_version=current.record_version,
                disposition_reason=_UNBOUND_CONTEXT_EXPIRED,
                updated_at_us=max(now_us, current.updated_at_us),
            )
            expired_count += 1
        return expired_count

    @staticmethod
    def _capture_parking_episode(
        repository: PendingHandoffRepository,
        episode: ParkingEpisode,
    ) -> None:
        if episode.publication_revision > 0 or episode.parked_at is None:
            return
        PendingHandoffWorkflow._ensure_marker(
            repository,
            aggregate_type="ParkingEpisode",
            aggregate_id=str(episode.episode_id),
            transition_type=ParkingTransitionType.PARKED.value,
            occurred_at=episode.parked_at,
            captured_at=episode.updated_at,
        )
        if (
            episode.state is ParkingState.ENDED
            and episode.termination_reason == MOVEMENT_CONFIRMED
            and episode.ended_at is not None
        ):
            PendingHandoffWorkflow._ensure_marker(
                repository,
                aggregate_type="ParkingEpisode",
                aggregate_id=str(episode.episode_id),
                transition_type=ParkingTransitionType.UNPARKED.value,
                occurred_at=episode.ended_at,
                captured_at=episode.updated_at,
            )
        if episode.ended_at is not None:
            PendingHandoffWorkflow._extend_aggregate_expiry(
                repository,
                aggregate_type="ParkingEpisode",
                aggregate_id=str(episode.episode_id),
                terminal_at=episode.ended_at,
                updated_at=episode.updated_at,
            )

    @staticmethod
    def _capture_incident(
        repository: PendingHandoffRepository,
        incident: Incident,
    ) -> None:
        if incident.publication_revision > 0 or incident.confirmed_at is None:
            return
        PendingHandoffWorkflow._ensure_marker(
            repository,
            aggregate_type="Incident",
            aggregate_id=str(incident.incident_id),
            transition_type=IncidentTransitionType.OPEN.value,
            occurred_at=incident.confirmed_at,
            captured_at=incident.updated_at,
        )
        if (
            incident.state is IncidentState.RESOLVED
            and incident.resolved_at is not None
        ):
            PendingHandoffWorkflow._ensure_marker(
                repository,
                aggregate_type="Incident",
                aggregate_id=str(incident.incident_id),
                transition_type=IncidentTransitionType.RESOLVE.value,
                occurred_at=incident.resolved_at,
                captured_at=incident.updated_at,
            )
        if incident.terminated_at is not None:
            PendingHandoffWorkflow._extend_aggregate_expiry(
                repository,
                aggregate_type="Incident",
                aggregate_id=str(incident.incident_id),
                terminal_at=incident.terminated_at,
                updated_at=incident.updated_at,
            )

    @staticmethod
    def _ensure_marker(
        repository: PendingHandoffRepository,
        *,
        aggregate_type: str,
        aggregate_id: str,
        transition_type: str,
        occurred_at: datetime,
        captured_at: datetime,
    ) -> None:
        occurred_at_us = datetime_to_epoch_microseconds(occurred_at)
        captured_at_us = datetime_to_epoch_microseconds(captured_at)
        identity = (
            f"{aggregate_type}:{aggregate_id}:{transition_type}:"
            f"{occurred_at_us}"
        )
        repository.ensure_waiting(
            PendingHandoffRecord(
                handoff_id=str(uuid5(NAMESPACE_URL, f"jetson:{identity}")),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                transition_type=transition_type,
                original_occurred_at_us=occurred_at_us,
                workflow_state=PendingHandoffState.WAITING_CORRELATION,
                expires_at_us=datetime_to_epoch_microseconds(
                    occurred_at + _HANDOFF_RETENTION
                ),
                record_version=1,
                created_at_us=max(occurred_at_us, captured_at_us),
                updated_at_us=max(occurred_at_us, captured_at_us),
            )
        )

    @staticmethod
    def _extend_aggregate_expiry(
        repository: PendingHandoffRepository,
        *,
        aggregate_type: str,
        aggregate_id: str,
        terminal_at: datetime,
        updated_at: datetime,
    ) -> None:
        expiry_us = datetime_to_epoch_microseconds(
            terminal_at + _HANDOFF_RETENTION
        )
        updated_at_us = datetime_to_epoch_microseconds(updated_at)
        for marker in repository.list_waiting_for_aggregate(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
        ):
            if expiry_us <= marker.expires_at_us:
                continue
            repository.extend_expiry(
                marker.handoff_id,
                expected_record_version=marker.record_version,
                expires_at_us=expiry_us,
                updated_at_us=max(updated_at_us, marker.updated_at_us),
            )

    @staticmethod
    def _historical_mirror(
        *,
        attempt: EntryMatchAttempt,
        vehicle,
        mirror: ParkingSessionMirror | None,
        presence_state: PhysicalPresenceState,
        updated_at: datetime,
    ) -> ParkingSessionMirror:
        context = attempt.authoritative_context
        session_id = attempt.authoritative_session_id
        if context is None or session_id is None:
            raise RuntimeError("historical mirror requires authoritative context")
        is_exited = presence_state is PhysicalPresenceState.EXITED
        publication_revision = (
            (0 if mirror is None else mirror.publication_revision) + 1
            if is_exited
            else (0 if mirror is None else mirror.publication_revision)
        )
        if mirror is None:
            return ParkingSessionMirror(
                parking_session_id=session_id,
                entry_attempt_id=attempt.entry_attempt_id,
                physical_vehicle_id=vehicle.physical_vehicle_id,
                administrative_state=SessionAdministrativeState.ACTIVE,
                physical_presence_state=presence_state,
                physical_observation=vehicle.observation,
                context_revision=attempt.decision_revision,
                last_context=context,
                physical_termination_origin=(
                    PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
                    if is_exited
                    else None
                ),
                physical_exit_evidence=(
                    PhysicalExitEvidence.FULL_AREA_ABSENCE
                    if is_exited
                    else None
                ),
                exited_at=vehicle.terminated_at if is_exited else None,
                record_version=1,
                publication_revision=publication_revision,
                created_at=attempt.created_at,
                updated_at=max(updated_at, attempt.updated_at),
            )
        return replace(
            mirror,
            entry_attempt_id=attempt.entry_attempt_id,
            physical_vehicle_id=vehicle.physical_vehicle_id,
            physical_presence_state=presence_state,
            physical_observation=vehicle.observation,
            context_revision=max(
                mirror.context_revision,
                attempt.decision_revision,
            ),
            last_context=mirror.last_context or context,
            physical_termination_origin=(
                PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
                if is_exited
                else None
            ),
            physical_exit_evidence=(
                PhysicalExitEvidence.FULL_AREA_ABSENCE if is_exited else None
            ),
            exited_at=vehicle.terminated_at if is_exited else None,
            record_version=mirror.record_version + 1,
            publication_revision=publication_revision,
            updated_at=max(updated_at, mirror.updated_at),
        )

    @staticmethod
    def _disable_historical_correlation(
        *,
        attempt: EntryMatchAttempt,
        mirror: ParkingSessionMirror | None,
        vehicle_observation: ObservationStatus,
        updated_at: datetime,
    ) -> ParkingSessionMirror:
        """복수 출차 correlation 입력을 재시도 가능한 conflict로 보존한다."""

        context = attempt.authoritative_context
        session_id = attempt.authoritative_session_id
        if context is None or session_id is None:
            raise RuntimeError("historical conflict requires authoritative context")
        if mirror is None:
            return ParkingSessionMirror(
                parking_session_id=session_id,
                entry_attempt_id=attempt.entry_attempt_id,
                administrative_state=SessionAdministrativeState.ACTIVE,
                physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
                physical_observation=vehicle_observation,
                context_revision=attempt.decision_revision,
                last_context=context,
                exit_correlation_enabled=False,
                record_version=1,
                publication_revision=0,
                created_at=attempt.created_at,
                updated_at=max(updated_at, attempt.updated_at),
            )

        is_closed = (
            mirror.administrative_state is SessionAdministrativeState.CLOSED
        )
        return replace(
            mirror,
            entry_attempt_id=attempt.entry_attempt_id,
            context_revision=max(
                mirror.context_revision,
                attempt.decision_revision,
            ),
            last_context=mirror.last_context or context,
            exit_correlation_enabled=False,
            terminated_at=(updated_at if is_closed else mirror.terminated_at),
            termination_reason=(
                _CORRELATION_CONFLICT
                if is_closed
                else mirror.termination_reason
            ),
            record_version=mirror.record_version + 1,
            updated_at=max(updated_at, mirror.updated_at),
        )

    @staticmethod
    def _save_mirror(
        repository: ParkingSessionMirrorRepository,
        existing: ParkingSessionMirror | None,
        updated: ParkingSessionMirror,
    ) -> None:
        if existing is None:
            repository.add(updated)
        else:
            repository.save(
                updated,
                expected_record_version=existing.record_version,
            )

    @staticmethod
    def _materialize_parking_episode(
        aggregate_id: str,
        markers: list[PendingHandoffRecord],
        *,
        session_contexts: Mapping[PhysicalVehicleId, SessionContext],
        materialized_at: datetime,
        connection: sqlite3.Connection,
    ) -> tuple[ParkingEpisode | None, tuple[ParkingTransition, ...]]:
        repository = ParkingEpisodeRepository(connection)
        episode = repository.get(ParkingEpisodeId(UUID(aggregate_id)))
        if episode is None:
            raise RuntimeError("pending handoff references a missing ParkingEpisode")
        if episode.publication_revision > 0:
            return None, ()
        context = session_contexts.get(episode.physical_vehicle_id)
        if context is None:
            context, _ = PendingHandoffWorkflow._durable_active_correlation(
                episode.physical_vehicle_id,
                connection=connection,
            )
        if context is None:
            return None, ()
        if episode.parking_session_id not in {
            None,
            context.parking_session_id,
        }:
            raise RuntimeError("ParkingEpisode session correlation cannot change")
        if episode.assignment is None or episode.parked_at is None:
            raise RuntimeError("PARKED handoff lost its assignment snapshot")

        marker_types = {marker.transition_type for marker in markers}
        allowed = {
            ParkingTransitionType.PARKED.value,
            ParkingTransitionType.UNPARKED.value,
        }
        if not marker_types.issubset(allowed):
            raise RuntimeError("invalid ParkingEpisode pending transition")
        if (
            ParkingTransitionType.UNPARKED.value in marker_types
            and (
                episode.state is not ParkingState.ENDED
                or episode.termination_reason != MOVEMENT_CONFIRMED
                or episode.ended_at is None
            )
        ):
            raise RuntimeError("UNPARKED marker requires MOVEMENT_CONFIRMED")
        if episode.termination_reason == PHYSICAL_EXIT:
            marker_types.discard(ParkingTransitionType.UNPARKED.value)

        revision = (
            2
            if ParkingTransitionType.UNPARKED.value in marker_types
            else 1
        )
        updated = replace(
            episode,
            parking_session_id=context.parking_session_id,
            publication_revision=revision,
            record_version=episode.record_version + 1,
            updated_at=max(materialized_at, episode.updated_at),
        )
        repository.save(
            updated,
            expected_record_version=episode.record_version,
        )
        transitions = [
            ParkingTransition(
                transition_type=ParkingTransitionType.PARKED,
                parking_episode_id=updated.episode_id,
                physical_vehicle_id=updated.physical_vehicle_id,
                parking_session_id=context.parking_session_id,
                publication_revision=1,
                occurred_at=updated.parked_at,
                assignment=updated.assignment,
            )
        ]
        if revision == 2:
            assert updated.ended_at is not None
            transitions.append(
                ParkingTransition(
                    transition_type=ParkingTransitionType.UNPARKED,
                    parking_episode_id=updated.episode_id,
                    physical_vehicle_id=updated.physical_vehicle_id,
                    parking_session_id=context.parking_session_id,
                    publication_revision=2,
                    occurred_at=updated.ended_at,
                    assignment=updated.assignment,
                )
            )
        return updated, tuple(transitions)

    @staticmethod
    def _materialize_incident(
        aggregate_id: str,
        markers: list[PendingHandoffRecord],
        *,
        session_contexts: Mapping[PhysicalVehicleId, SessionContext],
        entry_attempt_ids: Mapping[PhysicalVehicleId, EntryAttemptId],
        materialized_at: datetime,
        connection: sqlite3.Connection,
    ) -> tuple[Incident | None, tuple[IncidentTransition, ...]]:
        repository = IncidentRepository(connection)
        incident = repository.get(IncidentId(UUID(aggregate_id)))
        if incident is None:
            raise RuntimeError("pending handoff references a missing Incident")
        if incident.publication_revision > 0:
            return None, ()
        context = session_contexts.get(incident.physical_vehicle_id)
        entry_attempt_id = entry_attempt_ids.get(incident.physical_vehicle_id)
        if context is None or entry_attempt_id is None:
            durable_context, durable_entry_attempt_id = (
                PendingHandoffWorkflow._durable_active_correlation(
                    incident.physical_vehicle_id,
                    connection=connection,
                )
            )
            context = context or durable_context
            entry_attempt_id = entry_attempt_id or durable_entry_attempt_id
        if entry_attempt_id is None:
            attempt = PendingHandoffWorkflow._authoritative_attempt_for_vehicle(
                incident.physical_vehicle_id,
                connection=connection,
            )
            if attempt is not None:
                entry_attempt_id = attempt.entry_attempt_id
                if context is None and attempt.authoritative_context is not None:
                    context = attempt.authoritative_context
        if entry_attempt_id is None and context is None:
            return None, ()

        marker_types = {marker.transition_type for marker in markers}
        allowed = {
            IncidentTransitionType.OPEN.value,
            IncidentTransitionType.RESOLVE.value,
        }
        if not marker_types.issubset(allowed):
            raise RuntimeError("invalid Incident pending transition")
        if incident.confirmed_at is None:
            raise RuntimeError("OPEN marker lost confirmed_at")
        has_resolve = IncidentTransitionType.RESOLVE.value in marker_types
        if has_resolve and (
            incident.state is not IncidentState.RESOLVED
            or incident.resolved_at is None
        ):
            raise RuntimeError("RESOLVE marker requires terminal Incident")

        revision = 2 if has_resolve else 1
        updated = replace(
            incident,
            entry_attempt_id=(
                incident.entry_attempt_id or entry_attempt_id
            ),
            parking_session_id=(
                incident.parking_session_id
                or (None if context is None else context.parking_session_id)
            ),
            publication_revision=revision,
            record_version=incident.record_version + 1,
            updated_at=max(materialized_at, incident.updated_at),
        )
        repository.save(
            updated,
            expected_record_version=incident.record_version,
        )
        open_projection = replace(
            updated,
            state=IncidentState.OPEN,
            clear_trusted_seconds=0.0,
            publication_revision=1,
            resolved_at=None,
            terminated_at=None,
            termination_reason=None,
            updated_at=updated.confirmed_at,
        )
        transitions = [
            IncidentTransition(
                transition_type=IncidentTransitionType.OPEN,
                incident=open_projection,
            )
        ]
        if revision == 2:
            transitions.append(
                IncidentTransition(
                    transition_type=IncidentTransitionType.RESOLVE,
                    incident=updated,
                )
            )
        return updated, tuple(transitions)

    @staticmethod
    def _durable_active_correlation(
        physical_vehicle_id: PhysicalVehicleId,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[SessionContext | None, EntryAttemptId | None]:
        """미관측 차량의 active binding 정본을 durable row에서 복원한다."""

        binding = ContextBindingRepository(
            connection
        ).get_active_by_physical_vehicle_id(physical_vehicle_id)
        if binding is None:
            return None, None
        mirror = ParkingSessionMirrorRepository(connection).get(
            binding.parking_session_id
        )
        if mirror is None:
            raise RuntimeError(
                "active ContextBinding references a missing ParkingSessionMirror"
            )
        if (
            mirror.entry_attempt_id != binding.entry_attempt_id
            or mirror.physical_vehicle_id != physical_vehicle_id
            or mirror.administrative_state
            is not SessionAdministrativeState.ACTIVE
            or mirror.physical_presence_state
            is not PhysicalPresenceState.INSIDE
            or not mirror.exit_correlation_enabled
        ):
            raise RuntimeError(
                "active ContextBinding and ParkingSessionMirror disagree"
            )
        return binding.context, binding.entry_attempt_id

    @staticmethod
    def _competing_exit_correlation(
        physical_vehicle_id: PhysicalVehicleId,
        *,
        excluding_session_id: ParkingSessionId,
        connection: sqlite3.Connection,
    ) -> tuple[bool, EntryAttemptId | None]:
        """다른 session이 이미 소유한 출차 correlation을 찾는다.

        conflict가 있더라도 임의의 entry attempt를 고르지 않는다. 하나의
        authoritative attempt만 확인될 때에만 incident handoff가 그
        identity를 계속 사용할 수 있다.
        """

        rows = connection.execute(
            """
            SELECT entry_attempt_id
            FROM parking_session_mirrors
            WHERE physical_vehicle_id = ?
              AND exit_correlation_enabled = 1
              AND session_id <> ?
            ORDER BY created_at_us, session_id
            """,
            (str(physical_vehicle_id), int(excluding_session_id)),
        ).fetchall()
        if not rows:
            return False, None
        attempt_ids = {
            EntryAttemptId(UUID(str(row[0])))
            for row in rows
            if row[0] is not None
        }
        authoritative_attempt_id = (
            next(iter(attempt_ids)) if len(attempt_ids) == 1 else None
        )
        return True, authoritative_attempt_id

    @staticmethod
    def _authoritative_attempt_for_vehicle(
        physical_vehicle_id: PhysicalVehicleId,
        *,
        connection: sqlite3.Connection,
    ) -> EntryMatchAttempt | None:
        """출차 correlation이 정한 단일 entry attempt만 반환한다.

        historical conflict 뒤에는 한 PhysicalVehicle에 여러 MATCHED attempt가
        남을 수 있다. exit-enabled mirror가 존재하면 그 mirror가 정본이며,
        identity가 없거나 둘 이상이면 publication을 보류한다. mirror가 전혀
        없는 구형·DENY 흐름에서만 단일 MATCHED attempt로 fallback한다.
        """

        mirror_rows = connection.execute(
            """
            SELECT entry_attempt_id
            FROM parking_session_mirrors
            WHERE physical_vehicle_id = ?
              AND exit_correlation_enabled = 1
            ORDER BY created_at_us, session_id
            """,
            (str(physical_vehicle_id),),
        ).fetchall()
        repository = EntryMatchAttemptRepository(connection)
        if mirror_rows:
            attempt_ids = {
                EntryAttemptId(UUID(str(row[0])))
                for row in mirror_rows
                if row[0] is not None
            }
            if len(attempt_ids) != 1:
                return None
            return repository.get(next(iter(attempt_ids)))

        attempt_rows = connection.execute(
            """
            SELECT entry_attempt_id
            FROM entry_match_attempts
            WHERE match_state = 'MATCHED'
              AND physical_vehicle_id = ?
            ORDER BY match_terminated_at_us, entry_attempt_id
            """,
            (str(physical_vehicle_id),),
        ).fetchall()
        if len(attempt_rows) != 1:
            return None
        return repository.get(EntryAttemptId(UUID(str(attempt_rows[0][0]))))

    @staticmethod
    def _has_materializable_correlation(
        marker: PendingHandoffRecord,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        attempt: EntryMatchAttempt | None,
        connection: sqlite3.Connection,
    ) -> bool:
        """현재 materializer 입력이 충족된 marker인지 반환한다."""

        context, entry_attempt_id = (
            PendingHandoffWorkflow._durable_active_correlation(
                physical_vehicle_id,
                connection=connection,
            )
        )
        if marker.aggregate_type == "ParkingEpisode":
            return context is not None
        if marker.aggregate_type == "Incident":
            return entry_attempt_id is not None or attempt is not None
        raise RuntimeError(
            f"unsupported pending handoff aggregate: {marker.aggregate_type}"
        )

    @staticmethod
    def _terminal_scope(
        marker: PendingHandoffRecord,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[datetime | None, PhysicalVehicleId | None]:
        if marker.aggregate_type == "ParkingEpisode":
            episode = ParkingEpisodeRepository(connection).get(
                ParkingEpisodeId(UUID(marker.aggregate_id))
            )
            if episode is None:
                raise RuntimeError(
                    "pending handoff references a missing ParkingEpisode"
                )
            return episode.ended_at, episode.physical_vehicle_id
        if marker.aggregate_type == "Incident":
            incident = IncidentRepository(connection).get(
                IncidentId(UUID(marker.aggregate_id))
            )
            if incident is None:
                raise RuntimeError(
                    "pending handoff references a missing Incident"
                )
            return incident.terminated_at, incident.physical_vehicle_id
        raise RuntimeError(
            f"unsupported pending handoff aggregate: {marker.aggregate_type}"
        )


def _latest_by_id(items: tuple[object, ...], attribute: str) -> dict:
    latest: dict = {}
    for item in items:
        latest[getattr(item, attribute)] = item
    return latest


def _pending_transition_order(
    transition: ParkingTransition | IncidentTransition,
) -> tuple[datetime, int, str, str]:
    """occurredAt 다음 revision·identity로 결정적 순서를 만든다."""

    if isinstance(transition, ParkingTransition):
        return (
            transition.occurred_at,
            transition.publication_revision,
            "ParkingEpisode",
            str(transition.parking_episode_id),
        )
    occurred_at = (
        transition.incident.confirmed_at
        if transition.transition_type is IncidentTransitionType.OPEN
        else transition.incident.resolved_at
    )
    if occurred_at is None:
        raise RuntimeError("Incident pending publication lost occurredAt")
    return (
        occurred_at,
        transition.incident.publication_revision,
        "Incident",
        str(transition.incident.incident_id),
    )
