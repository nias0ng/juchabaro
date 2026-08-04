"""TrackingPipeline의 관측·segment 종료·물리 부재 분리 계약."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.camera.models import CapturedFrame
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.tracking.models import (
    BoundingBox,
    DetectionObservation,
    MotionSignal,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
    TrackerFrameResult,
    TrackObservation,
)
from src.tracking.motion_estimator import MotionEstimator
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import ModelInfo, TrackingError


BASE_TIME = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BBOX = BoundingBox(0.1, 0.1, 0.2, 0.2)


class FakeDetector:
    """Frame ID별로 준비한 tracker 결과를 반환한다."""

    def __init__(self) -> None:
        self.results_by_frame_id: dict[int, TrackerFrameResult] = {}
        self.error_frame_ids: set[int] = set()
        self.opened = False
        self.closed = False

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(
            library="fake",
            library_version="0",
            model_name="fake.pt",
            tracker_config="fake.yaml",
        )

    def open(self) -> None:
        self.opened = True

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        if frame.frame_id in self.error_frame_ids:
            raise TrackingError("scripted inference failure")
        return self.results_by_frame_id.get(frame.frame_id, _result())

    def close(self) -> None:
        self.closed = True


class RestartAwareSingleVehicleResolver:
    """재시작 후보 한 대를 다음 segment에 재연결하는 테스트 resolver."""

    def __init__(self) -> None:
        self.restored_vehicles: tuple[PhysicalVehicle, ...] = ()
        self._physical_vehicle_id: PhysicalVehicleId | None = None

    def restore_active_physical_vehicles(
        self,
        vehicles: tuple[PhysicalVehicle, ...],
    ) -> None:
        if len(vehicles) != 1:
            raise ValueError("test resolver expects exactly one vehicle")
        self.restored_vehicles = vehicles
        self._physical_vehicle_id = vehicles[0].physical_vehicle_id

    def resolve(self, _observation: TrackObservation) -> PhysicalVehicleId:
        if self._physical_vehicle_id is None:
            raise RuntimeError("restart candidates were not restored")
        return self._physical_vehicle_id

    def end_track_segments(self, _ended_track_segment_ids) -> None:
        return None

    def forget_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> None:
        if self._physical_vehicle_id == physical_vehicle_id:
            self._physical_vehicle_id = None

    def reset_track_segments(self) -> None:
        return None


class SpyMotionEstimator(MotionEstimator):
    """PhysicalVehicle 정리 요청만 기록하는 motion estimator."""

    def __init__(self) -> None:
        super().__init__()
        self.forget_calls = []

    def forget(self, physical_vehicle_id) -> None:
        self.forget_calls.append(physical_vehicle_id)
        super().forget(physical_vehicle_id)


class _FullAreaTestTrackingPipeline(TrackingPipeline):
    """테스트가 전체 영역 frame을 명시적으로 인증하는 편의 wrapper."""

    def process(self, frame, *, full_area_observed: bool = True):
        return super().process(
            frame,
            full_area_observed=full_area_observed,
        )


def _make_frame(frame_id: int, *, seconds: float = 0) -> CapturedFrame:
    return CapturedFrame(
        camera_id="cam-1",
        frame_id=frame_id,
        captured_at=BASE_TIME + timedelta(seconds=seconds),
        image=object(),
        width=640,
        height=480,
        calibration_id=None,
    )


def _observation(track_segment_id: int, *, seconds: float = 0, bbox: BoundingBox = BBOX) -> TrackObservation:
    return TrackObservation(
        track_segment_id=track_segment_id,
        bbox=bbox,
        confidence=0.9,
        observed_at=BASE_TIME + timedelta(seconds=seconds),
    )


def _result(
    *observations: TrackObservation,
    ended_track_segment_ids=(),
    all_detections_tracked: bool = True,
    detection_count: int | None = None,
    detections: tuple[DetectionObservation, ...] = (),
) -> TrackerFrameResult:
    return TrackerFrameResult(
        observations=observations,
        all_detections_tracked=all_detections_tracked,
        ended_track_segment_ids=ended_track_segment_ids,
        detection_count=detection_count,
        detections=detections,
    )


def _pipeline(
    detector: FakeDetector,
    *,
    absence_seconds: float = 2.0,
    entity_resolver=None,
) -> TrackingPipeline:
    return _FullAreaTestTrackingPipeline(
        camera_id="cam-1",
        detector=detector,
        absence_confirmation_seconds=absence_seconds,
        trusted_sample_max_gap_seconds=1.0,
        entity_resolver=entity_resolver,
    )


def test_open_and_close_delegate_to_detector():
    detector = FakeDetector()
    pipeline = _pipeline(detector)

    pipeline.open()
    pipeline.close()

    assert detector.opened
    assert detector.closed


def test_caller_certified_frame_is_a_healthy_full_area_observation():
    detector = FakeDetector()

    batch = _pipeline(detector).process(_make_frame(7))

    assert batch.camera_id == "cam-1"
    assert batch.frame_id == 7
    assert batch.observed_at == BASE_TIME
    assert batch.observation.state is ObservationState.OBSERVED
    assert batch.full_area_observed is True
    assert batch.all_detections_tracked is True


def test_pretrack_detection_diagnostics_are_propagated_without_identity():
    detector = FakeDetector()
    detection = DetectionObservation(
        bbox=BBOX,
        confidence=0.27,
        class_id=0,
    )
    detector.results_by_frame_id[7] = _result(
        detection_count=1,
        detections=(detection,),
        all_detections_tracked=False,
    )

    batch = _pipeline(detector).process(_make_frame(7))

    assert batch.detection_count == 1
    assert batch.detections == (detection,)
    assert batch.vehicles == ()
    assert batch.all_detections_tracked is False


def test_full_area_certification_is_a_required_keyword():
    detector = FakeDetector()
    pipeline = TrackingPipeline(
        camera_id="cam-1",
        detector=detector,
        absence_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
    )

    with pytest.raises(TypeError, match="full_area_observed"):
        pipeline.process(_make_frame(7))

    batch = pipeline.process(_make_frame(7), full_area_observed=False)

    assert batch.observation.state is ObservationState.DEGRADED
    assert batch.full_area_observed is False


def test_wrong_camera_frame_is_rejected_and_breaks_absence_continuity():
    detector = FakeDetector()
    pipeline = _pipeline(detector)
    wrong_camera_frame = replace(_make_frame(1), camera_id="cam-2")

    with pytest.raises(TrackingError, match="camera_id"):
        pipeline.process(wrong_camera_frame)


def test_new_vehicle_snapshot_has_no_session_context_and_starts_moving():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))

    batch = _pipeline(detector).process(_make_frame(1))

    snapshot = batch.vehicles[0]
    assert isinstance(snapshot.physical_vehicle_id, UUID)
    assert not hasattr(snapshot, "context")
    assert snapshot.motion_signal is MotionSignal.MOVING


def test_same_segment_with_same_bbox_becomes_stationary():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[2] = _result(_observation(1, seconds=1))
    pipeline = _pipeline(detector)

    pipeline.process(_make_frame(1))
    second = pipeline.process(_make_frame(2, seconds=1))

    assert second.vehicles[0].motion_signal is MotionSignal.STATIONARY


def test_one_frame_miss_is_unobserved_not_segment_end_or_not_present():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector)

    first = pipeline.process(_make_frame(1))
    second = pipeline.process(_make_frame(2, seconds=1))

    vehicle_id = first.vehicles[0].physical_vehicle_id
    assert second.vehicles == ()
    assert second.ended_track_segment_ids == ()
    assert second.unobserved_physical_vehicle_ids == (vehicle_id,)
    assert second.absence_progress[0].physical_vehicle_id == vehicle_id
    assert second.absence_progress[0].trusted_seconds == 0.0
    assert second.not_present_confirmed_vehicle_ids == ()


def test_same_segment_reappearing_after_temporary_miss_keeps_physical_identity():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[3] = _result(_observation(1, seconds=2))
    pipeline = _pipeline(detector)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    third = pipeline.process(_make_frame(3, seconds=2))

    assert third.vehicles[0].physical_vehicle_id == first.vehicles[0].physical_vehicle_id
    assert third.vehicles[0].motion_signal is MotionSignal.STATIONARY
    assert third.unobserved_physical_vehicle_ids == ()


def test_adapter_confirmed_segment_end_only_detaches_segment():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[2] = _result(
        ended_track_segment_ids=(1,),
    )
    pipeline = _pipeline(detector)

    first = pipeline.process(_make_frame(1))
    ended = pipeline.process(_make_frame(2, seconds=1))

    assert ended.ended_track_segment_ids == (1,)
    assert ended.unobserved_physical_vehicle_ids == (first.vehicles[0].physical_vehicle_id,)
    assert ended.not_present_confirmed_vehicle_ids == ()


def test_unrelated_new_segment_does_not_freeze_previous_vehicle_absence():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[2] = _result(
        _observation(2, seconds=1),
        ended_track_segment_ids=(1,),
    )
    detector.results_by_frame_id[3] = _result(_observation(2, seconds=2))
    detector.results_by_frame_id[4] = _result(_observation(2, seconds=3))
    pipeline = _pipeline(detector, absence_seconds=2.0)

    first = pipeline.process(_make_frame(1))
    replacement = pipeline.process(_make_frame(2, seconds=1))
    pipeline.process(_make_frame(3, seconds=2))
    confirmed = pipeline.process(_make_frame(4, seconds=3))

    previous_vehicle_id = first.vehicles[0].physical_vehicle_id
    assert replacement.vehicles[0].physical_vehicle_id != previous_vehicle_id
    assert previous_vehicle_id in confirmed.unobserved_physical_vehicle_ids
    assert confirmed.not_present_confirmed_vehicle_ids == (previous_vehicle_id,)


def test_untracked_detection_freezes_absence_for_only_that_frame():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[2] = _result(all_detections_tracked=False)
    pipeline = _pipeline(detector, absence_seconds=2.0)

    first = pipeline.process(_make_frame(1))
    unresolved = pipeline.process(_make_frame(2, seconds=1))
    pipeline.process(_make_frame(3, seconds=2))
    not_yet_confirmed = pipeline.process(_make_frame(4, seconds=3))
    confirmed = pipeline.process(_make_frame(5, seconds=4))

    vehicle_id = first.vehicles[0].physical_vehicle_id
    assert unresolved.unobserved_physical_vehicle_ids == (vehicle_id,)
    assert unresolved.all_detections_tracked is False
    assert unresolved.not_present_confirmed_vehicle_ids == ()
    assert not_yet_confirmed.not_present_confirmed_vehicle_ids == ()
    assert confirmed.not_present_confirmed_vehicle_ids == (vehicle_id,)


def test_segment_end_does_not_forget_physical_vehicle_motion_anchor():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[2] = _result(
        ended_track_segment_ids=(1,),
    )
    motion_estimator = SpyMotionEstimator()
    pipeline = TrackingPipeline(
        camera_id="cam-1",
        detector=detector,
        absence_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
        motion_estimator=motion_estimator,
    )

    pipeline.process(_make_frame(1), full_area_observed=True)
    pipeline.process(_make_frame(2, seconds=1), full_area_observed=True)

    assert motion_estimator.forget_calls == []


def test_healthy_full_area_absence_reaches_confirmation_threshold():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector, absence_seconds=2.0)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))  # first negative sample: 0 seconds
    pipeline.process(_make_frame(3, seconds=2))  # 1 trusted second
    confirmed = pipeline.process(_make_frame(4, seconds=3))  # 2 trusted seconds

    assert confirmed.not_present_confirmed_vehicle_ids == (first.vehicles[0].physical_vehicle_id,)


def test_partial_frame_degrades_snapshots_and_freezes_absence_timer():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[4] = _result(_observation(2, seconds=20))
    pipeline = _pipeline(detector, absence_seconds=2.0)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    degraded = pipeline.process(_make_frame(3, seconds=10), full_area_observed=False)
    observed_in_partial = pipeline.process(_make_frame(4, seconds=20), full_area_observed=False)
    recovered = pipeline.process(_make_frame(5, seconds=30))

    assert degraded.observation.state is ObservationState.DEGRADED
    assert degraded.observation.reason is ObservationReason.PARTIAL_FRAME
    assert degraded.full_area_observed is False
    assert observed_in_partial.vehicles[0].observation.state is ObservationState.DEGRADED
    assert observed_in_partial.vehicles[0].motion_signal is MotionSignal.UNKNOWN
    assert first.vehicles[0].physical_vehicle_id not in recovered.not_present_confirmed_vehicle_ids


def test_confirmed_absence_repeats_in_degraded_batch_until_ack():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector, absence_seconds=1.0)

    pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    confirmed = pipeline.process(_make_frame(3, seconds=2))
    degraded = pipeline.process(_make_frame(4, seconds=3), full_area_observed=False)
    recovered = pipeline.process(_make_frame(5, seconds=4))

    assert confirmed.not_present_confirmed_vehicle_ids
    assert degraded.not_present_confirmed_vehicle_ids == (
        confirmed.not_present_confirmed_vehicle_ids
    )
    assert recovered.not_present_confirmed_vehicle_ids == confirmed.not_present_confirmed_vehicle_ids


def test_explicit_pause_prevents_camera_downtime_from_being_counted():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector, absence_seconds=2.0)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    pipeline.process(_make_frame(3, seconds=2))
    pipeline.pause_absence_confirmation()
    recovered = pipeline.process(_make_frame(4, seconds=100))

    assert first.vehicles[0].physical_vehicle_id in recovered.unobserved_physical_vehicle_ids
    assert recovered.not_present_confirmed_vehicle_ids == ()


def test_long_frame_gap_is_not_backfilled_as_trusted_absence():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector, absence_seconds=2.0)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    after_stall = pipeline.process(_make_frame(3, seconds=100))
    next_sample = pipeline.process(_make_frame(4, seconds=101))

    vehicle_id = first.vehicles[0].physical_vehicle_id
    assert vehicle_id in after_stall.unobserved_physical_vehicle_ids
    assert after_stall.not_present_confirmed_vehicle_ids == ()
    assert next_sample.not_present_confirmed_vehicle_ids == ()


def test_inference_error_automatically_breaks_absence_time_continuity():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.error_frame_ids.add(4)
    pipeline = _pipeline(detector, absence_seconds=2.0)

    pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    pipeline.process(_make_frame(3, seconds=2))
    with pytest.raises(TrackingError):
        pipeline.process(_make_frame(4, seconds=50))
    recovered = pipeline.process(_make_frame(5, seconds=100))

    assert recovered.not_present_confirmed_vehicle_ids == ()


def test_camera_interruption_becomes_untrusted_batch_without_absence_gain():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector, absence_seconds=2.0)
    first = pipeline.process(_make_frame(1))
    vehicle_id = first.vehicles[0].physical_vehicle_id

    interrupted = pipeline.interrupt_observation(
        observed_at=BASE_TIME + timedelta(seconds=100),
        observation=ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.CAMERA_UNAVAILABLE,
        ),
    )

    assert interrupted.frame_id == 1
    assert interrupted.vehicles == ()
    assert interrupted.unobserved_physical_vehicle_ids == (vehicle_id,)
    assert interrupted.absence_progress[0].trusted_seconds == 0.0
    assert interrupted.not_present_confirmed_vehicle_ids == ()
    assert interrupted.observation.state is ObservationState.UNKNOWN
    assert (
        interrupted.observation.reason
        is ObservationReason.CAMERA_UNAVAILABLE
    )


def test_restore_absence_checkpoint_continues_from_durable_lower_bound():
    detector = FakeDetector()
    pipeline = _pipeline(detector, absence_seconds=2.0)
    vehicle_id = PhysicalVehicleId(UUID(int=500))
    pipeline.restore_absence_checkpoint(
        vehicle_id,
        trusted_seconds=1.0,
        absence_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
        confirmed_at=None,
    )

    after_restart = pipeline.process(_make_frame(1, seconds=100))
    confirmed = pipeline.process(_make_frame(2, seconds=101))

    assert after_restart.absence_progress[0].trusted_seconds == 1.0
    assert after_restart.not_present_confirmed_vehicle_ids == ()
    assert confirmed.absence_progress[0].trusted_seconds == 2.0
    assert confirmed.not_present_confirmed_vehicle_ids == (vehicle_id,)


def test_restart_with_visible_detection_pauses_identity_and_absence_until_empty():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(
        _observation(1, seconds=100)
    )
    detector.results_by_frame_id[5] = _result(
        _observation(1, seconds=104)
    )
    pipeline = _pipeline(detector, absence_seconds=2.0)
    vehicle_id = PhysicalVehicleId(UUID(int=700))
    pipeline.restore_active_checkpoints(
        (
            PhysicalVehicle(
                physical_vehicle_id=vehicle_id,
                state=PhysicalVehicleState.ACTIVE,
                observation=ObservationStatus(
                    state=ObservationState.UNKNOWN,
                    reason=ObservationReason.PROCESS_RESTARTED,
                    last_reliable_observed_at=BASE_TIME,
                ),
                absence_trusted_seconds=0.0,
                absence_confirmation_seconds=2.0,
                trusted_sample_max_gap_seconds=1.0,
                record_version=2,
                created_at=BASE_TIME,
                updated_at=BASE_TIME,
            ),
        )
    )

    uncertain = pipeline.process(_make_frame(1, seconds=100))
    first_empty = pipeline.process(_make_frame(2, seconds=101))
    pipeline.process(_make_frame(3, seconds=102))
    confirmed = pipeline.process(_make_frame(4, seconds=103))

    assert uncertain.vehicles == ()
    assert uncertain.observation.state is ObservationState.UNKNOWN
    assert (
        uncertain.observation.reason
        is ObservationReason.REIDENTIFICATION_UNCERTAIN
    )
    assert uncertain.all_detections_tracked is False
    assert uncertain.absence_progress[0].trusted_seconds == 0.0
    assert first_empty.not_present_confirmed_vehicle_ids == ()
    assert confirmed.not_present_confirmed_vehicle_ids == (vehicle_id,)

    pipeline.forget_physical_vehicle(vehicle_id)
    after_ack = pipeline.process(_make_frame(5, seconds=104))
    assert len(after_ack.vehicles) == 1
    assert after_ack.vehicles[0].physical_vehicle_id != vehicle_id


def test_restart_aware_resolver_reuses_durable_identity_without_empty_wait():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(
        _observation(1, seconds=100)
    )
    resolver = RestartAwareSingleVehicleResolver()
    pipeline = _pipeline(detector, entity_resolver=resolver)
    vehicle = PhysicalVehicle(
        physical_vehicle_id=PhysicalVehicleId(UUID(int=701)),
        state=PhysicalVehicleState.ACTIVE,
        observation=ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.PROCESS_RESTARTED,
            last_reliable_observed_at=BASE_TIME,
        ),
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=2,
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )

    pipeline.restore_active_checkpoints((vehicle,))
    recovered = pipeline.process(_make_frame(1, seconds=100))

    assert resolver.restored_vehicles == (vehicle,)
    assert [snapshot.physical_vehicle_id for snapshot in recovered.vehicles] == [
        vehicle.physical_vehicle_id
    ]
    assert recovered.observation.state is ObservationState.OBSERVED
    assert recovered.all_detections_tracked is True
    assert recovered.unobserved_physical_vehicle_ids == ()


def test_restore_uses_vehicle_policy_snapshot_instead_of_current_default():
    detector = FakeDetector()
    pipeline = _pipeline(detector, absence_seconds=1.0)
    vehicle_id = PhysicalVehicleId(UUID(int=501))
    pipeline.restore_absence_checkpoint(
        vehicle_id,
        trusted_seconds=1.0,
        absence_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
        confirmed_at=None,
    )

    first = pipeline.process(_make_frame(1, seconds=100))
    second = pipeline.process(_make_frame(2, seconds=101))
    third = pipeline.process(_make_frame(3, seconds=102))

    assert first.not_present_confirmed_vehicle_ids == ()
    assert second.not_present_confirmed_vehicle_ids == (vehicle_id,)
    assert third.not_present_confirmed_vehicle_ids == (vehicle_id,)


def test_forget_physical_vehicle_acknowledges_confirmed_absence():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    pipeline = _pipeline(detector, absence_seconds=1.0)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    confirmed = pipeline.process(_make_frame(3, seconds=2))
    vehicle_id = first.vehicles[0].physical_vehicle_id
    pipeline.forget_physical_vehicle(vehicle_id)
    after_ack = pipeline.process(_make_frame(4, seconds=3))

    assert confirmed.not_present_confirmed_vehicle_ids == (vehicle_id,)
    assert after_ack.unobserved_physical_vehicle_ids == ()
    assert after_ack.not_present_confirmed_vehicle_ids == ()


def test_forget_physical_vehicle_prevents_terminal_identity_resurrection():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[4] = _result(_observation(1, seconds=3))
    pipeline = _pipeline(detector, absence_seconds=1.0)

    first = pipeline.process(_make_frame(1))
    pipeline.process(_make_frame(2, seconds=1))
    confirmed = pipeline.process(_make_frame(3, seconds=2))
    terminal_id = first.vehicles[0].physical_vehicle_id
    assert confirmed.not_present_confirmed_vehicle_ids == (terminal_id,)

    pipeline.forget_physical_vehicle(terminal_id)
    reappeared = pipeline.process(_make_frame(4, seconds=3))

    assert reappeared.vehicles[0].physical_vehicle_id != terminal_id


def test_close_resets_numeric_track_segment_generation():
    detector = FakeDetector()
    detector.results_by_frame_id[1] = _result(_observation(1))
    detector.results_by_frame_id[2] = _result(_observation(1, seconds=1))
    pipeline = _pipeline(detector)

    first = pipeline.process(_make_frame(1))
    pipeline.close()
    pipeline.open()
    reopened = pipeline.process(_make_frame(2, seconds=1))

    assert reopened.vehicles[0].physical_vehicle_id != (
        first.vehicles[0].physical_vehicle_id
    )
