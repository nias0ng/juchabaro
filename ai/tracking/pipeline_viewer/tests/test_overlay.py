"""Viewer overlay가 운영 좌표만 표시하고 입력 이미지를 보존하는지 확인한다."""

from uuid import UUID

import numpy as np

from pipeline_viewer.overlay import draw_frame_overlay
from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.frame_source import EPOCH
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    EntryExitRole,
    ParkingPipelineResult,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackingBatch,
    TrackSegmentId,
)


def test_overlay_draws_on_copy_without_mutating_rgb_input() -> None:
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    original = image.copy()
    vehicle_id = PhysicalVehicleId(UUID(int=1))
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=EPOCH,
    )
    batch = TrackingBatch(
        camera_id="cam-1",
        frame_id=1,
        observed_at=EPOCH,
        vehicles=(
            PhysicalVehicleSnapshot(
                physical_vehicle_id=vehicle_id,
                track_segment_id=TrackSegmentId(7),
                bbox=BoundingBox(0.2, 0.2, 0.5, 0.6),
                confidence=0.91,
                motion_signal=MotionSignal.STATIONARY,
                observed_at=EPOCH,
                camera_id="cam-1",
                observation=observation,
            ),
        ),
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(),
        absence_progress=(),
        observation=observation,
        full_area_observed=True,
        all_detections_tracked=True,
    )
    result = FrameObservationResult(
        parking_result=ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_transitions=(),
        ),
        retired_physical_vehicle_ids=(),
    )
    zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.05, 0.05), (0.8, 0.05), (0.8, 0.8), (0.05, 0.8)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration",
        entry_exit_role=EntryExitRole.ENTRY,
    )

    rendered = draw_frame_overlay(
        image,
        tracking_batch=batch,
        result=result,
        zones=(zone,),
        alias_for=lambda _: "V1",
    )

    assert np.array_equal(image, original)
    assert not np.array_equal(rendered, original)
