"""판정 결과를 프레임 위에 그려 mp4로 인코딩한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from jetson_vehicle_tracking_baseline import (
    BaselineError,
    CapturedFrame,
    TrackSnapshot,
    VehicleBox,
    ViolationEvent,
    ViolationStatus,
    ZoneRegistry,
    ZoneType,
    _import_cv2,
)

# 구역 종류별 색 (BGR).
_ZONE_COLORS: dict[ZoneType, tuple[int, int, int]] = {
    ZoneType.GENERAL: (0, 200, 0),
    ZoneType.DISABLED: (0, 128, 255),
    ZoneType.EV_FAST: (255, 128, 0),
    ZoneType.EV_SLOW: (255, 200, 0),
    ZoneType.AISLE: (128, 128, 128),
    ZoneType.ENTRY_EXIT: (200, 0, 200),
}
# 전용구역은 굵게, 통로·입출차 참조 도형은 얇게 그려 한눈에 구분되게 한다.
_THICK_ZONE_TYPES = frozenset({ZoneType.DISABLED, ZoneType.EV_FAST, ZoneType.EV_SLOW})
# 판정 상태별 bbox 색 (BGR). 미등록 상태(향후 추가되는 위반)는 빨강으로 떨어진다.
_STATUS_COLORS: dict[ViolationStatus, tuple[int, int, int]] = {
    ViolationStatus.NONE: (160, 160, 160),
    ViolationStatus.OBSERVING: (0, 220, 220),
}
_VIOLATION_COLOR = (0, 0, 255)


class OverlayWriter:
    """구역·bbox·정차시간·판정상태를 그린 프레임을 mp4로 쓴다."""

    def __init__(
        self, *, path: Path, fps: float, frame_size: tuple[int, int], zones: ZoneRegistry
    ) -> None:
        self._path = path
        self._fps = fps
        self._frame_size = frame_size
        self._zones = zones
        self._writer: Any | None = None
        self._event_count = 0

    def open(self) -> None:
        """인코더를 연다. 여기서 실패해야 프레임을 다 돌린 뒤 낭비하지 않는다."""

        if self._writer is not None:
            return
        cv2 = _import_cv2()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(self._path), cv2.VideoWriter_fourcc(*"mp4v"), self._fps, self._frame_size
        )
        if not writer.isOpened():
            writer.release()
            raise BaselineError(
                f"오버레이 mp4 인코더를 열 수 없습니다: {self._path} "
                f"(fps={self._fps}, size={self._frame_size})"
            )
        self._writer = writer

    def write(
        self,
        frame: CapturedFrame,
        detections: Sequence[VehicleBox],
        snapshot: Mapping[int, TrackSnapshot],
        events: Sequence[ViolationEvent],
    ) -> None:
        """한 프레임을 그려서 쓴다."""

        if self._writer is None:
            raise BaselineError("오버레이가 초기화되지 않았습니다. open()을 먼저 호출하세요.")
        cv2 = _import_cv2()
        self._event_count += len(events)
        # 원본을 그리면 안 된다 — RemapFrameSource가 dst 버퍼를 재사용하므로
        # 다음 프레임에 이번 낙서가 남는다.
        canvas = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR).copy()
        self._draw_zones(canvas, cv2)
        self._draw_tracks(canvas, detections, snapshot, cv2)
        self._draw_header(canvas, frame, events, cv2)
        self._writer.write(canvas)

    def _draw_zones(self, canvas: Any, cv2: Any) -> None:
        import numpy as np

        height, width = canvas.shape[:2]
        for zone in self._zones.all():
            color = _ZONE_COLORS.get(zone.zone_type, (255, 255, 255))
            thickness = 3 if zone.zone_type in _THICK_ZONE_TYPES else 1
            points = np.array(
                [[int(x * width), int(y * height)] for x, y in zone.polygon.points], dtype=np.int32
            )
            cv2.polylines(canvas, [points], isClosed=True, color=color, thickness=thickness)
            cv2.putText(
                canvas, zone.zone_number, tuple(points[0]),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )

    def _draw_tracks(
        self,
        canvas: Any,
        detections: Sequence[VehicleBox],
        snapshot: Mapping[int, TrackSnapshot],
        cv2: Any,
    ) -> None:
        height, width = canvas.shape[:2]
        for detection in detections:
            state = snapshot.get(detection.track_id)
            status = state.open_violation if state else ViolationStatus.NONE
            dwell = state.dwell_seconds if state else 0.0
            color = _STATUS_COLORS.get(status, _VIOLATION_COLOR)
            x1 = int(detection.bbox.x1 * width)
            y1 = int(detection.bbox.y1 * height)
            x2 = int(detection.bbox.x2 * width)
            y2 = int(detection.bbox.y2 * height)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            cv2.putText(
                canvas,
                f"#{detection.track_id} {dwell:.0f}s {status.value}",
                (x1, max(12, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )

    def _draw_header(
        self, canvas: Any, frame: CapturedFrame, events: Sequence[ViolationEvent], cv2: Any
    ) -> None:
        cv2.putText(
            canvas,
            f"frame={frame.frame_id} t={frame.captured_at.isoformat()} events={self._event_count}",
            (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        )
        for index, event in enumerate(events):
            # 스크럽으로 위반 발생 순간을 찾을 수 있게 그 프레임에만 배너를 남긴다.
            cv2.putText(
                canvas,
                f"NEW {event.status.value} #{event.track_id} zone={event.zone_number or '-'}",
                (10, 44 + index * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, _VIOLATION_COLOR, 2,
            )

    def close(self) -> None:
        """인코더를 닫는다."""

        writer, self._writer = self._writer, None
        if writer is not None:
            writer.release()
