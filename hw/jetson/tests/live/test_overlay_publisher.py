"""OverlayPublisher의 게시·예외 흡수·프레임 드롭 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import cv2
import numpy as np
import pytest

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.models import CapturedFrame
from src.domain.models import ObservationState, ObservationStatus
from src.live.frame_publishing import PLACEHOLDER_HEIGHT, PLACEHOLDER_WIDTH
from src.live.overlay_publisher import OverlayPublisher
from src.parking.models import (
    ParkingPipelineResult,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
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

# placeholder 크기(640x480)와 겹치지 않는 실제 프레임 크기 — 렌더 결과와
# placeholder 대체 결과를 디코드된 shape만으로 구분하기 위한 값이다.
_REAL_FRAME_SIZE = 100


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _publisher(render, clock, *, target_fps: float = 15.0) -> OverlayPublisher:
    return OverlayPublisher(render=render, target_fps=target_fps, monotonic=clock)


def _real_frame() -> CapturedFrame:
    return CapturedFrame(
        camera_id="cam-1",
        frame_id=1,
        captured_at=NOW,
        image=np.zeros((_REAL_FRAME_SIZE, _REAL_FRAME_SIZE, 3), dtype=np.uint8),
        width=_REAL_FRAME_SIZE,
        height=_REAL_FRAME_SIZE,
        calibration_id=CALIBRATION_ID,
    )


def _real_zone_registry() -> ZoneRegistry:
    return ZoneRegistry(
        [
            ZoneDefinition(
                zone_id=ZoneId(1),
                zone_type=ZoneType.GENERAL,
                polygon=((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
                zone_definition_version=ZoneDefinitionVersion(1),
                calibration_reference=CALIBRATION_ID,
            )
        ]
    )


def _real_vehicle() -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=VEHICLE_ID,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6),
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=NOW,
        camera_id="cam-1",
        observation=OBSERVED,
    )


def _real_tracking_batch() -> TrackingBatch:
    return TrackingBatch(
        camera_id="cam-1",
        frame_id=1,
        observed_at=NOW,
        vehicles=(_real_vehicle(),),
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(),
        absence_progress=(),
        observation=OBSERVED,
        full_area_observed=True,
        all_detections_tracked=True,
    )


def _real_result() -> FrameObservationResult:
    return FrameObservationResult(
        parking_result=ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_transitions=(),
        ),
        retired_physical_vehicle_ids=(),
    )


def test_latest_jpeg_is_none_before_any_frame() -> None:
    publisher = _publisher(lambda f, b, r: b"jpeg", _FakeClock())

    assert publisher.latest_jpeg() is None


def test_publishes_rendered_bytes_on_first_frame() -> None:
    publisher = _publisher(lambda f, b, r: b"first", _FakeClock())

    publisher(object(), object(), object())

    assert publisher.latest_jpeg() == b"first"


def test_drops_frames_arriving_faster_than_target_fps() -> None:
    clock = _FakeClock()
    rendered: list[bytes] = []

    def render(frame, tracking_batch, result) -> bytes:
        payload = f"frame-{len(rendered)}".encode("ascii")
        rendered.append(payload)
        return payload

    publisher = _publisher(render, clock, target_fps=10.0)

    publisher(object(), object(), object())
    clock.now = 0.05  # 목표 간격 0.1초의 절반 — 드롭돼야 한다
    publisher(object(), object(), object())

    assert rendered == [b"frame-0"]
    assert publisher.latest_jpeg() == b"frame-0"


def test_publishes_again_once_target_interval_has_passed() -> None:
    clock = _FakeClock()
    rendered: list[bytes] = []

    def render(frame, tracking_batch, result) -> bytes:
        payload = f"frame-{len(rendered)}".encode("ascii")
        rendered.append(payload)
        return payload

    publisher = _publisher(render, clock, target_fps=10.0)

    publisher(object(), object(), object())
    clock.now = 0.2
    publisher(object(), object(), object())

    assert rendered == [b"frame-0", b"frame-1"]
    assert publisher.latest_jpeg() == b"frame-1"


def test_swallows_render_failure_and_publishes_placeholder() -> None:
    def render(frame, tracking_batch, result) -> bytes:
        raise ValueError("render exploded")

    publisher = _publisher(render, _FakeClock())

    publisher(object(), object(), object())  # 예외가 밖으로 나오면 안 된다

    latest = publisher.latest_jpeg()
    assert latest is not None
    assert latest.startswith(b"\xff\xd8")  # JPEG SOI — placeholder가 들어갔다


def test_requires_zones_or_render() -> None:
    with pytest.raises(ValueError, match="zones 또는 render"):
        OverlayPublisher()


def test_rejects_non_positive_target_fps() -> None:
    with pytest.raises(ValueError, match="target_fps"):
        OverlayPublisher(render=lambda f, b, r: b"x", target_fps=0.0)


def test_zones_only_publisher_renders_real_frame_via_build_default_render() -> None:
    """`main.py`가 실제로 쓰는 유일한 경로: `render`를 넘기지 않고 `zones`만 넘기면
    `build_default_render`가 만든 클로저가 `render_overlay_jpeg`를 호출해야 한다.

    placeholder는 항상 640x480(PLACEHOLDER_WIDTH x PLACEHOLDER_HEIGHT)이므로, 입력
    프레임을 그와 다른 크기(100x100)로 주면 디코드된 결과 크기로 "진짜 렌더됨"과
    "렌더 실패 후 placeholder로 대체됨"을 구분할 수 있다.
    """

    publisher = OverlayPublisher(zones=_real_zone_registry(), monotonic=_FakeClock())

    publisher(_real_frame(), _real_tracking_batch(), _real_result())

    jpeg_bytes = publisher.latest_jpeg()
    assert jpeg_bytes is not None
    decoded = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (_REAL_FRAME_SIZE, _REAL_FRAME_SIZE, 3)
    assert decoded.shape != (PLACEHOLDER_HEIGHT, PLACEHOLDER_WIDTH, 3)
