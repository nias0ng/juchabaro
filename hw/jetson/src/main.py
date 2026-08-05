"""Jetson FastAPI application composition root.

DB, zones, evidence, publication, monitoring lifecycle을 하나의 lifespan에서
소유한다. module-level ``src.main:app``은 운영 camera·tracking factory와
정확한 Backend publication wire를 결속해 단일 MonitoringWorker를 기동한다.

``create_app()``의 optional factory 경계는 API-only 테스트와 명시적
dependency injection을 위해 유지하며, 운영 경로에 임시 serializer나
no-op publisher가 섞이지 않도록 한다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from src.api.error_handlers import register_error_handlers
from src.api.entry_events_router import router as entry_events_router
from src.api.health_router import router as health_router
from src.api.internal_commands_router import router as internal_commands_router
from src.application.entry_event_intake import EntryEventIntake
from src.application.entry_review_resolution_intake import (
    EntryReviewResolutionIntake,
)
from src.application.evidence_publication_worker import (
    EvidencePublicationPublisher,
    EvidencePublicationWorker,
)
from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.application.monitoring_pipeline import MonitoringPipeline
from src.application.monitoring_worker import MonitoringWorker
from src.application.move_verification_executor import (
    MoveVerificationExecutor,
    MoveVerificationExecutorWorker,
)
from src.application.move_verification_intake import MoveVerificationIntake
from src.application.outbox_publisher import (
    OutboxPublisher,
    OutboxPublisherWorker,
)
from src.application.session_context_update_intake import (
    SessionContextUpdateIntake,
)
from src.camera.calibration_utils import load_calibration
from src.camera.frame_source import (
    OpenCvWebcamFrameSource,
    RemapFrameSource,
    calibration_fingerprint,
)
from src.communication.backend_client import BackendClient
from src.communication.backend_publication_preparer import (
    BackendPublicationPreparer,
)
from src.config.settings import Settings, get_settings
from src.evidence.capture import EvidenceCaptureCoordinator
from src.parking.zone_registry import ZoneRegistry
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.storage.database import connect_database, open_database
from src.tracking.adapters.side_masking_detector import (
    SideMaskingDetector,
    compute_mask_ratios_from_zones,
)
from src.tracking.adapters.ultralytics_bytetrack import (
    UltralyticsVehicleTracker,
)


DatabaseConnectionFactory = Callable[[], sqlite3.Connection]


@dataclass(frozen=True)
class RuntimeContext:
    """확정된 기동 설정·구역·DB·outbound wire adapter 경계."""

    settings: Settings
    zones: ZoneRegistry
    connection_factory: DatabaseConnectionFactory
    publication_preparer: BackendPublicationPreparer
    evidence_capture_coordinator: EvidenceCaptureCoordinator


MonitoringPipelineFactory = Callable[[RuntimeContext], MonitoringPipeline]


def _validate_monitoring_assets(
    settings: Settings,
    zones: ZoneRegistry,
) -> None:
    """운영 camera·model asset을 장치 객체 생성 전에 검증한다."""

    if not settings.calibration_path.is_file():
        raise ValueError(
            "calibration_path가 실제 calibration 파일이 아닙니다: "
            f"{settings.calibration_path}"
        )

    # K/D/image_size와 fisheye calibration JSON 계약을 기존 parser로 검증한다.
    load_calibration(str(settings.calibration_path))

    calibration_sha = calibration_fingerprint(
        settings.calibration_path,
        settings.remap_balance,
    )["calibrationSha256"]
    if calibration_sha != zones.calibration_reference:
        raise ValueError(
            "calibration 파일 SHA가 ZoneRegistry.calibration_reference와 "
            "일치하지 않습니다: "
            f"calibrationSha256={calibration_sha}, "
            f"calibrationReference={zones.calibration_reference}"
        )

    if not settings.vehicle_model_path.is_file():
        raise ValueError(
            "vehicle_model_path가 실제 vehicle model 파일이 아닙니다: "
            f"{settings.vehicle_model_path}"
        )


def _build_monitoring_policy(settings: Settings) -> MonitoringPolicy:
    """Settings의 monitoring 정책을 해석 없이 domain factory로 전달한다."""

    return MonitoringPolicy(
        zone_entry_confirm_seconds=settings.zone_entry_confirm_seconds,
        zone_exit_confirm_seconds=settings.zone_exit_confirm_seconds,
        entry_zone_min_overlap_ratio=(
            settings.entry_zone_min_overlap_ratio
        ),
        parking_confirm_seconds=settings.parking_confirm_seconds,
        parking_move_confirm_seconds=(
            settings.parking_move_confirm_seconds
        ),
        absence_confirmation_seconds=(
            settings.absence_confirmation_seconds
        ),
        trusted_sample_max_gap_seconds=(
            settings.trusted_sample_max_gap_seconds
        ),
        reidentification_max_gap_seconds=(
            settings.reidentification_max_gap_seconds
        ),
        reidentification_min_score=settings.reidentification_min_score,
        reidentification_ambiguity_margin=(
            settings.reidentification_ambiguity_margin
        ),
        incident_confirm_seconds=settings.incident_confirm_seconds,
        incident_clear_seconds=settings.incident_clear_seconds,
        zone_presence_min_overlap_ratio=(
            settings.zone_presence_min_overlap_ratio
        ),
        assignment_min_overlap_ratio=(
            settings.assignment_min_overlap_ratio
        ),
        assignment_ambiguous_margin=(
            settings.assignment_ambiguous_margin
        ),
        bad_parking_min_primary_overlap_ratio=(
            settings.bad_parking_min_primary_overlap_ratio
        ),
        bad_parking_min_secondary_overlap_ratio=(
            settings.bad_parking_min_secondary_overlap_ratio
        ),
        out_of_zone_min_spot_overlap_ratio=(
            settings.out_of_zone_min_spot_overlap_ratio
        ),
        blocking_relation_confirm_seconds=(
            settings.blocking_relation_confirm_seconds
        ),
        blocking_relation_clear_seconds=(
            settings.blocking_relation_clear_seconds
        ),
        motion_window_seconds=settings.motion_window_seconds,
        motion_min_observation_span_seconds=(
            settings.motion_min_observation_span_seconds
        ),
        motion_max_sample_gap_seconds=(
            settings.motion_max_sample_gap_seconds
        ),
        motion_stationary_threshold=(
            settings.motion_stationary_threshold
        ),
        motion_moving_threshold=settings.motion_moving_threshold,
        motion_min_samples=settings.motion_min_samples,
        motion_min_trend_consistency=(
            settings.motion_min_trend_consistency
        ),
    )


def build_runtime_monitoring_pipeline(
    context: RuntimeContext,
) -> MonitoringPipeline:
    """운영 Settings와 RuntimeContext로 camera·tracking pipeline을 조립한다."""

    settings = context.settings
    _validate_monitoring_assets(settings, context.zones)

    webcam = OpenCvWebcamFrameSource(
        camera_id=settings.camera_id,
        camera_index=settings.camera_index,
        width=settings.camera_width,
        height=settings.camera_height,
    )
    frame_source = RemapFrameSource(
        inner=webcam,
        calibration_path=str(settings.calibration_path),
        balance=settings.remap_balance,
    )

    tracker = UltralyticsVehicleTracker(
        model_path=str(settings.vehicle_model_path),
        tracker_config=settings.vehicle_tracker_config,
        confidence=settings.vehicle_tracking_confidence,
    )
    left_ratio, right_ratio = compute_mask_ratios_from_zones(
        context.zones.all(),
        margin_ratio=settings.mask_margin_ratio,
    )
    detector = SideMaskingDetector(
        inner=tracker,
        left_mask_end_ratio=left_ratio,
        right_mask_start_ratio=right_ratio,
    )

    dependencies = MonitoringDependencies(
        camera_id=settings.camera_id,
        frame_source=frame_source,
        detector=detector,
        publication_preparer=context.publication_preparer,
        connection_factory=context.connection_factory,
        evidence_capture_sink=context.evidence_capture_coordinator,
    )
    return build_monitoring_pipeline(
        zones=context.zones,
        policy=_build_monitoring_policy(settings),
        dependencies=dependencies,
    )


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def create_app(
    *,
    settings: Settings | None = None,
    monitoring_pipeline_factory: MonitoringPipelineFactory | None = None,
) -> FastAPI:
    """FastAPI app을 만들고 process-local 자원 생명주기를 소유한다.

    module-level app은 운영 concrete factory를 전달해 camera·tracking
    monitoring을 함께 기동한다. 직접 호출하는 API-only 테스트는 factory를
    생략하거나 별도 test double을 주입할 수 있다.
    """

    resolved_settings = settings or get_settings()

    def connection_factory() -> sqlite3.Connection:
        # FastAPI sync handler와 monitoring thread가 SQLite connection을
        # 공유하지 않도록 호출마다 새로 연다.
        return connect_database(resolved_settings.database_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Migration 후 application을 조립하고 종료 시 worker를 회수한다."""

        _prepare_database_path(resolved_settings.database_path)
        connection = open_database(resolved_settings.database_path)
        connection.close()
        zones = ZoneRegistry.from_file(
            resolved_settings.zone_definition_path
        )
        entry_match_coordinator = EntryMatchCoordinator(zones=zones)
        application.state.zone_registry = zones
        application.state.entry_match_coordinator = entry_match_coordinator
        application.state.entry_event_intake = EntryEventIntake(
            entry_match_coordinator,
            match_window_seconds=(
                resolved_settings.entry_match_window_seconds
            ),
        )
        application.state.entry_review_resolution_intake = (
            EntryReviewResolutionIntake(entry_match_coordinator)
        )
        application.state.session_context_update_intake = (
            SessionContextUpdateIntake(ContextBindingCoordinator())
        )
        application.state.move_verification_intake = MoveVerificationIntake()
        application.state.database_connection_factory = connection_factory
        publication_preparer = BackendPublicationPreparer()
        application.state.publication_preparer = publication_preparer
        evidence_capture_coordinator = EvidenceCaptureCoordinator(
            connection_factory=connection_factory,
            zones=zones,
            spool_path=resolved_settings.evidence_spool_path,
            spool_cap_bytes=resolved_settings.evidence_spool_cap_bytes,
            filesystem_floor_ratio=(
                resolved_settings.evidence_filesystem_floor_ratio
            ),
            capture_stop_free_ratio=(
                resolved_settings.evidence_capture_stop_free_ratio
            ),
        )
        application.state.evidence_capture_coordinator = (
            evidence_capture_coordinator
        )

        monitoring_worker: MonitoringWorker | None = None
        if monitoring_pipeline_factory is not None:
            pipeline = monitoring_pipeline_factory(
                RuntimeContext(
                    settings=resolved_settings,
                    zones=zones,
                    connection_factory=connection_factory,
                    publication_preparer=publication_preparer,
                    evidence_capture_coordinator=(
                        evidence_capture_coordinator
                    ),
                )
            )
            if (
                isinstance(pipeline, MonitoringPipeline)
                and not pipeline.has_evidence_capture_sink
            ):
                pipeline.bind_evidence_capture_sink(
                    evidence_capture_coordinator
                )
            monitoring_worker = MonitoringWorker(pipeline)
        application.state.monitoring_worker = monitoring_worker

        move_verification_worker = MoveVerificationExecutorWorker(
            MoveVerificationExecutor(
                connection_factory=connection_factory,
                publication_preparer=publication_preparer,
            )
        )
        application.state.move_verification_worker = move_verification_worker

        evidence_publication_worker: EvidencePublicationWorker | None = None
        outbox_publisher_worker: OutboxPublisherWorker | None = None
        if resolved_settings.backend_hw_api_key.strip():
            evidence_publication_worker = EvidencePublicationWorker(
                EvidencePublicationPublisher(
                    connection_factory=connection_factory,
                    client=BackendClient(
                        base_url=resolved_settings.backend_base_url,
                        hw_api_key=resolved_settings.backend_hw_api_key,
                    ),
                    spool_path=resolved_settings.evidence_spool_path,
                    spool_cap_bytes=(
                        resolved_settings.evidence_spool_cap_bytes
                    ),
                    filesystem_floor_ratio=(
                        resolved_settings.evidence_filesystem_floor_ratio
                    ),
                    capture_stop_free_ratio=(
                        resolved_settings.evidence_capture_stop_free_ratio
                    ),
                )
            )
            outbox_publisher_worker = OutboxPublisherWorker(
                OutboxPublisher(
                    connection_factory=connection_factory,
                    client=BackendClient(
                        base_url=resolved_settings.backend_base_url,
                        hw_api_key=resolved_settings.backend_hw_api_key,
                    ),
                )
            )
        application.state.evidence_publication_worker = (
            evidence_publication_worker
        )
        application.state.outbox_publisher_worker = outbox_publisher_worker
        try:
            # MonitoringPipeline.open()이 durable recovery를 끝낸 뒤 기존·신규
            # publication을 보내기 시작한다.
            if evidence_publication_worker is not None:
                evidence_publication_worker.start()
            else:
                # Backend key가 없어 publisher를 끈 현장도 interrupted local
                # JPEG를 다음 capture 전 일관된 FAILED/READY 상태로 만든다.
                evidence_capture_coordinator.recover()
            if monitoring_worker is not None:
                monitoring_worker.start()
            move_verification_worker.start()
            if outbox_publisher_worker is not None:
                outbox_publisher_worker.start()
            yield
        finally:
            move_verification_worker.stop()
            if evidence_publication_worker is not None:
                evidence_publication_worker.stop()
            if outbox_publisher_worker is not None:
                outbox_publisher_worker.stop()
            if monitoring_worker is not None:
                monitoring_worker.stop()

    application = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        description="Smart Parking Jetson hardware interface",
        lifespan=lifespan,
    )
    register_error_handlers(application)

    application.include_router(health_router)
    application.include_router(entry_events_router)
    application.include_router(internal_commands_router)

    return application


def _create_runtime_app() -> FastAPI:
    """운영 camera·tracking factory가 결속된 ASGI app을 생성한다."""

    return create_app(
        monitoring_pipeline_factory=build_runtime_monitoring_pipeline,
    )


def _prepare_database_path(database_path: Path) -> None:
    """File DB의 부모 디렉터리만 기동 시 준비한다."""

    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)


configure_logging()
app = _create_runtime_app()
