# 478 라이브 오버레이 렌더러 구현 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `MonitoringPipeline`의 `frame_observer` 콜백(477에서 추가됨)이 받는 `(frame, tracking_batch, result)`를 구역 폴리곤·차량 bbox·판정상태가 그려진 JPEG bytes로 변환하는 `src/live/live_overlay_renderer.py`를 새로 만든다.

**Architecture:** 그리기(순수 numpy 연산, 픽셀 단위로 정확히 테스트 가능)와 JPEG 인코딩(손실 압축, 구조만 검증)을 별도 함수로 분리한다 — `draw_overlay()`가 BGR `np.ndarray`를 반환하고 `encode_jpeg()`가 그것을 JPEG bytes로 바꾼다. `render_overlay_jpeg()`가 둘을 이어붙인 최종 진입점이다. 옛 `ai/tracking/replay/overlay.py`의 `OverlayWriter`(그리는 방식만 참고, 데이터 계약은 재사용 안 함)와 달리 466 이후 정착된 `ZoneVisit`/`ParkingEpisode` 계약에서 상태를 읽는다.

**Tech Stack:** Python, OpenCV(`cv2`)·numpy(이미 `hw/jetson/requirements.txt`에 존재), pytest.

## Global Constraints

- `frame.image`를 직접 수정하지 않는다 — `RemapFrameSource`가 dst 버퍼를 재사용하므로 그리기 전에 반드시 `.copy()`한다(`docs/superpowers/specs/2026-08-03-live-demo-streaming-design.md`의 옛 `OverlayWriter` 주석과 같은 이유).
- 이 렌더러는 **유효한 도메인 상태**(터미널 `ZoneVisit`/`ParkingEpisode`, 매칭되는 상태가 전혀 없는 차량, 빈 zone/episode 목록) 앞에서 절대 예외를 던지지 않는다 — 이건 이번 작업(478)의 책임이다. 반면 **실제 렌더링·인코딩 실패**(예: `cv2.imencode` 실패)를 잡아 placeholder 프레임으로 대체하는 책임은 스펙 문서 에러 처리 섹션이 명시한 대로 479(`live_stream_loop`)의 몫이다 — 478은 그 경계까지만 구현한다.
- 색상은 구역 종류(정적 구조)와 차량 판정 상태(동적)를 별도 팔레트로 분리하고, 팔레트 안의 모든 BGR 튜플은 서로 달라야 한다(테스트가 정확한 픽셀색 일치로 상태를 구분하므로 색이 겹치면 테스트가 우연히 통과할 수 있다).
- `ParkingEpisode`가 있어도 `state`가 `ENDED`/`CANCELED`(터미널)이면 "활성 주차 판정 없음"으로 취급하고 `ZoneVisit` 기반 색으로 폴백한다 — `ParkingEpisode.state`는 `STOP_PENDING`/`PARKED`/`MOVE_PENDING`/`ENDED`/`CANCELED`(`hw/jetson/src/parking/models.py:72-79`)이고 색 팔레트는 앞의 세 개만 정의하므로, 이 폴백이 없으면 터미널 상태에서 `KeyError`가 난다.
- 한 차량이 같은 프레임에 여러 `ZoneVisit`(여러 구역과 동시 겹침)을 가질 수 있으므로 우선순위 `INSIDE > ENTERING > EXITING > ENDED > CANCELED`로 대표 하나를 고른다(`hw/jetson/src/parking/pipeline.py:222-233`가 차량당 구역마다 독립적으로 `ZoneVisit`을 만들 수 있음을 보여준다). `ParkingEpisode`는 차량당 최대 1개만 나오므로(`pipeline.py:237-255`) 그런 우선순위가 필요 없다.

---

### Task 1: `draw_overlay`/`encode_jpeg`/`render_overlay_jpeg` 구현

**Files:**
- Create: `hw/jetson/src/live/__init__.py` (빈 파일, 기존 `src/camera/__init__.py`와 같은 패턴)
- Create: `hw/jetson/src/live/live_overlay_renderer.py`
- Test: `hw/jetson/tests/live/test_live_overlay_renderer.py`

**Interfaces:**
- Consumes: `CapturedFrame`(`src/camera/models.py`), `TrackingBatch`/`PhysicalVehicleSnapshot`(`src/tracking/models.py`), `FrameObservationResult`/`ParkingPipelineResult`(`src/application/frame_observation_workflow.py`, `src/parking/models.py`), `ZoneVisit`/`ZoneVisitState`/`ParkingEpisode`/`ParkingState`/`ZoneDefinition`/`ZoneType`(`src/parking/models.py`), `ZoneRegistry`(`src/parking/zone_registry.py`).
- Produces: `draw_overlay(frame, tracking_batch, result, *, zones: ZoneRegistry) -> np.ndarray`(BGR uint8), `encode_jpeg(canvas: np.ndarray, *, jpeg_quality: int = 80) -> bytes`, `render_overlay_jpeg(frame, tracking_batch, result, *, zones: ZoneRegistry, jpeg_quality: int = 80) -> bytes`. 479는 `render_overlay_jpeg`를 `functools.partial`이나 클로저로 `zones`/`jpeg_quality`를 고정해 `FrameObserver` 콜백(`Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], None]`, 477에서 정의)에 연결한다 — 이 함수 자체는 반환값이 있어 `FrameObserver`와 시그니처가 다르다는 점에 유의.

- [ ] **Step 1: 실패하는 테스트 작성 — 구역 폴리곤이 종류별 색으로 그려진다**

`hw/jetson/tests/live/test_live_overlay_renderer.py`를 새로 만든다:

```python
"""live_overlay_renderer의 픽셀 단위 그리기·인코딩 회귀 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import cv2
import numpy as np
import pytest

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
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_draw_overlay_paints_zone_polygon_with_type_color -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.live'`

- [ ] **Step 3: `src/live/live_overlay_renderer.py` 최초 구현 (구역 그리기까지)**

`hw/jetson/src/live/__init__.py`를 빈 파일로 만든다.

`hw/jetson/src/live/live_overlay_renderer.py`를 만든다:

```python
"""판정 결과를 실시간 프레임 위에 그려 JPEG로 인코딩한다.

`ai/tracking/replay/overlay.py`의 `OverlayWriter`는 재사용하지 않는다 —
그 코드는 폐기 예정인 옛 baseline(`ViolationStatus` 등) 계약에 물려 있고,
여기서는 466 이후 정착된 `ZoneVisit`/`ParkingEpisode` 계약을 그린다.

그리기(`draw_overlay`)와 JPEG 인코딩(`encode_jpeg`)을 분리했다 — 그리기는
순수 numpy 연산이라 픽셀 단위로 정확히 테스트할 수 있고, JPEG는 손실
압축이라 같은 방식으로 테스트할 수 없다.
"""

from __future__ import annotations

from typing import Mapping

import cv2
import numpy as np

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.models import CapturedFrame
from src.parking.models import ParkingEpisode, ParkingState, ZoneType, ZoneVisit, ZoneVisitState
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import PhysicalVehicleId, TrackingBatch

_ZONE_COLORS: dict[ZoneType, tuple[int, int, int]] = {
    ZoneType.GENERAL: (0, 200, 0),
    ZoneType.DISABLED: (0, 128, 255),
    ZoneType.EV_CHARGING: (255, 128, 0),
    ZoneType.AISLE: (128, 128, 128),
    ZoneType.ENTRY_EXIT: (200, 0, 200),
}
_THICK_ZONE_TYPES = frozenset({ZoneType.DISABLED, ZoneType.EV_CHARGING})


def draw_overlay(
    frame: CapturedFrame,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
    *,
    zones: ZoneRegistry,
) -> np.ndarray:
    """RGB `CapturedFrame` 위에 구역·bbox·판정상태를 그린 BGR uint8 canvas를 반환한다.

    `frame.image`는 수정하지 않는다 — `RemapFrameSource`가 dst 버퍼를
    재사용하므로 그리기 전에 복사해 다음 프레임에 낙서가 남는 것을 막는다.
    """

    canvas = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR).copy()
    _draw_zones(canvas, zones)
    return canvas


def _draw_zones(canvas: np.ndarray, zones: ZoneRegistry) -> None:
    height, width = canvas.shape[:2]
    for zone in zones.all():
        color = _ZONE_COLORS.get(zone.zone_type, (255, 255, 255))
        thickness = 3 if zone.zone_type in _THICK_ZONE_TYPES else 1
        points = np.array(
            [[int(x * width), int(y * height)] for x, y in zone.polygon], dtype=np.int32
        )
        cv2.polylines(canvas, [points], isClosed=True, color=color, thickness=thickness)
        cv2.putText(
            canvas, str(zone.zone_id), tuple(points[0]),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_draw_overlay_paints_zone_polygon_with_type_color -v`
Expected: PASS

- [ ] **Step 5: 실패하는 테스트 작성 — 매칭되는 판정이 없으면 차량 bbox는 중립색**

`test_live_overlay_renderer.py`에 추가:

```python
def test_draw_overlay_paints_vehicle_bbox_neutral_when_no_zone_visit_or_episode() -> None:
    vehicle = _vehicle(BoundingBox(x1=0.2, y1=0.2, x2=0.6, y2=0.6))
    canvas = draw_overlay(
        _frame(), _tracking_batch((vehicle,)), _result(), zones=_zone_registry()
    )

    assert _row_has_color(canvas, 20, NEUTRAL_COLOR)
```

- [ ] **Step 6: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_draw_overlay_paints_vehicle_bbox_neutral_when_no_zone_visit_or_episode -v`
Expected: FAIL — 아직 차량을 전혀 그리지 않으므로 `NEUTRAL_COLOR`가 어떤 픽셀에도 없어 `assert` 실패.

- [ ] **Step 7: 차량 bbox 그리기 구현 (중립색까지)**

`live_overlay_renderer.py`의 상단 상수 블록에 추가:

```python
_NEUTRAL_COLOR = (160, 160, 160)
```

`draw_overlay()` 본문에 `_draw_vehicles` 호출을 추가:

```python
    canvas = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR).copy()
    _draw_zones(canvas, zones)
    _draw_vehicles(canvas, tracking_batch, result)
    return canvas
```

`_draw_zones` 함수 뒤에 추가:

```python
def _draw_vehicles(
    canvas: np.ndarray,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
) -> None:
    height, width = canvas.shape[:2]
    episode_by_vehicle = _index_episodes(result.parking_result.parking_episode_updates)
    visit_by_vehicle = _index_zone_visits(result.parking_result.zone_visit_updates)

    for vehicle in tracking_batch.vehicles:
        color, label_suffix = _vehicle_status(
            vehicle.physical_vehicle_id, episode_by_vehicle, visit_by_vehicle
        )
        x1 = int(vehicle.bbox.x1 * width)
        y1 = int(vehicle.bbox.y1 * height)
        x2 = int(vehicle.bbox.x2 * width)
        y2 = int(vehicle.bbox.y2 * height)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        short_id = str(vehicle.physical_vehicle_id)[:8]
        cv2.putText(
            canvas, f"#{short_id} {label_suffix}".rstrip(), (x1, max(12, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )


def _index_episodes(
    episodes: tuple[ParkingEpisode, ...]
) -> Mapping[PhysicalVehicleId, ParkingEpisode]:
    return {episode.physical_vehicle_id: episode for episode in episodes}


def _index_zone_visits(
    visits: tuple[ZoneVisit, ...]
) -> Mapping[PhysicalVehicleId, tuple[ZoneVisit, ...]]:
    grouped: dict[PhysicalVehicleId, list[ZoneVisit]] = {}
    for visit in visits:
        grouped.setdefault(visit.physical_vehicle_id, []).append(visit)
    return {vehicle_id: tuple(group) for vehicle_id, group in grouped.items()}


def _vehicle_status(
    vehicle_id: PhysicalVehicleId,
    episode_by_vehicle: Mapping[PhysicalVehicleId, ParkingEpisode],
    visit_by_vehicle: Mapping[PhysicalVehicleId, tuple[ZoneVisit, ...]],
) -> tuple[tuple[int, int, int], str]:
    return _NEUTRAL_COLOR, ""
```

이 시점에서는 `_vehicle_status`가 항상 중립색을 반환하는 최소 구현이다 — Step 9/11에서 실제 상태 분기를 채운다.

- [ ] **Step 8: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py -v`
Expected: 지금까지 작성한 2개 테스트 PASS

- [ ] **Step 9: 실패하는 테스트 작성 — `ZoneVisit.state`에 따른 색, 그리고 우선순위**

`test_live_overlay_renderer.py`에 추가:

```python
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
```

- [ ] **Step 10: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_draw_overlay_paints_vehicle_bbox_with_zone_visit_color_when_inside tests/live/test_live_overlay_renderer.py::test_draw_overlay_prefers_inside_zone_visit_over_entering_when_both_present -v`
Expected: 둘 다 FAIL — `_vehicle_status`가 아직 항상 중립색만 반환.

- [ ] **Step 11: `ZoneVisit` 상태 기반 색상·우선순위 구현**

`live_overlay_renderer.py` 상단 상수 블록에 추가:

```python
_ZONE_VISIT_COLORS: dict[ZoneVisitState, tuple[int, int, int]] = {
    ZoneVisitState.ENTERING: (0, 220, 220),
    ZoneVisitState.INSIDE: (0, 255, 0),
    ZoneVisitState.EXITING: (0, 165, 255),
    ZoneVisitState.ENDED: _NEUTRAL_COLOR,
    ZoneVisitState.CANCELED: _NEUTRAL_COLOR,
}
_ZONE_VISIT_PRIORITY: tuple[ZoneVisitState, ...] = (
    ZoneVisitState.INSIDE,
    ZoneVisitState.ENTERING,
    ZoneVisitState.EXITING,
    ZoneVisitState.ENDED,
    ZoneVisitState.CANCELED,
)
```

`_vehicle_status`를 교체:

```python
def _vehicle_status(
    vehicle_id: PhysicalVehicleId,
    episode_by_vehicle: Mapping[PhysicalVehicleId, ParkingEpisode],
    visit_by_vehicle: Mapping[PhysicalVehicleId, tuple[ZoneVisit, ...]],
) -> tuple[tuple[int, int, int], str]:
    visits = visit_by_vehicle.get(vehicle_id)
    if visits:
        visit = _pick_primary_visit(visits)
        return _ZONE_VISIT_COLORS[visit.state], f"zone{visit.zone_id} {visit.state.value}"

    return _NEUTRAL_COLOR, ""
```

`_index_zone_visits` 함수 뒤에 추가:

```python
def _pick_primary_visit(visits: tuple[ZoneVisit, ...]) -> ZoneVisit:
    by_state = {visit.state: visit for visit in visits}
    for state in _ZONE_VISIT_PRIORITY:
        if state in by_state:
            return by_state[state]
    return visits[0]
```

- [ ] **Step 12: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py -v`
Expected: 지금까지 작성한 4개 테스트 PASS

- [ ] **Step 13: 실패하는 테스트 작성 — 활성 `ParkingEpisode`가 `ZoneVisit`보다 우선하고, 터미널 `ParkingEpisode`는 크래시 없이 폴백한다**

`test_live_overlay_renderer.py`에 추가:

```python
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
```

- [ ] **Step 14: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_draw_overlay_prefers_active_parking_episode_color_over_zone_visit tests/live/test_live_overlay_renderer.py::test_draw_overlay_falls_back_to_zone_visit_when_episode_is_terminal tests/live/test_live_overlay_renderer.py::test_draw_overlay_falls_back_to_neutral_when_terminal_episode_has_no_zone_visit -v`
Expected: 3개 모두 FAIL — `_vehicle_status`가 아직 `episode_by_vehicle`을 전혀 참조하지 않음.

- [ ] **Step 15: `ParkingEpisode` 우선순위·터미널 폴백 구현**

`live_overlay_renderer.py` 상단 상수 블록에 추가:

```python
_PARKING_EPISODE_COLORS: dict[ParkingState, tuple[int, int, int]] = {
    ParkingState.STOP_PENDING: (0, 255, 255),
    ParkingState.PARKED: (0, 0, 255),
    ParkingState.MOVE_PENDING: (0, 255, 255),
}
_ACTIVE_PARKING_STATES = frozenset(_PARKING_EPISODE_COLORS)
```

`_vehicle_status`를 교체:

```python
def _vehicle_status(
    vehicle_id: PhysicalVehicleId,
    episode_by_vehicle: Mapping[PhysicalVehicleId, ParkingEpisode],
    visit_by_vehicle: Mapping[PhysicalVehicleId, tuple[ZoneVisit, ...]],
) -> tuple[tuple[int, int, int], str]:
    episode = episode_by_vehicle.get(vehicle_id)
    if episode is not None and episode.state in _ACTIVE_PARKING_STATES:
        return _PARKING_EPISODE_COLORS[episode.state], episode.state.value

    visits = visit_by_vehicle.get(vehicle_id)
    if visits:
        visit = _pick_primary_visit(visits)
        return _ZONE_VISIT_COLORS[visit.state], f"zone{visit.zone_id} {visit.state.value}"

    return _NEUTRAL_COLOR, ""
```

`episode.state in _ACTIVE_PARKING_STATES`가 터미널 상태(`ENDED`/`CANCELED`)를 걸러내므로, `_PARKING_EPISODE_COLORS[episode.state]` 조회는 항상 그 3개 키 중 하나에만 일어나 `KeyError`가 나지 않는다.

- [ ] **Step 16: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py -v`
Expected: 지금까지 작성한 7개 테스트 PASS

- [ ] **Step 17: 실패하는 테스트 작성 — `encode_jpeg`와 `render_overlay_jpeg`**

`test_live_overlay_renderer.py`에 추가:

```python
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
```

- [ ] **Step 18: 테스트 실행해 실패 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_encode_jpeg_returns_decodable_bytes_of_same_shape tests/live/test_live_overlay_renderer.py::test_render_overlay_jpeg_composes_draw_and_encode -v`
Expected: FAIL — `ImportError: cannot import name 'encode_jpeg' from 'src.live.live_overlay_renderer'` (`render_overlay_jpeg`도 아직 없어 같은 import 줄에서 실패).

- [ ] **Step 19: `encode_jpeg`/`render_overlay_jpeg` 구현**

`live_overlay_renderer.py`의 `draw_overlay` 함수 뒤, `_draw_zones` 함수 앞에 추가:

```python
def encode_jpeg(canvas: np.ndarray, *, jpeg_quality: int = 80) -> bytes:
    """BGR canvas를 JPEG bytes로 인코딩한다."""

    ok, buffer = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise ValueError("JPEG 인코딩에 실패했습니다")
    return buffer.tobytes()


def render_overlay_jpeg(
    frame: CapturedFrame,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
    *,
    zones: ZoneRegistry,
    jpeg_quality: int = 80,
) -> bytes:
    """`(frame, tracking_batch, result)` -> JPEG bytes. `FrameObserver`에 zones/jpeg_quality를 고정해 연결하는 진입점."""

    canvas = draw_overlay(frame, tracking_batch, result, zones=zones)
    return encode_jpeg(canvas, jpeg_quality=jpeg_quality)
```

- [ ] **Step 20: 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py::test_encode_jpeg_returns_decodable_bytes_of_same_shape tests/live/test_live_overlay_renderer.py::test_render_overlay_jpeg_composes_draw_and_encode -v`
Expected: PASS

- [ ] **Step 21: 전체 테스트 실행해 통과 확인**

Run: `cd hw/jetson && uv run pytest tests/live/test_live_overlay_renderer.py -v`
Expected: 9개 테스트 전부 PASS

Run: `cd hw/jetson && uv run pytest -q`
Expected: 이전과 동일하게 `tests/evidence/test_spool.py`의 6개(Windows 환경 fsync 이슈, 이번 변경과 무관 — 477 작업 때 `develop` tip에서도 동일하게 확인함)만 실패하고 나머지는 전부 PASS. 이 6개 외에 새로운 실패가 있으면 안 된다.

- [ ] **Step 22: 커밋**

```bash
cd hw/jetson
git add src/live/__init__.py src/live/live_overlay_renderer.py tests/live/test_live_overlay_renderer.py
git commit -m "$(cat <<'EOF'
feat(ai): 라이브 오버레이 렌더러(live_overlay_renderer) 구현

MonitoringPipeline의 frame_observer(477)가 넘겨주는 (frame,
tracking_batch, result)를 구역 폴리곤·차량 bbox·ZoneVisit/ParkingEpisode
판정상태가 그려진 JPEG bytes로 바꾼다. 그리기(draw_overlay, 픽셀 단위로
정확히 테스트)와 JPEG 인코딩(encode_jpeg, 손실 압축이라 근사 검증)을
분리했다. 옛 OverlayWriter(ViolationStatus 계약)는 재사용하지 않는다.

478
EOF
)"
```
