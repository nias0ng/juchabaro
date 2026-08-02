"""NOT_PRESENT_CONFIRMED를 하나의 durable 물리 종료로 조립한다.

이 workflow는 tracking timeout을 출차로 바꾸지 않는다. TrackingBatch가
정상 전체 관측으로 확정한 ``NOT_PRESENT_CONFIRMED``만 받아
session correlation을 고정하고 child scope를 종료한다. 모든 변경은
상위 frame UnitOfWork에 참여하며, TrackingPipeline ACK는 commit 뒤에만
호출되어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import sqlite3

from src.domain.models import require_aware, require_positive
from src.parking.models import ParkingPipelineResult
from src.parking.pipeline import ParkingPipeline
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.models import (
    PhysicalExitEvidence,
    PhysicalPresenceState,
    PhysicalTerminationOrigin,
)
from src.storage.repositories import (
    ContextBindingRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import require_write_transaction
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


SESSION_EXITED = "SESSION_EXITED"
PHYSICAL_VEHICLE_LEFT = "PHYSICAL_VEHICLE_LEFT"


class UnfinishedPhysicalVehicleScopeError(RuntimeError):
    """PhysicalVehicle를 RETIRED하기 전 nonterminal child가 남아 있다."""


@dataclass(frozen=True, kw_only=True)
class SessionExitTransition:
    """Backend wire를 결정하지 않은 Session EXIT 의미 projection."""

    parking_session_id: ParkingSessionId
    physical_vehicle_id: PhysicalVehicleId
    publication_revision: int
    occurred_at: datetime
    origin: PhysicalTerminationOrigin
    evidence: PhysicalExitEvidence

    def __post_init__(self) -> None:
        require_positive(self.publication_revision, "publication_revision")
        require_aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True, kw_only=True)
class PhysicalDeparturePlan:
    """child 저장 후 PhysicalVehicle RETIRED를 검증할 종료 plan."""

    physical_vehicle_id: PhysicalVehicleId
    parking_result: ParkingPipelineResult
    session_exit_transition: SessionExitTransition | None
    termination_reason: str
    already_terminal: bool = False


class PhysicalPresenceWorkflow:
    """PhysicalVehicle 출차의 session·child·presence 경계를 소유한다."""

    def __init__(
        self,
        *,
        context_binding_coordinator: ContextBindingCoordinator,
        parking_pipeline: ParkingPipeline,
    ) -> None:
        self._context_binding_coordinator = context_binding_coordinator
        self._parking_pipeline = parking_pipeline

    def plan_departure(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        connection: sqlite3.Connection,
    ) -> PhysicalDeparturePlan:
        """session correlation을 고정하고 종료할 aggregate snapshot을 만든다."""

        require_write_transaction(connection)
        vehicle_repository = PhysicalVehicleRepository(connection)
        vehicle = vehicle_repository.get(physical_vehicle_id)
        if vehicle is None:
            raise RuntimeError(
                "NOT_PRESENT_CONFIRMED references a missing PhysicalVehicle"
            )
        if vehicle.state in {
            PhysicalVehicleState.RETIRED,
            PhysicalVehicleState.CANCELED,
        }:
            return PhysicalDeparturePlan(
                physical_vehicle_id=physical_vehicle_id,
                parking_result=_empty_parking_result(),
                session_exit_transition=None,
                termination_reason=(
                    vehicle.termination_reason or PHYSICAL_VEHICLE_LEFT
                ),
                already_terminal=True,
            )
        if vehicle.absence_confirmed_at is None:
            raise RuntimeError(
                "PhysicalVehicle departure requires durable absence_confirmed_at"
            )
        occurred_at = vehicle.absence_confirmed_at

        binding_repository = ContextBindingRepository(connection)
        mirror_repository = ParkingSessionMirrorRepository(connection)
        binding = binding_repository.get_active_by_physical_vehicle_id(
            physical_vehicle_id
        )
        mirror = None
        if binding is not None:
            mirror = mirror_repository.get(binding.parking_session_id)
            if mirror is None:
                raise RuntimeError(
                    "active ContextBinding references a missing ParkingSessionMirror"
                )
            if (
                not mirror.exit_correlation_enabled
                or mirror.physical_presence_state
                is PhysicalPresenceState.EXITED
            ):
                raise RuntimeError(
                    "active ContextBinding references a disabled exit correlation"
                )
        else:
            # ADMIN_CLOSED로 binding이 먼저 끝나도 보존한
            # session–vehicle correlation은 실제 출차에 사용한다.
            mirror = mirror_repository.get_exit_enabled_by_physical_vehicle_id(
                physical_vehicle_id
            )

        termination_reason = (
            SESSION_EXITED if mirror is not None else PHYSICAL_VEHICLE_LEFT
        )
        parking_result = self._parking_pipeline.physical_exit(
            physical_vehicle_id=physical_vehicle_id,
            observed_at=occurred_at,
            incident_termination_reason=termination_reason,
        )

        if binding is not None:
            ended_binding = self._context_binding_coordinator.end(
                binding,
                # commit retry 사이 context checkpoint가 더 느린
                # application 시각으로 갱신될 수 있다. 출차 fact의
                # occurredAt은 SessionExit에 그대로 보존하되 binding
                # storage 시각은 단조 증가를 유지한다.
                ended_at=max(occurred_at, binding.updated_at),
                reason=termination_reason,
            )
            binding_repository.save(
                ended_binding,
                expected_record_version=binding.record_version,
            )

        session_exit: SessionExitTransition | None = None
        if mirror is not None:
            if mirror.physical_vehicle_id != physical_vehicle_id:
                raise RuntimeError(
                    "exit correlation references another PhysicalVehicle"
                )
            exited_mirror = replace(
                mirror,
                physical_presence_state=PhysicalPresenceState.EXITED,
                physical_observation=vehicle.observation,
                physical_termination_origin=(
                    PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
                ),
                physical_exit_evidence=PhysicalExitEvidence.FULL_AREA_ABSENCE,
                exited_at=occurred_at,
                record_version=mirror.record_version + 1,
                publication_revision=mirror.publication_revision + 1,
                updated_at=max(occurred_at, mirror.updated_at),
            )
            mirror_repository.save(
                exited_mirror,
                expected_record_version=mirror.record_version,
            )
            session_exit = SessionExitTransition(
                parking_session_id=mirror.parking_session_id,
                physical_vehicle_id=physical_vehicle_id,
                publication_revision=exited_mirror.publication_revision,
                occurred_at=occurred_at,
                origin=PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED,
                evidence=PhysicalExitEvidence.FULL_AREA_ABSENCE,
            )

        return PhysicalDeparturePlan(
            physical_vehicle_id=physical_vehicle_id,
            parking_result=parking_result,
            session_exit_transition=session_exit,
            termination_reason=termination_reason,
        )

    def complete_departure(
        self,
        plan: PhysicalDeparturePlan,
        *,
        connection: sqlite3.Connection,
    ) -> None:
        """child snapshot 저장 후 남은 active scope를 검증하고 RETIRED한다."""

        require_write_transaction(connection)
        if plan.already_terminal:
            return
        active_scopes = _active_scope_names(
            connection,
            plan.physical_vehicle_id,
        )
        if active_scopes:
            raise UnfinishedPhysicalVehicleScopeError(
                "cannot retire PhysicalVehicle with active scopes: "
                + ", ".join(active_scopes)
            )

        repository = PhysicalVehicleRepository(connection)
        vehicle = repository.get(plan.physical_vehicle_id)
        if vehicle is None:
            raise RuntimeError("PhysicalVehicle disappeared before retirement")
        if vehicle.state is not PhysicalVehicleState.ACTIVE:
            if vehicle.state in {
                PhysicalVehicleState.RETIRED,
                PhysicalVehicleState.CANCELED,
            }:
                return
            raise RuntimeError("only an ACTIVE PhysicalVehicle may be retired")
        occurred_at = vehicle.absence_confirmed_at
        if occurred_at is None:
            raise RuntimeError("retirement lost absence_confirmed_at")
        retired = replace(
            vehicle,
            state=PhysicalVehicleState.RETIRED,
            record_version=vehicle.record_version + 1,
            terminated_at=occurred_at,
            termination_reason=plan.termination_reason,
            updated_at=max(vehicle.updated_at, occurred_at),
        )
        repository.save(
            retired,
            expected_record_version=vehicle.record_version,
        )


def _active_scope_names(
    connection: sqlite3.Connection,
    physical_vehicle_id: PhysicalVehicleId,
) -> tuple[str, ...]:
    """미구현 child까지 포함해 조용히 유실되는 종료를 막는다."""

    identity = str(physical_vehicle_id)
    checks = (
        (
            "ContextBinding",
            """SELECT 1 FROM context_bindings
               WHERE physical_vehicle_id = ? AND domain_state = 'BOUND'
               LIMIT 1""",
            (identity,),
        ),
        (
            "ZoneVisit",
            """SELECT 1 FROM zone_visits
               WHERE physical_vehicle_id = ?
                 AND domain_state IN ('ENTERING', 'INSIDE', 'EXITING')
               LIMIT 1""",
            (identity,),
        ),
        (
            "ParkingEpisode",
            """SELECT 1 FROM parking_episodes
               WHERE physical_vehicle_id = ?
                 AND domain_state IN ('STOP_PENDING', 'PARKED', 'MOVE_PENDING')
               LIMIT 1""",
            (identity,),
        ),
        (
            "BlockingRelation",
            """SELECT 1 FROM blocking_relations
               WHERE (subject_physical_vehicle_id = ?
                      OR victim_physical_vehicle_id = ?)
                 AND domain_state IN ('CANDIDATE', 'BLOCKING', 'CLEAR_PENDING')
               LIMIT 1""",
            (identity, identity),
        ),
        (
            "Incident",
            """SELECT 1 FROM incidents
               WHERE (subject_physical_vehicle_id = ?
                      OR victim_physical_vehicle_id = ?)
                 AND domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING')
               LIMIT 1""",
            (identity, identity),
        ),
        (
            "MoveVerificationAttempt",
            """SELECT 1 FROM move_verification_attempts
               WHERE subject_physical_vehicle_id = ?
                 AND domain_state IN ('ACCEPTED', 'CHECKING')
               LIMIT 1""",
            (identity,),
        ),
    )
    return tuple(
        name
        for name, query, parameters in checks
        if connection.execute(query, parameters).fetchone() is not None
    )


def _empty_parking_result() -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(),
        incident_transitions=(),
    )
