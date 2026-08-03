"""일시적인 트랙 구간들을 Jetson 내부 물리 차량으로 연결한다.

현재 기본 구현은 재식별 없는 통과 구현이다. 활성 track_segment_id마다
별도의 UUID physical_vehicle_id를 하나 발급하지만 여러 트랙 구간을 같은
물리 차량으로 재결합하지는 않는다. 재결합 구현은
``TrackObservation``의 시각·기하 근거와 durable candidate를 결합해야 한다.

ByteTrack이 track_buffer를 넘겨 segment 종료를 확정하면 연결만
해제한다. 현재 frame의 미관측은 segment 종료로 추론하지 않는다.
이 통과 구현은 종료 뒤 새 segment를 기존 PhysicalVehicle에
재식별하지 않는다.
"""

from __future__ import annotations

from uuid import uuid4

from src.tracking.models import PhysicalVehicleId, TrackObservation, TrackSegmentId


class PassthroughEntityResolver:
    """활성 track_segment_id와 UUID physical_vehicle_id를 1:1로 유지하는 통과 구현."""

    def __init__(self) -> None:
        self._active_ids: dict[TrackSegmentId, PhysicalVehicleId] = {}

    def resolve(self, observation: TrackObservation) -> PhysicalVehicleId:
        """이번 프레임에 관측된 track_segment_id의 physical_vehicle_id를 반환한다."""

        track_segment_id = observation.track_segment_id
        physical_vehicle_id = self._active_ids.get(track_segment_id)
        if physical_vehicle_id is None:
            physical_vehicle_id = PhysicalVehicleId(uuid4())
            self._active_ids[track_segment_id] = physical_vehicle_id
        return physical_vehicle_id

    def end_track_segments(
        self,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> None:
        """Adapter가 확정한 segment 연결만 해제한다.

        연결 해제는 반환값이 없으며 차량의 출차·RETIRED를
        의미하지 않는다.
        """

        for track_segment_id in sorted(ended_track_segment_ids):
            self._active_ids.pop(track_segment_id, None)

    def forget_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> None:
        """상위 owner가 종료를 commit한 차량의 모든 segment를 해제한다.

        NOT_PRESENT 확정이 ByteTrack removed 보고보다 먼저 올 수 있다.
        이 연결을 남기면 같은 segment ID가 재등장했을 때 이미 종료된
        PhysicalVehicle identity가 다시 살아난다.
        """

        attached_segment_ids = tuple(
            sorted(
                track_segment_id
                for track_segment_id, attached_vehicle_id in self._active_ids.items()
                if attached_vehicle_id == physical_vehicle_id
            )
        )
        for track_segment_id in attached_segment_ids:
            del self._active_ids[track_segment_id]

    def reset_track_segments(self) -> None:
        """Tracker runtime이 교체되면 숫자 segment ID 세대를 초기화한다."""

        self._active_ids.clear()
