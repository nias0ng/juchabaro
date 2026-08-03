"""live_overlay_renderer의 픽셀 단위 그리기·인코딩 회귀 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import cv2
import numpy as np

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.models import CapturedFrame
from src.domain.models import ObservationState, ObservationStatus
from src.live.live_overlay_renderer import draw_overlay, encode_jpeg, render_overlay_jpeg
from src.parking.models import (
    AssignmentState,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingPipelineResult,
    ParkingState,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    TrackingBatch,
)

NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
CALIBRATION_ID = "calib-1"
VEHICLE_ID = PhysicalVehicleId(UUID("10000000-0000-4000-8000-000000000001"))

OBSERVED = ObservationStatus(state=ObservationState.OBSERVED, last_reliable_observed_at=NOW)

GENERAL_ZONE_COLOR = (0, 200, 0)
NEUTRAL_COLOR = (160, 160, 160)
INSIDE_COLOR = (0, 255, 0)
PARKED_COLOR = (0, 0, 255)


def _frame(size: int = 100) -> CapturedFrame:
    return CapturedFrame(
        camera_id="cam-1",
        frame_id=1,
        captured_at=NOW,
        image=np.zeros((size, size, 3), dtype=np.uint8),
        width=size,
        height=size,
        calibration_id=CALIBRATION_ID,
    )


def _zone_registry(zone_type: ZoneType = ZoneType.GENERAL) -> ZoneRegistry:
    return ZoneRegistry(
        [
            ZoneDefinition(
                zone_id=ZoneId(1),
                zone_type=zone_type,
                polygon=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
                zone_definition_version=ZoneDefinitionVersion(1),
                calibration_reference=CALIBRATION_ID,
            )
        ]
    )


def _vehicle(bbox: BoundingBox) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=VEHICLE_ID,
        track_segment_id=TrackSegmentId(1),
        bbox=bbox,
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=NOW,
        camera_id="cam-1",
        observation=OBSERVED,
    )


def _tracking_batch(vehicles: tuple[PhysicalVehicleSnapshot, ...]) -> TrackingBatch:
    return TrackingBatch(
        camera_id="cam-1",
        frame_id=1,
        observed_at=NOW,
        vehicles=vehicles,
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(),
        absence_progress=(),
        observation=OBSERVED,
        full_area_observed=True,
        all_detections_tracked=True,
    )


def _result(
    *,
    zone_visits: tuple[ZoneVisit, ...] = (),
    episodes: tuple[ParkingEpisode, ...] = (),
) -> FrameObservationResult:
    return FrameObservationResult(
        parking_result=ParkingPipelineResult(
            zone_visit_updates=zone_visits,
            parking_episode_updates=episodes,
            incident_transitions=(),
        ),
        retired_physical_vehicle_ids=(),
    )


def _row_has_color(canvas: np.ndarray, y: int, color: tuple[int, int, int]) -> bool:
    return any(tuple(int(c) for c in canvas[y, x]) == color for x in range(canvas.shape[1]))


def test_draw_overlay_paints_zone_polygon_with_type_color() -> None:
    canvas = draw_overlay(
        _frame(), _tracking_batch(()), _result(), zones=_zone_registry(ZoneType.GENERAL)
    )

    assert _row_has_color(canvas, 10, GENERAL_ZONE_COLOR)


def test_draw_overlay_paints_vehicle_bbox_neutral_when_no_zone_visit_or_episode() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    canvas = draw_overlay(
        _frame(), _tracking_batch((vehicle,)), _result(), zones=_zone_registry()
    )

    assert _row_has_color(canvas, 20, NEUTRAL_COLOR)


def _zone_visit(state: ZoneVisitState, *, zone_id: int = 1) -> ZoneVisit:
    entered_at = NOW if state in {ZoneVisitState.INSIDE, ZoneVisitState.EXITING, ZoneVisitState.ENDED} else None
    entered_candidate_at = NOW if state is ZoneVisitState.ENTERING else entered_at
    exit_candidate_at = NOW if state is ZoneVisitState.EXITING else None
    ended_at = NOW if state in {ZoneVisitState.ENDED, ZoneVisitState.CANCELED} else None
    termination_reason = "test" if ended_at is not None else None
    return ZoneVisit(
        visit_id=ZoneVisitId(UUID("20000000-0000-4000-8000-000000000001")),
        physical_vehicle_id=VEHICLE_ID,
        zone_id=ZoneId(zone_id),
        zone_definition_version=ZoneDefinitionVersion(1),
        state=state,
        observation=OBSERVED,
        entry_trusted_seconds=0.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
        entered_candidate_at=entered_candidate_at,
        entered_at=entered_at,
        exit_candidate_at=exit_candidate_at,
        ended_at=ended_at,
        termination_reason=termination_reason,
    )


def test_draw_overlay_paints_vehicle_bbox_with_zone_visit_color_when_inside() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(zone_visits=(_zone_visit(ZoneVisitState.INSIDE),))

    canvas = draw_overlay(_frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry())

    assert _row_has_color(canvas, 20, INSIDE_COLOR)


def test_draw_overlay_prefers_inside_zone_visit_over_entering_when_both_present() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(
        zone_visits=(
            _zone_visit(ZoneVisitState.ENTERING, zone_id=1),
            _zone_visit(ZoneVisitState.INSIDE, zone_id=2),
        )
    )

    canvas = draw_overlay(_frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry())

    assert _row_has_color(canvas, 20, INSIDE_COLOR)


def test_draw_overlay_paints_vehicle_bbox_with_ended_zone_visit_distinct_from_neutral() -> None:
    """Terminal zone visit (ENDED) must be visually distinct from having no zone visit at all."""
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(zone_visits=(_zone_visit(ZoneVisitState.ENDED),))

    canvas = draw_overlay(_frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry())

    # Terminal zone visit should render with (100, 100, 180), not NEUTRAL_COLOR (160, 160, 160)
    ended_color = (100, 100, 180)
    assert _row_has_color(canvas, 20, ended_color)
    assert not _row_has_color(canvas, 20, NEUTRAL_COLOR)


def _assignment() -> ParkingAssignment:
    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        zone_id=ZoneId(1),
        representative_footprint=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
        confidence=0.9,
        last_stable_at=NOW,
    )


def _episode(state: ParkingState) -> ParkingEpisode:
    parked_at = NOW if state in {ParkingState.PARKED, ParkingState.MOVE_PENDING, ParkingState.ENDED} else None
    assignment = _assignment() if parked_at is not None else None
    movement_candidate_at = NOW if state is ParkingState.MOVE_PENDING else None
    ended_at = NOW if state in {ParkingState.ENDED, ParkingState.CANCELED} else None
    termination_reason = "test" if ended_at is not None else None
    return ParkingEpisode(
        episode_id=ParkingEpisodeId(UUID("30000000-0000-4000-8000-000000000001")),
        physical_vehicle_id=VEHICLE_ID,
        state=state,
        observation=OBSERVED,
        stationary_trusted_seconds=0.0,
        movement_trusted_seconds=0.0,
        parking_confirmation_seconds=10.0,
        movement_confirmation_seconds=2.0,
        last_signal=MotionSignal.STATIONARY,
        record_version=1,
        publication_revision=0,
        created_at=NOW,
        updated_at=NOW,
        trusted_sample_max_gap_seconds=1.0,
        assignment=assignment,
        parked_at=parked_at,
        movement_candidate_at=movement_candidate_at,
        ended_at=ended_at,
        termination_reason=termination_reason,
    )


def test_draw_overlay_prefers_active_parking_episode_color_over_zone_visit() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(
        zone_visits=(_zone_visit(ZoneVisitState.INSIDE),),
        episodes=(_episode(ParkingState.PARKED),),
    )

    canvas = draw_overlay(_frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry())

    assert _row_has_color(canvas, 20, PARKED_COLOR)


def test_draw_overlay_falls_back_to_zone_visit_when_episode_is_terminal() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(
        zone_visits=(_zone_visit(ZoneVisitState.INSIDE),),
        episodes=(_episode(ParkingState.ENDED),),
    )

    canvas = draw_overlay(_frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry())

    assert _row_has_color(canvas, 20, INSIDE_COLOR)


def test_draw_overlay_falls_back_to_neutral_when_terminal_episode_has_no_zone_visit() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(episodes=(_episode(ParkingState.ENDED),))

    canvas = draw_overlay(_frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry())

    assert _row_has_color(canvas, 20, NEUTRAL_COLOR)


def _approx_row_has_color(
    canvas: np.ndarray, y: int, color: tuple[int, int, int], *, tolerance: int = 40
) -> bool:
    # JPEG는 손실 압축이라 정확히 같은 색이 나온다고 보장할 수 없다 —
    # 위의 draw_overlay 테스트들과 달리 여기서는 근사 비교를 쓴다.
    for x in range(canvas.shape[1]):
        pixel = canvas[y, x]
        if all(abs(int(pixel[c]) - color[c]) <= tolerance for c in range(3)):
            return True
    return False


def test_encode_jpeg_returns_decodable_bytes_of_same_shape() -> None:
    canvas = draw_overlay(_frame(), _tracking_batch(()), _result(), zones=_zone_registry())

    jpeg_bytes = encode_jpeg(canvas)

    assert isinstance(jpeg_bytes, bytes)
    assert len(jpeg_bytes) > 0
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == canvas.shape


def test_render_overlay_jpeg_composes_draw_and_encode() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    result = _result(zone_visits=(_zone_visit(ZoneVisitState.INSIDE),))

    jpeg_bytes = render_overlay_jpeg(
        _frame(), _tracking_batch((vehicle,)), result, zones=_zone_registry()
    )

    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert _approx_row_has_color(decoded, 20, INSIDE_COLOR)
