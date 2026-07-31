"""일시적인 트랙 구간들을 Jetson 내부 물리 차량으로 연결하는 모듈(436).

이번 티켓은 재식별 없는 통과 구현만 제공한다 — track_segment_id를 그대로
physical_vehicle_id로 쓴다(데이터흐름.md §5 "1단계 관통" 전략: "camera →
tracking(재식별 없이 TrackSegmentId를 PhysicalVehicleId로 직결)"). 실제
재결합 알고리즘은 T-13에서 구현한다.

ByteTrack이 track_buffer(기본 30프레임, 5fps에서 약 2~6초)를 넘겨 트랙을
잃으면 새 track_segment_id를 발급하므로, 이 통과 구현은 그 순간 "다른
물리 차량"으로 본다 — 같은 차일 수 있다는 게 §7 알려진 한계 1이다.
"""

from __future__ import annotations

from src.tracking.models import PhysicalVehicleId, TrackSegmentId


class PassthroughEntityResolver:
    """track_segment_id를 그대로 physical_vehicle_id로 변환하는 통과 구현."""

    def __init__(self) -> None:
        self._active_ids: set[TrackSegmentId] = set()

    def resolve(self, track_segment_id: TrackSegmentId) -> PhysicalVehicleId:
        """이번 프레임에 관측된 track_segment_id의 physical_vehicle_id를 반환한다."""

        self._active_ids.add(track_segment_id)
        return PhysicalVehicleId(f"track-{track_segment_id}")

    def resolve_ended(self, observed_track_segment_ids: set[TrackSegmentId]) -> list[PhysicalVehicleId]:
        """더 이상 관측되지 않는 physical_vehicle_id 목록을 반환하고 내부 상태에서 정리한다."""

        ended = self._active_ids - observed_track_segment_ids
        self._active_ids -= ended
        return [PhysicalVehicleId(f"track-{track_segment_id}") for track_segment_id in sorted(ended)]
