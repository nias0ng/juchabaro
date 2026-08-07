"""NOT_PRESENT_CONFIRMED를 하나의 durable 물리 종료로 조립한다.

이 workflow는 tracking timeout을 출차로 바꾸지 않는다. TrackingBatch가
정상 전체 관측으로 확정한 ``NOT_PRESENT_CONFIRMED``만 받아
session correlation을 고정하고 child scope를 종료한다. 모든 변경은
상위 frame UnitOfWork에 참여하며, TrackingPipeline ACK는 commit 뒤에만
호출되어야 한다.

부재 확정을 곧 출차로 발행하지는 않는다(565). 단일 카메라에서 "전체 영역"은
카메라 화각이므로, 주차장 안에 있으면서 화각만 벗어난 차량과 실제로 나간
차량을 부재만으로 구분할 수 없다. 그래서 명시적인 출차 기준선의 외향 통과를
트래킹 시점에 durable checkpoint로 고정하고, 이 checkpoint가 남아 있는
부재만 SessionExit으로 발행한다. 외향 통과 후 다시 내향으로 연속 관측되면
checkpoint를 무효화한다. 그렇지 않은 부재는 로컬 수명주기만 닫고,
진단을 위해 PhysicalVehicle의 termination_reason에
``ABSENCE_WITHOUT_EXIT_EVIDENCE``를 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import logging
import sqlite3

from src.domain.models import require_aware, require_positive
from src.parking.models import (
    ExitTraversalObservation,
    ExitTraversalSide,
    ParkingPipelineResult,
)
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
from src.storage.exit_traversal_checkpoint_repository import (
    ExitTraversalCheckpointRepository,
)
from src.storage.models import ExitTraversalCheckpointRecord
from src.storage.unit_of_work import require_write_transaction
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


SESSION_EXITED = "SESSION_EXITED"
PHYSICAL_VEHICLE_LEFT = "PHYSICAL_VEHICLE_LEFT"
ABSENCE_WITHOUT_EXIT_EVIDENCE = "ABSENCE_WITHOUT_EXIT_EVIDENCE"

logger = logging.getLogger(__name__)


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
    vehicle_termination_reason: str
    already_terminal: bool = False


class PhysicalPresenceWorkflow:
    """PhysicalVehicle 출차의 session·child·presence 경계를 소유한다."""

    def __init__(
        self,
        *,
        context_binding_coordinator: ContextBindingCoordinator,
        parking_pipeline: ParkingPipeline,
        exit_reentry_confirmation_seconds: float,
    ) -> None:
        require_positive(
            exit_reentry_confirmation_seconds,
            "exit_reentry_confirmation_seconds",
        )
        self._context_binding_coordinator = context_binding_coordinator
        self._parking_pipeline = parking_pipeline
        self._exit_reentry_confirmation_seconds = (
            exit_reentry_confirmation_seconds
        )

    def apply_exit_traversal_observations(
        self,
        observations: tuple[ExitTraversalObservation, ...],
        *,
        connection: sqlite3.Connection,
    ) -> None:
        """trusted 기준선 관측을 현재 UnitOfWork의 latch에 반영한다.

        ``OUTWARD``는 최초 외향 통과를 고정하고, ``INWARD``는 같은
        출차 구역의 연속 내향 관측 시간을 누적한다. 샘플 간격이
        확정 기간보다 크면 연속성이 끊긴 것으로 보고 누적을 다시
        시작한다. ``NEUTRAL``과 새 ``OUTWARD``는 재진입 후보만 취소한다.
        """

        require_write_transaction(connection)
        repository = ExitTraversalCheckpointRepository(connection)
        vehicle_repository = PhysicalVehicleRepository(connection)
        for observation in sorted(
            observations,
            key=lambda item: (
                item.observed_at,
                int(item.exit_zone_id),
                str(item.exit_zone_visit_id),
            ),
        ):
            vehicle = vehicle_repository.get(observation.physical_vehicle_id)
            if (
                vehicle is None
                or vehicle.state is not PhysicalVehicleState.ACTIVE
            ):
                continue

            checkpoint = repository.get(observation.physical_vehicle_id)
            if checkpoint is not None and (
                observation.observed_at <= checkpoint.updated_at
            ):
                # commit retry의 중복 샘플과 역순 전달은 도메인 시간을
                # 되돌리지 않는다.
                continue

            if observation.side is ExitTraversalSide.OUTWARD:
                if checkpoint is None:
                    repository.add(
                        ExitTraversalCheckpointRecord(
                            physical_vehicle_id=(
                                observation.physical_vehicle_id
                            ),
                            exit_zone_id=observation.exit_zone_id,
                            exit_zone_visit_id=(
                                observation.exit_zone_visit_id
                            ),
                            zone_definition_version=(
                                observation.zone_definition_version
                            ),
                            outward_observed_at=observation.observed_at,
                            reentry_candidate_at=None,
                            reentry_trusted_seconds=0.0,
                            reentry_confirmation_seconds=(
                                self._exit_reentry_confirmation_seconds
                            ),
                            last_trusted_sample_at=None,
                            record_version=1,
                            updated_at=observation.observed_at,
                        )
                    )
                    continue
                if (
                    observation.exit_zone_id != checkpoint.exit_zone_id
                    or observation.exit_zone_visit_id
                    != checkpoint.exit_zone_visit_id
                    or observation.zone_definition_version
                    != checkpoint.zone_definition_version
                ):
                    repository.delete(
                        checkpoint.physical_vehicle_id,
                        expected_record_version=checkpoint.record_version,
                    )
                    repository.add(
                        ExitTraversalCheckpointRecord(
                            physical_vehicle_id=(
                                observation.physical_vehicle_id
                            ),
                            exit_zone_id=observation.exit_zone_id,
                            exit_zone_visit_id=(
                                observation.exit_zone_visit_id
                            ),
                            zone_definition_version=(
                                observation.zone_definition_version
                            ),
                            outward_observed_at=observation.observed_at,
                            reentry_candidate_at=None,
                            reentry_trusted_seconds=0.0,
                            reentry_confirmation_seconds=(
                                self._exit_reentry_confirmation_seconds
                            ),
                            last_trusted_sample_at=None,
                            record_version=1,
                            updated_at=observation.observed_at,
                        )
                    )
                    continue
                self._reset_reentry_progress(
                    repository,
                    checkpoint,
                    updated_at=observation.observed_at,
                )
                continue

            if checkpoint is None:
                continue
            if observation.side is ExitTraversalSide.NEUTRAL:
                self._reset_reentry_progress(
                    repository,
                    checkpoint,
                    updated_at=observation.observed_at,
                )
                continue
            if observation.side is not ExitTraversalSide.INWARD:
                raise RuntimeError(
                    f"unsupported exit traversal side: {observation.side!r}"
                )
            if (
                observation.exit_zone_id != checkpoint.exit_zone_id
                or observation.zone_definition_version
                != checkpoint.zone_definition_version
            ):
                continue
            self._apply_inward_observation(
                repository,
                checkpoint,
                observed_at=observation.observed_at,
            )

    @staticmethod
    def _reset_reentry_progress(
        repository: ExitTraversalCheckpointRepository,
        checkpoint: ExitTraversalCheckpointRecord,
        *,
        updated_at: datetime,
    ) -> None:
        repository.save(
            replace(
                checkpoint,
                reentry_candidate_at=None,
                reentry_trusted_seconds=0.0,
                last_trusted_sample_at=None,
                record_version=checkpoint.record_version + 1,
                updated_at=updated_at,
            ),
            expected_record_version=checkpoint.record_version,
        )

    @staticmethod
    def _apply_inward_observation(
        repository: ExitTraversalCheckpointRepository,
        checkpoint: ExitTraversalCheckpointRecord,
        *,
        observed_at: datetime,
    ) -> None:
        last_sample = checkpoint.last_trusted_sample_at
        if checkpoint.reentry_candidate_at is None or last_sample is None:
            accumulated = replace(
                checkpoint,
                reentry_candidate_at=observed_at,
                reentry_trusted_seconds=0.0,
                last_trusted_sample_at=observed_at,
                record_version=checkpoint.record_version + 1,
                updated_at=observed_at,
            )
            repository.save(
                accumulated,
                expected_record_version=checkpoint.record_version,
            )
            return

        sample_gap_seconds = (observed_at - last_sample).total_seconds()
        if sample_gap_seconds > checkpoint.reentry_confirmation_seconds:
            trusted_seconds = 0.0
            candidate_at = observed_at
        else:
            trusted_seconds = (
                checkpoint.reentry_trusted_seconds + sample_gap_seconds
            )
            candidate_at = checkpoint.reentry_candidate_at

        if trusted_seconds >= checkpoint.reentry_confirmation_seconds:
            repository.delete(
                checkpoint.physical_vehicle_id,
                expected_record_version=checkpoint.record_version,
            )
            return
        repository.save(
            replace(
                checkpoint,
                reentry_candidate_at=candidate_at,
                reentry_trusted_seconds=trusted_seconds,
                last_trusted_sample_at=observed_at,
                record_version=checkpoint.record_version + 1,
                updated_at=observed_at,
            ),
            expected_record_version=checkpoint.record_version,
        )

    def plan_departure(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        connection: sqlite3.Connection,
    ) -> PhysicalDeparturePlan:
        """session correlation을 고정하고 종료할 aggregate snapshot을 만든다."""

        require_write_transaction(connection)
        vehicle_repository = PhysicalVehicleRepository(connection)
        checkpoint_repository = ExitTraversalCheckpointRepository(connection)
        vehicle = vehicle_repository.get(physical_vehicle_id)
        if vehicle is None:
            raise RuntimeError(
                "NOT_PRESENT_CONFIRMED references a missing PhysicalVehicle"
            )
        if vehicle.state in {
            PhysicalVehicleState.RETIRED,
            PhysicalVehicleState.CANCELED,
        }:
            stale_checkpoint = checkpoint_repository.get(physical_vehicle_id)
            if stale_checkpoint is not None:
                checkpoint_repository.delete(
                    physical_vehicle_id,
                    expected_record_version=stale_checkpoint.record_version,
                )
            existing_reason = vehicle.termination_reason or PHYSICAL_VEHICLE_LEFT
            return PhysicalDeparturePlan(
                physical_vehicle_id=physical_vehicle_id,
                parking_result=_empty_parking_result(),
                session_exit_transition=None,
                termination_reason=existing_reason,
                vehicle_termination_reason=existing_reason,
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

        traversal_checkpoint = checkpoint_repository.get(physical_vehicle_id)
        traversal_observed = traversal_checkpoint is not None
        termination_reason = (
            SESSION_EXITED if mirror is not None else PHYSICAL_VEHICLE_LEFT
        )
        vehicle_termination_reason = (
            termination_reason
            if traversal_observed
            else ABSENCE_WITHOUT_EXIT_EVIDENCE
        )
        if not traversal_observed:
            logger.warning(
                "부재가 확정됐지만 출차 구역 통과가 관측되지 않아 SessionExit을 "
                "발행하지 않습니다: physical_vehicle_id=%s session_id=%s "
                "absence_confirmed_at=%s",
                physical_vehicle_id,
                None if mirror is None else mirror.parking_session_id,
                occurred_at,
            )
        parking_result = self._parking_pipeline.physical_exit(
            physical_vehicle_id=physical_vehicle_id,
            observed_at=occurred_at,
            incident_termination_reason=termination_reason,
        )
        if traversal_checkpoint is not None:
            checkpoint_repository.delete(
                physical_vehicle_id,
                expected_record_version=traversal_checkpoint.record_version,
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
        if mirror is not None and traversal_observed:
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
                physical_exit_evidence=PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL,
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
                evidence=PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL,
            )

        return PhysicalDeparturePlan(
            physical_vehicle_id=physical_vehicle_id,
            parking_result=parking_result,
            session_exit_transition=session_exit,
            termination_reason=termination_reason,
            vehicle_termination_reason=vehicle_termination_reason,
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
            termination_reason=plan.vehicle_termination_reason,
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
        (
            "ExitTraversalCheckpoint",
            """SELECT 1 FROM exit_traversal_checkpoints
               WHERE physical_vehicle_id = ?
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
