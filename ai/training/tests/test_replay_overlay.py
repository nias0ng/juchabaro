"""OverlayWriter 계약 테스트.

픽셀 내용은 검증하지 않는다 — 그림이 맞는지는 사람이 보는 것이 이 도구의 목적이다.
대신 프레임 유실, 입력 배열 오염, 뒤늦은 인코더 실패를 막는다.
"""

from datetime import datetime, timezone

import cv2
import numpy as np
import pytest
from jetson_vehicle_tracking_baseline import (
    BaselineError,
    BoundingBox,
    CapturedFrame,
    ParkingZone,
    NormalizedPolygon,
    TrackSnapshot,
    VehicleBox,
    ViolationStatus,
    ZoneRegistry,
    ZoneType,
)
from replay.overlay import OverlayWriter

WIDTH, HEIGHT = 64, 48


def make_registry():
    return ZoneRegistry(
        [
            ParkingZone(
                zone_id=1,
                zone_number="GEN-01",
                zone_type=ZoneType.GENERAL,
                polygon=NormalizedPolygon(((0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4))),
            ),
            ParkingZone(
                zone_id=2,
                zone_number="AISLE-01",
                zone_type=ZoneType.AISLE,
                polygon=NormalizedPolygon(((0.5, 0.0), (0.9, 0.0), (0.9, 0.9), (0.5, 0.9))),
            ),
        ]
    )


def make_frame(frame_id=1):
    return CapturedFrame(
        frame_id=frame_id,
        captured_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        image=np.full((HEIGHT, WIDTH, 3), 100, dtype=np.uint8),
    )


def make_detection(track_id=1):
    return VehicleBox(
        track_id=track_id,
        bbox=BoundingBox(0.1, 0.1, 0.3, 0.3),
        confidence=0.9,
        frame_id=1,
        captured_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
    )


def make_snapshot(track_id=1, status=ViolationStatus.OBSERVING):
    return {track_id: TrackSnapshot(track_id=track_id, dwell_seconds=3.5, open_violation=status)}


def test_writes_one_output_frame_per_input_frame(tmp_path):
    path = tmp_path / "overlay.mp4"
    writer = OverlayWriter(path=path, fps=30.0, frame_size=(WIDTH, HEIGHT), zones=make_registry())
    writer.open()
    try:
        for frame_id in range(1, 6):
            writer.write(make_frame(frame_id), [make_detection()], make_snapshot(), [])
    finally:
        writer.close()

    capture = cv2.VideoCapture(str(path))
    try:
        written = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        capture.release()
    assert written == 5


def test_does_not_mutate_input_image(tmp_path):
    """RemapFrameSource는 dst 버퍼를 재사용하므로 원본을 그리면 다음 프레임이 오염된다."""
    writer = OverlayWriter(
        path=tmp_path / "overlay.mp4", fps=30.0, frame_size=(WIDTH, HEIGHT), zones=make_registry()
    )
    frame = make_frame()
    before = frame.image.copy()
    writer.open()
    try:
        writer.write(frame, [make_detection()], make_snapshot(), [])
    finally:
        writer.close()

    assert np.array_equal(frame.image, before)


def test_write_before_open_raises(tmp_path):
    writer = OverlayWriter(
        path=tmp_path / "overlay.mp4", fps=30.0, frame_size=(WIDTH, HEIGHT), zones=make_registry()
    )

    with pytest.raises(BaselineError):
        writer.write(make_frame(), [], {}, [])


def test_open_fails_fast_on_invalid_frame_size(tmp_path):
    """14,712프레임을 다 돌린 뒤 저장에 실패하면 낭비다.

    frame_size=(0,0)을 쓰는 이유는 실측이다 — 이 환경의 cv2는 fps=0을 조용히
    받아들여(isOpened()==True) 인코더 거부 테스트로 쓸 수 없다.
    """
    writer = OverlayWriter(
        path=tmp_path / "x.mp4",
        fps=30.0,
        frame_size=(0, 0),
        zones=make_registry(),
    )

    with pytest.raises(BaselineError):
        writer.open()


def test_handles_frame_with_no_detections(tmp_path):
    path = tmp_path / "overlay.mp4"
    writer = OverlayWriter(path=path, fps=30.0, frame_size=(WIDTH, HEIGHT), zones=make_registry())
    writer.open()
    try:
        writer.write(make_frame(), [], {}, [])
    finally:
        writer.close()

    assert path.exists()
