"""Monitoring runtime의 domain owner와 Unit of Work를 한곳에서 조립한다.

이 모듈은 정책값이나 장치 구현을 선택하지 않는다. 배포 계층이 검증된
ZoneRegistry, camera·detector, exact wire ``PublicationPreparer``와 모든
threshold를 명시적으로 주입해야 한다. Backend wire 계약 전 임시 serializer나
no-op publisher를 만들지 않는 것이 이 composition root의 경계다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sqlite3

from src.actuators.ports import ActuatorCommandPlanner, ActuatorPort
from src.application.frame_observation_workflow import (
    FrameObservationWorkflow,
    PublicationPreparer,
)
from src.application.monitoring_pipeline import MonitoringPipeline
from src.application.session_observation_workflow import (
    SessionObservationWorkflow,
)
from src.camera.frame_source import FrameSource
from src.parking.blocking_relation_tracker import InMemoryBlockingRelationTracker
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.parking_episode_tracker import InMemoryParkingEpisodeTracker
from src.parking.pipeline import ParkingPipeline
from src.parking.zone_registry import ZoneRegistry
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.tracking.motion_estimator import MotionEstimator
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import Detector, EntityResolver


@dataclass(frozen=True, kw_only=True)
class MonitoringPolicy:
    """한 배포가 명시해야 하는 monitoring 판단값 모음.

    실측 전 임의 기본값을 코드에 숨기지 않는다. 각 domain owner가 자신의
    단위·범위 검증을 수행하므로 factory는 같은 검증을 중복하지 않는다.
    """

    zone_entry_confirm_seconds: float
    zone_exit_confirm_seconds: float
    entry_zone_min_overlap_ratio: float
    parking_confirm_seconds: float
    parking_move_confirm_seconds: float
    absence_confirmation_seconds: float
    trusted_sample_max_gap_seconds: float
    incident_confirm_seconds: float
    incident_clear_seconds: float
    zone_presence_min_overlap_ratio: float
    assignment_min_overlap_ratio: float
    assignment_ambiguous_margin: float
    bad_parking_min_primary_overlap_ratio: float
    blocking_relation_confirm_seconds: float
    blocking_relation_clear_seconds: float


@dataclass(frozen=True, kw_only=True)
class MonitoringDependencies:
    """배포·adapter 계층이 소유하는 runtime 의존성."""

    camera_id: str
    frame_source: FrameSource
    detector: Detector
    publication_preparer: PublicationPreparer
    connection_factory: Callable[[], sqlite3.Connection]
    entity_resolver: EntityResolver | None = None
    # 리플레이 검증 CLI가 movement_epsilon을 실측으로 바꿔가며 돌릴 수 있게
    # 열어 둔 자리다(465/T-17). 생략하면 TrackingPipeline이 자기 기본
    # MotionEstimator를 쓴다 — 배포 경로의 동작은 달라지지 않는다.
    motion_estimator: MotionEstimator | None = None
    actuator_command_planner: ActuatorCommandPlanner | None = None
    actuator_port: ActuatorPort | None = None


def build_monitoring_pipeline(
    *,
    zones: ZoneRegistry,
    policy: MonitoringPolicy,
    dependencies: MonitoringDependencies,
) -> MonitoringPipeline:
    """tracking·session·parking·storage를 한 frame transaction으로 조립한다."""

    entry_match_coordinator = EntryMatchCoordinator(
        zones=zones,
        entry_zone_min_overlap_ratio=policy.entry_zone_min_overlap_ratio,
    )
    context_binding_coordinator = ContextBindingCoordinator()
    session_workflow = SessionObservationWorkflow(
        entry_match_coordinator=entry_match_coordinator,
        context_binding_coordinator=context_binding_coordinator,
        absence_confirmation_seconds=policy.absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=(
            policy.trusted_sample_max_gap_seconds
        ),
    )
    parking_pipeline = ParkingPipeline(
        zones=zones,
        zone_visit_tracker=InMemoryZoneVisitTracker(
            zone_definition_version=zones.zone_definition_version,
            entry_confirm_seconds=policy.zone_entry_confirm_seconds,
            exit_confirm_seconds=policy.zone_exit_confirm_seconds,
            trusted_sample_max_gap_seconds=(
                policy.trusted_sample_max_gap_seconds
            ),
        ),
        parking_episode_tracker=InMemoryParkingEpisodeTracker(
            parking_confirmation_seconds=policy.parking_confirm_seconds,
            movement_confirmation_seconds=(
                policy.parking_move_confirm_seconds
            ),
            trusted_sample_max_gap_seconds=(
                policy.trusted_sample_max_gap_seconds
            ),
        ),
        incident_reducer=InMemoryIncidentReducer(
            trusted_sample_max_gap_seconds=(
                policy.trusted_sample_max_gap_seconds
            ),
            confirm_duration_seconds=policy.incident_confirm_seconds,
            clear_duration_seconds=policy.incident_clear_seconds,
        ),
        blocking_relation_tracker=InMemoryBlockingRelationTracker(
            confirm_duration_seconds=policy.blocking_relation_confirm_seconds,
            clear_duration_seconds=policy.blocking_relation_clear_seconds,
            trusted_sample_max_gap_seconds=(
                policy.trusted_sample_max_gap_seconds
            ),
        ),
        min_overlap_ratio=policy.zone_presence_min_overlap_ratio,
        assignment_min_overlap_ratio=(
            policy.assignment_min_overlap_ratio
        ),
        assignment_ambiguous_margin=(
            policy.assignment_ambiguous_margin
        ),
        bad_parking_min_primary_overlap_ratio=(
            policy.bad_parking_min_primary_overlap_ratio
        ),
    )
    frame_workflow = FrameObservationWorkflow(
        session_workflow=session_workflow,
        parking_pipeline=parking_pipeline,
        context_binding_coordinator=context_binding_coordinator,
        publication_preparer=dependencies.publication_preparer,
    )
    tracking_pipeline = TrackingPipeline(
        camera_id=dependencies.camera_id,
        detector=dependencies.detector,
        entity_resolver=dependencies.entity_resolver,
        motion_estimator=dependencies.motion_estimator,
        absence_confirmation_seconds=policy.absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=(
            policy.trusted_sample_max_gap_seconds
        ),
    )
    return MonitoringPipeline(
        frame_source=dependencies.frame_source,
        tracking_pipeline=tracking_pipeline,
        frame_workflow=frame_workflow,
        connection_factory=dependencies.connection_factory,
        calibration_reference=zones.calibration_reference,
        actuator_command_planner=dependencies.actuator_command_planner,
        actuator_port=dependencies.actuator_port,
    )
