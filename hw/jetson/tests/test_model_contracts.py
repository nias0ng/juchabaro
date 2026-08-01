"""T-02: 데이터흐름.md가 정의했으나 코드에 없던 모델 계약 7종 + camera_id 전파 검증."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.actuators.models import ActuatorCommand
from src.camera.models import CapturedFrame
from src.communication.models import EntryContext, MoveRequestId, ParkingEventId
from src.parking.models import (
    AssignmentState,
    IncidentId,
    ParkingAssignment,
    ParkingEpisodeId,
    ParkingPipelineResult,
    ZoneId,
    ZoneVisitId,
)
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ZoneRegistry
from src.sensors.models import SensorObservation
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    TrackingBatch,
    VehicleId,
)

NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


def _make_snapshot(
    *,
    physical_vehicle_id: PhysicalVehicleId = PhysicalVehicleId(UUID(int=1)),
    camera_id: str = "cam-1",
) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=physical_vehicle_id,
        camera_id=camera_id,
        track_segment_id=1,
        bbox=BoundingBox(0.1, 0.1, 0.2, 0.2),
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=NOW,
    )


class TestCapturedFrame:
    def test_constructs_with_calibration_id(self):
        frame = CapturedFrame(
            camera_id="cam-1",
            frame_id=1,
            captured_at=NOW,
            image=object(),
            width=1280,
            height=720,
            calibration_id="calib-1",
        )
        assert frame.camera_id == "cam-1"
        assert frame.calibration_id == "calib-1"

    def test_calibration_id_can_be_none(self):
        frame = CapturedFrame(
            camera_id="cam-1", frame_id=1, captured_at=NOW, image=object(),
            width=1280, height=720, calibration_id=None,
        )
        assert frame.calibration_id is None


class TestPhysicalVehicleSnapshotCameraId:
    def test_snapshot_now_carries_camera_id(self):
        """§4.2: PhysicalVehicleSnapshot에 camera_id가 없어 추적 계층을 지나며
        유실되던 문제를 고친다."""
        snapshot = _make_snapshot(camera_id="cam-7")
        assert snapshot.camera_id == "cam-7"


class TestTrackingBatch:
    def test_batch_carries_vehicles_and_ended_ids(self):
        snapshot = _make_snapshot()
        ended_id = PhysicalVehicleId(UUID(int=2))
        batch = TrackingBatch(
            camera_id="cam-1",
            frame_id=42,
            observed_at=NOW,
            vehicles=(snapshot,),
            ended_vehicle_ids=(ended_id,),
            source_available=True,
        )
        assert batch.vehicles == (snapshot,)
        assert batch.ended_vehicle_ids == (ended_id,)

    def test_source_unavailable_distinct_from_empty_vehicles(self):
        """카메라 장애(source_available=False)와 '차량이 없다'(빈 vehicles)는
        다른 신호다(데이터흐름.md §2)."""
        batch = TrackingBatch(
            camera_id="cam-1", frame_id=1, observed_at=NOW,
            vehicles=(), ended_vehicle_ids=(), source_available=False,
        )
        assert batch.vehicles == ()
        assert batch.source_available is False


class TestParkingAssignment:
    def test_assigned_state_carries_zone_id(self):
        assignment = ParkingAssignment(
            physical_vehicle_id=PhysicalVehicleId(UUID(int=1)),
            state=AssignmentState.ASSIGNED,
            zone_id=7,
        )
        assert assignment.state == AssignmentState.ASSIGNED
        assert assignment.zone_id == 7

    def test_ambiguous_state_has_no_zone_id(self):
        assignment = ParkingAssignment(
            physical_vehicle_id=PhysicalVehicleId(UUID(int=1)),
            state=AssignmentState.AMBIGUOUS,
        )
        assert assignment.zone_id is None


class TestParkingPipelineResult:
    def test_constructs_with_all_three_update_kinds(self):
        result = ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_transitions=(),
        )
        assert result.zone_visit_updates == ()
        assert result.parking_episode_updates == ()
        assert result.incident_transitions == ()


class TestRuleContext:
    def test_constructs_with_optional_fields_none(self):
        """자격 정보·주차 에피소드·배정이 아직 없는 상태(예: 방금 진입한
        차량)도 RuleContext를 만들 수 있어야 한다."""
        context = RuleContext(
            vehicle=_make_snapshot(),
            vehicle_context=None,
            active_zone_visits=(),
            parking_episode=None,
            parking_assignment=None,
            zones=ZoneRegistry([]),
            observed_at=NOW,
        )
        assert context.vehicle_context is None
        assert context.parking_episode is None


class TestSensorObservation:
    def test_quality_defaults_to_none(self):
        observation = SensorObservation(
            sensor_id="us-1", sensor_type="ultrasonic", value=42.0, observed_at=NOW,
        )
        assert observation.quality is None


class TestActuatorCommand:
    def test_constructs_with_reason(self):
        command = ActuatorCommand(
            actuator_id="led-1", action="BLINK", reason="EV_OVERSTAY", requested_at=NOW,
        )
        assert command.action == "BLINK"
        assert command.reason == "EV_OVERSTAY"


class TestEntryContext:
    def test_matches_383_incoming_entry_event_shape(self):
        """ai/tracking/entry_event_intake.py의 IncomingEntryEvent와 필드가
        같아야 한다(383의 wire 계약)."""
        context = EntryContext(
            tracking_id="d290f1ee-6c54-4b01-90e6-d701748f0851",
            recognized_plate_number="12가3456",
            entry_time=NOW,
            access_decision="ALLOW",
            registered=True,
            vehicle_id=10,
            is_disabled_vehicle=False,
            is_electric=True,
            vehicle_status="ACTIVE",
            session_id=55,
            duplicate_request=False,
        )
        assert context.tracking_id == "d290f1ee-6c54-4b01-90e6-d701748f0851"
        assert context.recognized_plate_number == "12가3456"

    def test_deny_payload_allows_null_vehicle_fields(self):
        context = EntryContext(
            tracking_id="x", recognized_plate_number="12가3456", entry_time=NOW,
            access_decision="DENY", registered=False, vehicle_id=None,
            is_disabled_vehicle=None, is_electric=None, vehicle_status=None,
            session_id=None, duplicate_request=False,
        )
        assert context.vehicle_id is None


def test_identifier_types_keep_domain_meanings_separate():
    assert TrackSegmentId.__supertype__ is int
    assert PhysicalVehicleId.__supertype__ is UUID
    assert ParkingSessionId.__supertype__ is int
    assert VehicleId.__supertype__ is int
    assert ZoneId.__supertype__ is int
    assert ZoneVisitId.__supertype__ is UUID
    assert ParkingEpisodeId.__supertype__ is UUID
    assert IncidentId.__supertype__ is UUID
    assert ParkingEventId.__supertype__ is int
    assert MoveRequestId.__supertype__ is int
