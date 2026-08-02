"""Tracker 관측을 PhysicalVehicle projection과 부재 신호로 변환한다.

추적 계층은 TrackSegment·PhysicalVehicle 관측만 소유한다. 입차
session 매칭과 ContextBinding은 session coordinator의 책임이며 이 pipeline에
주입하지 않는다. 한 frame의 미관측, tracker가 확정한 segment 종료,
정상 전체 관측이 일정 시간 지속된 NOT_PRESENT를 서로 다른 출력으로
보고한다.
"""

from __future__ import annotations

from datetime import datetime

from src.camera.models import CapturedFrame
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
    require_positive,
)
from src.tracking.entity_resolver import PassthroughEntityResolver
from src.tracking.models import (
    MotionSignal,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
    PhysicalVehicleSnapshot,
    TrackingBatch,
)
from src.tracking.motion_estimator import MotionEstimator
from src.tracking.presence_confirmer import PhysicalVehiclePresenceConfirmer
from src.tracking.protocols import (
    Detector,
    EntityResolver,
    RestartAwareEntityResolver,
    TrackingError,
)


class TrackingPipeline:
    """한 camera frame을 차량 관측 batch로 변환하는 조립 지점."""

    def __init__(
        self,
        *,
        camera_id: str,
        detector: Detector,
        absence_confirmation_seconds: float,
        trusted_sample_max_gap_seconds: float,
        entity_resolver: EntityResolver | None = None,
        motion_estimator: MotionEstimator | None = None,
    ) -> None:
        if not camera_id:
            raise ValueError("camera_id must not be empty")
        require_positive(absence_confirmation_seconds, "absence_confirmation_seconds")
        self._camera_id = camera_id
        self._detector = detector
        self._entity_resolver = (
            entity_resolver if entity_resolver is not None else PassthroughEntityResolver()
        )
        self._motion_estimator = (
            motion_estimator if motion_estimator is not None else MotionEstimator()
        )
        self._presence_confirmer = PhysicalVehiclePresenceConfirmer(
            absence_confirmation_seconds=absence_confirmation_seconds,
            trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
        )
        self._last_reliable_observed_at = None
        self._restart_unresolved_vehicle_ids: set[PhysicalVehicleId] = set()

    def open(self) -> None:
        """탐지·tracker 모델을 초기화한다."""

        self._detector.open()

    def process(
        self,
        frame: CapturedFrame,
        *,
        full_area_observed: bool,
    ) -> TrackingBatch:
        """프레임 한 장을 처리해 서로 분리된 tracking 신호를 반환한다.

        호출자가 calibration과 전체 관리 영역 포함을 확인한
        경우에만 `full_area_observed=True`를 넘긴다. 이 키워드는
        생략할 수 없어 신뢰 조건을 암묵적으로 fail-open하지 않는다.
        """

        if frame.camera_id != self._camera_id:
            self.pause_absence_confirmation()
            raise TrackingError(
                "frame camera_id does not match the tracking pipeline: "
                f"expected={self._camera_id}, actual={frame.camera_id}"
            )

        try:
            tracker_result = self._detector.track(frame)
        except TrackingError:
            # 추론 실패 뒤 첫 정상 frame이 실패 구간을 부재
            # trusted duration에 포함하지 않게 연속성을 끊고 원 예외를 유지한다.
            self.pause_absence_confirmation()
            raise

        if self._restart_unresolved_vehicle_ids and (
            tracker_result.observations
            or not tracker_result.all_detections_tracked
        ):
            # 현재 기본 resolver는 process 간 re-identification 근거가
            # 없다. 기존 차량을 새 UUID로 중복 생성하거나
            # 존재하는데 출차로 확정하지 않고, 전체 영역이
            # 빌 때까지 보수적 degraded 상태로 멈춘다.
            observation = ObservationStatus(
                state=ObservationState.UNKNOWN,
                reason=ObservationReason.REIDENTIFICATION_UNCERTAIN,
                last_reliable_observed_at=self._last_reliable_observed_at,
            )
            presence_result = self._presence_confirmer.update(
                observed_physical_vehicle_ids=set(),
                observed_at=frame.captured_at,
                trusted_full_area_sample=False,
            )
            self._entity_resolver.end_track_segments(
                set(tracker_result.ended_track_segment_ids)
            )
            return TrackingBatch(
                camera_id=self._camera_id,
                frame_id=frame.frame_id,
                observed_at=frame.captured_at,
                vehicles=(),
                ended_track_segment_ids=(
                    tracker_result.ended_track_segment_ids
                ),
                unobserved_physical_vehicle_ids=(
                    presence_result.unobserved_physical_vehicle_ids
                ),
                absence_progress=presence_result.absence_progress,
                observation=observation,
                full_area_observed=full_area_observed,
                all_detections_tracked=False,
                not_present_confirmed_vehicle_ids=(
                    presence_result.not_present_confirmed_vehicle_ids
                ),
            )
        batch_observation = self._batch_observation(
            observed_at=frame.captured_at,
            full_area_observed=full_area_observed,
        )

        vehicles: list[PhysicalVehicleSnapshot] = []
        observed_physical_vehicle_ids: set[PhysicalVehicleId] = set()
        for observation in tracker_result.observations:
            physical_vehicle_id = self._entity_resolver.resolve(observation)
            observed_physical_vehicle_ids.add(physical_vehicle_id)
            motion_signal = (
                self._motion_estimator.update(
                    physical_vehicle_id=physical_vehicle_id,
                    bbox=observation.bbox,
                )
                if full_area_observed
                else MotionSignal.UNKNOWN
            )
            vehicles.append(
                PhysicalVehicleSnapshot(
                    physical_vehicle_id=physical_vehicle_id,
                    track_segment_id=observation.track_segment_id,
                    bbox=observation.bbox,
                    confidence=observation.confidence,
                    motion_signal=motion_signal,
                    observed_at=observation.observed_at,
                    camera_id=self._camera_id,
                    observation=batch_observation,
                )
            )

        presence_result = self._presence_confirmer.update(
            observed_physical_vehicle_ids=observed_physical_vehicle_ids,
            observed_at=frame.captured_at,
            trusted_full_area_sample=(
                full_area_observed and tracker_result.all_detections_tracked
            ),
        )
        self._entity_resolver.end_track_segments(set(tracker_result.ended_track_segment_ids))

        return TrackingBatch(
            camera_id=self._camera_id,
            frame_id=frame.frame_id,
            observed_at=frame.captured_at,
            vehicles=tuple(vehicles),
            ended_track_segment_ids=tracker_result.ended_track_segment_ids,
            unobserved_physical_vehicle_ids=presence_result.unobserved_physical_vehicle_ids,
            absence_progress=presence_result.absence_progress,
            observation=batch_observation,
            full_area_observed=full_area_observed,
            all_detections_tracked=tracker_result.all_detections_tracked,
            not_present_confirmed_vehicle_ids=presence_result.not_present_confirmed_vehicle_ids,
        )

    def pause_absence_confirmation(self) -> None:
        """Camera·pipeline 장애 구간을 trusted duration에서 제외한다.

        프레임 캡처 또는 추론 실패로 `process()`가 호출되지 않은 경우
        상위 loop가 이 메서드를 호출해야 다음 정상 frame이 중단 구간의
        wall-clock을 합산하지 않는다.
        """

        self._presence_confirmer.pause()

    def forget_physical_vehicle(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """상위 owner가 PhysicalVehicle 종료를 commit한 뒤 ephemeral 상태를 정리한다."""

        self._entity_resolver.forget_physical_vehicle(physical_vehicle_id)
        self._presence_confirmer.forget(physical_vehicle_id)
        self._motion_estimator.forget(physical_vehicle_id)
        self._restart_unresolved_vehicle_ids.discard(physical_vehicle_id)

    def restore_active_checkpoints(
        self,
        vehicles: tuple[PhysicalVehicle, ...],
    ) -> None:
        """재시작 active identity와 durable 부재 checkpoint를 복원한다.

        restart-aware resolver는 durable 후보를 받아 즉시 재식별을
        재개한다. 기본 ``PassthroughEntityResolver``는 process 간
        재식별을 지원하지 않으므로 detection이 남아 있는 동안 신규
        identity 생성과 부재 누적을 멈추고, 정상 전체 영역이 빈 뒤에만
        durable 하한에서 NOT_PRESENT를 재개한다.
        """

        identities = tuple(vehicle.physical_vehicle_id for vehicle in vehicles)
        if len(identities) != len(set(identities)):
            raise ValueError("restart checkpoints contain duplicate PhysicalVehicleId")
        for vehicle in vehicles:
            if vehicle.state is not PhysicalVehicleState.ACTIVE:
                raise ValueError("only ACTIVE PhysicalVehicle may be restored")
            self.restore_absence_checkpoint(
                vehicle.physical_vehicle_id,
                trusted_seconds=vehicle.absence_trusted_seconds,
                absence_confirmation_seconds=(
                    vehicle.absence_confirmation_seconds
                ),
                trusted_sample_max_gap_seconds=(
                    vehicle.trusted_sample_max_gap_seconds
                ),
                confirmed_at=vehicle.absence_confirmed_at,
            )
        if isinstance(self._entity_resolver, RestartAwareEntityResolver):
            self._entity_resolver.restore_active_physical_vehicles(vehicles)
            self._restart_unresolved_vehicle_ids.clear()
        else:
            self._restart_unresolved_vehicle_ids = set(identities)

    def restore_absence_checkpoint(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        trusted_seconds: float,
        absence_confirmation_seconds: float,
        trusted_sample_max_gap_seconds: float,
        confirmed_at: datetime | None,
    ) -> None:
        """재식별을 마친 active 차량의 durable 부재 판단을 복원한다."""

        self._presence_confirmer.restore_checkpoint(
            physical_vehicle_id,
            trusted_seconds=trusted_seconds,
            absence_confirmation_seconds=absence_confirmation_seconds,
            trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
            confirmed_at=confirmed_at,
        )

    def close(self) -> None:
        """탐지·tracker 모델 자원을 해제한다."""

        self.pause_absence_confirmation()
        try:
            self._detector.close()
        finally:
            # 새 tracker runtime은 숫자 segment ID를 재사용할 수
            # 있으므로 이전 세대의 1:1 연결을 남기지 않는다.
            self._entity_resolver.reset_track_segments()

    def _batch_observation(
        self,
        *,
        observed_at: datetime,
        full_area_observed: bool,
    ) -> ObservationStatus:
        if full_area_observed:
            self._last_reliable_observed_at = observed_at
            return ObservationStatus(
                state=ObservationState.OBSERVED,
                last_reliable_observed_at=observed_at,
            )
        return ObservationStatus(
            state=ObservationState.DEGRADED,
            reason=ObservationReason.PARTIAL_FRAME,
            last_reliable_observed_at=self._last_reliable_observed_at,
        )
