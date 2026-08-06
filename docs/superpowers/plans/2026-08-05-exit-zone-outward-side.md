# 출차 구역 외부측 도달 판정 구현 계획 (Jira 571)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ParkingPipeline.exit_zone_traversal_observed()`의 판정을 "출차 구역과 겹쳤다"에서 "출차 구역의 **외부측**에 도달했다"로 좁혀, 출차 통로 안쪽에 정지한 채 가려진 차량이 출차로 오판되지 않게 한다.

**Architecture:** 외부 방향을 기존 폴리곤에서 유도한다 — 가장 가까운 `AISLE` 구역 중심에서 `EXIT` 구역 중심으로 향하는 벡터다. 그 방향에 수직이고 `EXIT` 중심을 지나는 직선으로 `EXIT` 폴리곤을 잘라 외부측 조각을 만든다(registry 구성 시 1회). `ParkingPipeline`은 신뢰 가능한 관측 프레임마다 차량별 외부측 접촉 구역 집합을 덮어쓰고, 판정은 "열린 `EXIT` role ZoneVisit의 구역이 그 집합에 있는가"가 된다.

**Tech Stack:** Python 3.10.12, pytest — `hw/jetson`의 기존 스택과 동일.

## Global Constraints

- 대상 브랜치: `feature/ai/571-exit-zone-outward-side`. **`feature/ai/565-exit-zone-traversal-signal` 위에 stacked**되어 있다(565는 아직 develop에 병합되지 않았다). Jira 571 = 이 브랜치 = 이 MR.
- 스펙: [`docs/superpowers/specs/2026-08-05-exit-zone-outward-side-design.md`](../specs/2026-08-05-exit-zone-outward-side-design.md) — 모호한 점은 이 문서를 먼저 확인한다.
- **새 설정 임계값을 만들지 않는다.** 기준선은 폴리곤 중심(유도값)이고, 접촉 판정은 교차 면적 > 0(임계값 없음)이다.
- **마이그레이션을 만들지 않는다.** 외부측 접촉 상태는 in-memory ephemeral이다.
- **`exit_zone_traversal_observed()`의 시그니처와 호출 지점을 바꾸지 않는다.** `src/application/physical_presence_workflow.py`, `src/application/pending_handoff_workflow.py`는 이 작업에서 수정하지 않는다.
- `src/parking/zone_visit_tracker.py`와 `src/tracking/` 아래는 수정하지 않는다. 방향(motion) 판정은 이 스펙에서 의식적으로 배제했다 — `MotionEstimator`를 건드리지 않는다.
- 기존 import 목록은 알파벳 순서를 유지한다.
- **테스트 실행 명령**(이 환경에 시스템 python이 없다):
  ```
  cd "C:/kiddo/ssafy/pjt1/.claude/worktrees/feature+ai+571-exit-zone-outward-side/hw/jetson"
  "C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests -q
  ```
- **테스트 기준선**: 이 브랜치 시작 시점의 전체 스위트는 `2 failed, 877 passed`다. 실패 2건(`tests/parking/test_zone_registry.py::test_loads_tracked_deployment_snapshot`, `tests/test_main.py::test_lifespan_prepares_runtime_and_stops_monitoring_worker`)은 `origin/develop`에도 있는 기존 문제다. **고치지 말고, 쫓지도 말 것.** 그 둘 외의 실패만 이 작업의 책임이다.

---

## Task 1: `geometry.py`에 폴리곤 중심과 반평면 클리핑 추가

**Files:**
- Modify: `hw/jetson/src/parking/geometry.py` — 심볼: `polygon_centroid`(신규), `clip_polygon_to_half_plane`(신규)
- Modify: `hw/jetson/tests/parking/test_geometry.py` — 신규 테스트 8개

**Interfaces:**
- Consumes: 없음(시작점). 기존 private `_clip_half_plane`(같은 파일)과 `signed_polygon_area`를 사용한다.
- Produces:
  - `polygon_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]`
  - `clip_polygon_to_half_plane(points: Sequence[tuple[float, float]], origin: tuple[float, float], direction: tuple[float, float]) -> list[tuple[float, float]]`

  Task 2가 `zone_registry.py`에서 두 함수를 모두 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`hw/jetson/tests/parking/test_geometry.py` 맨 끝에 추가한다. import 목록에 `polygon_centroid`와 `clip_polygon_to_half_plane`를 추가한다(기존 `from src.parking.geometry import (...)` 블록, 알파벳 순서 유지):

```python
def test_polygon_centroid_of_unit_square_is_its_middle() -> None:
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    assert polygon_centroid(square) == pytest.approx((0.5, 0.5))


def test_polygon_centroid_is_independent_of_winding_and_start_vertex() -> None:
    clockwise = ((0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0))
    rotated = ((1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.0, 1.0))
    assert polygon_centroid(clockwise) == pytest.approx((0.5, 0.5))
    assert polygon_centroid(rotated) == pytest.approx((0.5, 0.5))


def test_polygon_centroid_rejects_degenerate_polygon() -> None:
    with pytest.raises(ValueError, match="area"):
        polygon_centroid(((0.0, 0.0), (1.0, 1.0), (2.0, 2.0)))


def test_half_plane_clip_keeps_fully_inside_polygon() -> None:
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    clipped = clip_polygon_to_half_plane(square, (0.0, 0.0), (1.0, 0.0))
    assert polygon_area(clipped) == pytest.approx(1.0)


def test_half_plane_clip_drops_fully_outside_polygon() -> None:
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    assert clip_polygon_to_half_plane(square, (2.0, 0.0), (1.0, 0.0)) == []


def test_half_plane_clip_halves_polygon_through_its_centre() -> None:
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    clipped = clip_polygon_to_half_plane(square, (0.5, 0.5), (1.0, 0.0))
    assert polygon_area(clipped) == pytest.approx(0.5)
    assert min(x for x, _ in clipped) == pytest.approx(0.5)


def test_half_plane_clip_handles_diagonal_direction() -> None:
    """외부 방향은 축에 정렬되지 않는다(실측값 약 (+0.5, -0.87))."""

    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    clipped = clip_polygon_to_half_plane(square, (0.5, 0.5), (1.0, -1.0))
    assert polygon_area(clipped) == pytest.approx(0.5)
    # 잘린 조각은 오른쪽 아래 절반이므로 (0,1) 꼭짓점을 포함하지 않는다.
    assert all(
        not (x == pytest.approx(0.0) and y == pytest.approx(1.0)) for x, y in clipped
    )


def test_half_plane_clip_rejects_zero_direction() -> None:
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    with pytest.raises(ValueError, match="zero vector"):
        clip_polygon_to_half_plane(square, (0.5, 0.5), (0.0, 0.0))
```

- [ ] **Step 2: 테스트가 실패함을 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests/parking/test_geometry.py -v` (from `hw/jetson`)
Expected: FAIL — `ImportError: cannot import name 'polygon_centroid'`.

- [ ] **Step 3: 구현**

`hw/jetson/src/parking/geometry.py`의 `signed_polygon_area` 정의 바로 뒤에 추가한다:

```python
def polygon_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """shoelace 가중 중심을 반환한다.

    꼭짓점 순서(시계/반시계)와 시작 꼭짓점에 무관하다. 면적이 0인
    degenerate polygon은 중심이 정의되지 않으므로 거부한다.
    """

    area = signed_polygon_area(points)
    if area == 0.0:
        raise ValueError("polygon centroid requires a non-zero area")

    weighted_x = 0.0
    weighted_y = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        weighted_x += (x1 + x2) * cross
        weighted_y += (y1 + y2) * cross
    return (weighted_x / (6.0 * area), weighted_y / (6.0 * area))
```

`clip_polygon_to_bbox` 정의 바로 뒤에 추가한다:

```python
def clip_polygon_to_half_plane(
    points: Sequence[tuple[float, float]],
    origin: tuple[float, float],
    direction: tuple[float, float],
) -> list[tuple[float, float]]:
    """``origin``을 지나 ``direction`` 쪽 반평면으로 polygon을 자른다.

    경계선 위의 점은 포함한다. 결과 꼭짓점이 3개 미만이면 면적 0인
    조각이므로 빈 리스트를 반환한다.
    """

    direction_x, direction_y = direction
    if direction_x == 0.0 and direction_y == 0.0:
        raise ValueError("half plane direction must not be a zero vector")

    origin_x, origin_y = origin

    def offset(point: tuple[float, float]) -> float:
        return (point[0] - origin_x) * direction_x + (point[1] - origin_y) * direction_y

    def inside(point: tuple[float, float]) -> bool:
        return offset(point) >= 0.0

    def intersect(
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> tuple[float, float]:
        first_offset = offset(first)
        span = first_offset - offset(second)
        if span == 0.0:
            return second
        ratio = first_offset / span
        return (
            first[0] + (second[0] - first[0]) * ratio,
            first[1] + (second[1] - first[1]) * ratio,
        )

    clipped = _clip_half_plane(points, inside, intersect)
    return clipped if len(clipped) >= 3 else []
```

- [ ] **Step 4: 테스트가 통과함을 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests/parking/test_geometry.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add hw/jetson/src/parking/geometry.py hw/jetson/tests/parking/test_geometry.py
git commit -m "feat(ai): 폴리곤 중심과 반평면 클리핑 헬퍼 추가 (571)"
```

---

## Task 2: `ZoneRegistry`에 출차 구역 외부측 폴리곤 유도 추가

**Files:**
- Modify: `hw/jetson/src/parking/zone_registry.py` — 심볼: import 목록, `logger`(신규), `ZoneRegistry.__init__`, `ZoneRegistry.exit_outward_polygons`(신규), `_build_exit_outward_polygons`(신규)
- Modify: `hw/jetson/tests/parking/test_zone_registry.py` — 신규 테스트 5개

**Interfaces:**
- Consumes: Task 1의 `polygon_centroid`, `clip_polygon_to_half_plane`
- Produces: `ZoneRegistry.exit_outward_polygons() -> dict[ZoneId, NormalizedPolygon]` — Task 3이 `pipeline.py`에서 호출한다. `EXIT` role 구역만 키로 갖고, 유도 불가한 구역은 키에서 빠진다.

- [ ] **Step 1: 실패하는 테스트 작성**

`hw/jetson/tests/parking/test_zone_registry.py` 맨 끝에 추가한다. 이 파일의 기존 헬퍼(구역 정의를 만드는 함수/상수)를 그대로 재사용하고, 없으면 아래처럼 `ZoneDefinition`을 직접 만든다:

```python
def _aisle_and_exit_registry() -> ZoneRegistry:
    """aisle이 아래쪽, exit이 위쪽인 최소 구성. 외부 방향은 -y다."""

    aisle = ZoneDefinition(
        zone_id=ZoneId(7),
        zone_type=ZoneType.AISLE,
        polygon=((0.0, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
    )
    exit_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
    )
    return ZoneRegistry((aisle, exit_zone))


def test_exit_outward_polygon_is_the_half_away_from_the_aisle() -> None:
    registry = _aisle_and_exit_registry()
    outward = registry.exit_outward_polygons()

    assert set(outward) == {ZoneId(9)}
    piece = outward[ZoneId(9)]
    # exit 구역은 y 0.0~0.4, 중심 y=0.2. aisle이 아래(y 0.5~1.0)이므로
    # 외부 방향은 -y이고 외부측 조각은 y <= 0.2다.
    assert polygon_area(piece) == pytest.approx(0.2)
    assert max(y for _, y in piece) == pytest.approx(0.2)


def test_entry_role_zone_gets_no_outward_polygon() -> None:
    aisle = ZoneDefinition(
        zone_id=ZoneId(7),
        zone_type=ZoneType.AISLE,
        polygon=((0.0, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
    )
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(8),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    assert ZoneRegistry((aisle, entry_zone)).exit_outward_polygons() == {}


def test_registry_without_aisle_yields_no_outward_polygon() -> None:
    """외부 방향을 유도할 수 없으면 통과를 확정하지 않는다(fail-safe)."""

    exit_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
    )
    assert ZoneRegistry((exit_zone,)).exit_outward_polygons() == {}


def test_exit_outward_polygons_are_cached_and_identical_across_calls() -> None:
    registry = _aisle_and_exit_registry()
    assert registry.exit_outward_polygons() == registry.exit_outward_polygons()


@pytest.mark.parametrize(
    "filename",
    ["zone_definition.json", "zone_definition.pilot.json"],
)
def test_deployed_configs_derive_outward_direction_into_upper_right(
    filename: str,
) -> None:
    """배포 설정의 외부 방향이 화면 오른쪽 위(+x, -y)임을 고정한다(571).

    현장 확인으로 차량이 화면 오른쪽 위로 빠져나간다는 것을 검증했다.
    폴리곤이 재작성되어 이 사분면을 벗어나면 판정이 조용히 반대가 되므로
    여기서 잡는다.
    """

    # 이 파일의 기존 테스트와 같은 CWD 독립 경로 관례를 쓴다
    # (`test_loads_tracked_deployment_snapshot` 참고).
    path = Path(__file__).parents[2] / "config" / filename
    registry = ZoneRegistry.from_file(path)
    outward = registry.exit_outward_polygons()
    assert set(outward) == {ZoneId(9)}

    exit_definition = registry.get(ZoneId(9))
    exit_center = polygon_centroid(exit_definition.polygon)
    piece_center = polygon_centroid(outward[ZoneId(9)])
    assert piece_center[0] > exit_center[0]
    assert piece_center[1] < exit_center[1]
```

이 테스트들이 필요로 하는 import를 파일 상단에 추가한다: `Path`(pathlib), `polygon_area`·`polygon_centroid`(`src.parking.geometry`), `EntryExitRole`·`ZoneDefinition`·`ZoneDefinitionVersion`·`ZoneId`·`ZoneType`(`src.parking.models`) 중 아직 없는 것만. 이미 있는 것은 중복 추가하지 않는다.

- [ ] **Step 2: 테스트가 실패함을 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests/parking/test_zone_registry.py -v`
Expected: 신규 5개가 `AttributeError: 'ZoneRegistry' object has no attribute 'exit_outward_polygons'`로 실패. 기존 `test_loads_tracked_deployment_snapshot`은 계속 실패한다(브랜치 시작 전부터의 기존 문제 — 고치지 않는다).

- [ ] **Step 3: 구현**

`hw/jetson/src/parking/zone_registry.py` 상단 import 구역에 `import logging`을 추가하고(표준 라이브러리 블록, 알파벳 순서), `from src.parking.geometry import (...)` 블록에 `clip_polygon_to_half_plane`과 `polygon_centroid`를 추가한다(알파벳 순서). geometry import 블록이 없으면 다른 `from src.parking...` import들과 같은 위치에 새로 만든다.

`IGNORED_ZONE_TYPES_FOR_PARKING` 상수 정의 뒤에 추가한다:

```python
logger = logging.getLogger(__name__)
```

`ZoneRegistry.__init__`의 끝(기존 `self._zones = ...` 대입 뒤)에 캐시 생성을 추가한다:

```python
        self._exit_outward_polygons = self._build_exit_outward_polygons()
```

`all()` 메서드 정의 앞에 두 메서드를 추가한다:

```python
    def exit_outward_polygons(self) -> dict[ZoneId, NormalizedPolygon]:
        """EXIT role 구역별 외부측 sub-polygon을 반환한다(571).

        외부 방향을 유도할 수 없거나 조각 면적이 0인 구역은 키에서 빠진다.
        호출자는 키가 없으면 그 구역으로 통과를 확정하지 않는다.
        """

        return dict(self._exit_outward_polygons)

    def _build_exit_outward_polygons(self) -> dict[ZoneId, NormalizedPolygon]:
        """구역 정의는 불변이므로 구성 시 1회만 계산한다.

        외부 방향은 가장 가까운 AISLE 구역 중심에서 EXIT 구역 중심으로
        향하는 벡터다. 기준선은 EXIT 중심을 지나고 그 방향에 수직인
        직선이며, 외부측 조각은 그 직선의 외부 방향 쪽이다. 새 설정 필드를
        도입하지 않으려고 기존 폴리곤에서 유도한다.
        """

        exits = tuple(
            definition
            for definition in self._definitions
            if definition.zone_type is ZoneType.ENTRY_EXIT
            and definition.entry_exit_role is EntryExitRole.EXIT
        )
        if not exits:
            return {}

        aisles = tuple(
            definition
            for definition in self._definitions
            if definition.zone_type is ZoneType.AISLE
        )
        if not aisles:
            logger.warning(
                "AISLE 구역이 없어 출차 구역 외부 방향을 유도할 수 없습니다. "
                "출차 구역 통과가 확정되지 않습니다: zone_ids=%s",
                [int(definition.zone_id) for definition in exits],
            )
            return {}

        aisle_centers = {
            definition.zone_id: polygon_centroid(definition.polygon)
            for definition in aisles
        }
        outward: dict[ZoneId, NormalizedPolygon] = {}
        for exit_definition in exits:
            exit_center = polygon_centroid(exit_definition.polygon)
            nearest_zone_id = min(
                aisle_centers,
                key=lambda zone_id: (
                    _squared_distance(aisle_centers[zone_id], exit_center),
                    int(zone_id),
                ),
            )
            aisle_center = aisle_centers[nearest_zone_id]
            direction = (
                exit_center[0] - aisle_center[0],
                exit_center[1] - aisle_center[1],
            )
            if direction[0] == 0.0 and direction[1] == 0.0:
                logger.warning(
                    "AISLE과 EXIT 구역의 중심이 같아 외부 방향을 유도할 수 "
                    "없습니다: zone_id=%s",
                    int(exit_definition.zone_id),
                )
                continue
            piece = clip_polygon_to_half_plane(
                exit_definition.polygon,
                exit_center,
                direction,
            )
            if not piece:
                logger.warning(
                    "출차 구역 외부측 조각이 비어 외부측 판정을 할 수 "
                    "없습니다: zone_id=%s",
                    int(exit_definition.zone_id),
                )
                continue
            outward[exit_definition.zone_id] = tuple(piece)
        return outward
```

파일 맨 끝(다른 모듈 수준 private 함수들 옆)에 추가한다:

```python
def _squared_distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2
```

`NormalizedPolygon`이 이 파일에 import되어 있지 않으면 `from src.parking.models import (...)` 블록에 추가한다.

- [ ] **Step 4: 테스트가 통과함을 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests/parking/test_zone_registry.py -v`
Expected: 신규 5개 PASS. `test_loads_tracked_deployment_snapshot`은 여전히 FAIL(기존 문제). 그 외 기존 테스트는 PASS.

- [ ] **Step 5: 커밋**

```bash
git add hw/jetson/src/parking/zone_registry.py hw/jetson/tests/parking/test_zone_registry.py
git commit -m "feat(ai): ZoneRegistry가 출차 구역 외부측 폴리곤을 유도 (571)"
```

---

## Task 3: `ParkingPipeline`에 외부측 접촉 추적과 판정 배선

**Files:**
- Modify: `hw/jetson/src/parking/pipeline.py` — 심볼: import 목록, `ParkingPipeline.__init__`, `ParkingPipeline.process`(차량 루프), `ParkingPipeline.exit_zone_traversal_observed`, `ParkingPipeline.physical_exit`, `ParkingPipeline.checkpoint_state`, `ParkingPipeline.restore_state`, `_outward_contacts`(신규)
- Modify: `hw/jetson/tests/parking/test_pipeline.py` — 심볼: `make_pipeline`의 zone 인자를 쓰는 신규 테스트 7개, 565가 추가한 기존 테스트 일부 수정

**Interfaces:**
- Consumes: Task 2의 `ZoneRegistry.exit_outward_polygons()`
- Produces: 없음(이 태스크로 기능 완성)

565가 추가한 테스트 중 일부는 **의도적으로 동작이 바뀐다** — 내부측만 접촉한 차량이 이제 통과로 인정되지 않는다. 이 태스크는 그 기대값을 새 계약으로 갱신한다.

- [ ] **Step 1: 기존 테스트를 새 계약에 맞게 수정하고 신규 테스트 작성**

`hw/jetson/tests/parking/test_pipeline.py`에서 다음을 수행한다.

**(a) 외부측/내부측 bbox 상수 추가.** `IN_EXIT` 정의 뒤에 추가한다. `EXIT_SPOT`은 x 0.60~0.80, y 0.10~0.30이고, aisle이 없는 테스트 registry에서는 외부측 유도가 안 되므로 이 태스크의 테스트는 AISLE 구역을 함께 넣는다:

```python
AISLE_STRIP = ((0.10, 0.50), (0.90, 0.50), (0.90, 0.95), (0.10, 0.95))
# EXIT_SPOT(y 0.10~0.30)의 중심은 y=0.20이고 aisle이 아래(y 0.50~)이므로
# 외부측은 y <= 0.20 쪽이다.
IN_EXIT_OUTWARD = BoundingBox(0.64, 0.11, 0.72, 0.18)
IN_EXIT_INWARD = BoundingBox(0.64, 0.22, 0.72, 0.29)
```

**(b) AISLE fixture 추가.** `EXIT_ZONE` 정의 뒤에 추가한다:

```python
AISLE_ZONE = zone(7, ZoneType.AISLE, AISLE_STRIP)
```

**(c) 565가 추가한 통과 테스트들에 AISLE을 넣고 bbox를 외부측으로 바꾼다.** 아래 세 테스트에서 `make_pipeline((GENERAL_A, EXIT_ZONE), ...)`을 `make_pipeline((GENERAL_A, AISLE_ZONE, EXIT_ZONE), ...)`으로, `bbox=IN_EXIT`를 `bbox=IN_EXIT_OUTWARD`로 바꾼다:

- `test_open_exit_zone_visit_counts_as_traversal`
- `test_entering_visit_below_confirmation_still_counts_as_traversal`
- `test_traversal_is_no_longer_observed_after_physical_exit`

`test_entry_role_zone_is_not_traversal`은 `make_pipeline((GENERAL_A, AISLE_ZONE, ENTRY_ZONE), ...)`으로 바꾸고 `bbox=IN_EXIT_OUTWARD`를 쓴다. `test_parking_zone_visit_alone_is_not_traversal`과 `test_visit_of_unknown_zone_is_ignored_without_raising`는 그대로 둔다.

**(d) 파일 끝에 신규 테스트를 추가한다:**

```python
def test_inward_side_contact_alone_is_not_traversal() -> None:
    """출차 통로 안쪽에만 있던 차량은 통과로 인정하지 않는다(571).

    565에서는 이 경우도 통과였다 — 이 태스크가 좁히는 지점이다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_INWARD)))
    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_INWARD)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_outward_side_contact_while_stationary_is_traversal() -> None:
    """외부측에 정지해 있어도 통과로 인정한다(571).

    방향 조건을 쓰지 않는다는 결정을 고정한다 — 차단기 앞 정지 중
    추적이 끊겨도 세션이 미결되지 않아야 한다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(
        batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD, motion=MotionSignal.STATIONARY))
    )
    pipeline.process(
        batch(1, snapshot(1, bbox=IN_EXIT_OUTWARD, motion=MotionSignal.STATIONARY))
    )
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_returning_to_inward_side_overwrites_outward_contact() -> None:
    """매 프레임 덮어쓰기 검증(571) — 외부측 접촉이 오래 남지 않는다."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    assert pipeline.exit_zone_traversal_observed(CAR) is True

    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_INWARD)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_unobserved_frames_preserve_the_last_outward_contact() -> None:
    """미관측 프레임은 접촉 상태를 지우지 않는다(571).

    부재 확정까지 5초가 걸리므로, 그동안 값이 유지돼야 판정이 성립한다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    for seconds in (1, 2, 3, 4, 5):
        pipeline.process(batch(seconds, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_degraded_frame_does_not_overwrite_outward_contact() -> None:
    """신뢰할 수 없는 관측은 접촉 상태를 갱신하지 않는다(571)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(
        batch(
            1,
            snapshot(
                1,
                bbox=IN_EXIT_INWARD,
                observation=degraded(last_reliable=0),
            ),
            batch_observation=degraded(last_reliable=0),
        )
    )

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_registry_without_aisle_never_confirms_traversal() -> None:
    """외부 방향을 유도할 수 없으면 통과를 확정하지 않는다(571)."""

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A, EXIT_ZONE), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(1, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_checkpoint_round_trip_preserves_outward_contact() -> None:
    """frame UnitOfWork 롤백이 접촉 상태도 함께 되돌린다(571)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    checkpoint = pipeline.checkpoint_state()

    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_INWARD)))
    assert pipeline.exit_zone_traversal_observed(CAR) is False

    pipeline.restore_state(checkpoint)
    assert pipeline.exit_zone_traversal_observed(CAR) is True
```

- [ ] **Step 2: 테스트가 실패함을 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests/parking/test_pipeline.py -v`
Expected: FAIL — 신규 테스트 다수가 실패한다(아직 외부측 판정이 없어 `test_inward_side_contact_alone_is_not_traversal`이 `True`를 받는 등). `AISLE_ZONE`을 넣어도 판정이 안 바뀌므로 (c)에서 수정한 테스트들은 통과할 수 있다 — 정상이다.

- [ ] **Step 3: 구현**

`hw/jetson/src/parking/pipeline.py`의 `from src.parking.geometry import (...)` 블록에 `overlap_ratio`가 없으면 추가한다(알파벳 순서). `from src.tracking.models import (...)`에 `PhysicalVehicleId`가 이미 있는지 확인하고 없으면 추가한다.

`__init__`의 끝(`self._out_of_zone_min_spot_overlap_ratio = ...` 대입 뒤)에 추가한다:

```python
        # 구역 정의는 불변이라 외부측 조각은 여기서 1회만 계산한다(571).
        self._exit_outward_polygons = zones.exit_outward_polygons()
        # 차량별 "가장 최근 신뢰 관측 프레임에서 접촉한 EXIT 구역" 집합이다.
        # 매 신뢰 프레임마다 덮어쓰므로 오래된 접촉이 남지 않는다.
        self._exit_outward_contacts: dict[PhysicalVehicleId, frozenset[ZoneId]] = {}
```

`checkpoint_state`와 `restore_state`를 교체한다(4-tuple → 5-tuple):

```python
    def checkpoint_state(self) -> tuple[object, object, object, object, object]:
        """frame UnitOfWork 실패 시 복구할 runtime owner state를 반환한다."""

        return (
            self._zone_visit_tracker.checkpoint_state(),
            self._parking_episode_tracker.checkpoint_state(),
            self._incident_reducer.checkpoint_state(),
            self._blocking_relation_tracker.checkpoint_state(),
            dict(self._exit_outward_contacts),
        )

    def restore_state(
        self,
        checkpoint: tuple[object, object, object, object, object],
    ) -> None:
        """DB rollback과 함께 runtime owner를 같은 frame 전 시점으로 되돌린다."""

        if len(checkpoint) != 5:
            raise ValueError("invalid ParkingPipeline checkpoint")
        (
            visit_state,
            episode_state,
            incident_state,
            relation_state,
            outward_contacts,
        ) = checkpoint
        self._zone_visit_tracker.restore_state(visit_state)
        self._parking_episode_tracker.restore_state(episode_state)
        self._incident_reducer.restore_state(incident_state)
        self._blocking_relation_tracker.restore_state(relation_state)
        self._exit_outward_contacts = dict(outward_contacts)
```

`process()`의 차량 루프에서 `observation = _effective_observation(batch, vehicle)` 바로 뒤에 추가한다:

```python
            if observation.state is ObservationState.OBSERVED:
                # degraded/unknown 프레임의 bbox는 공간적으로 신뢰할 수
                # 없으므로 이전 접촉 값을 보존한다(571).
                self._exit_outward_contacts[vehicle.physical_vehicle_id] = (
                    self._outward_contacts(vehicle)
                )
```

`exit_zone_traversal_observed`를 교체한다:

```python
    def exit_zone_traversal_observed(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> bool:
        """마지막 관측에서 출차 구역의 외부측에 도달해 있었는지 반환한다(571).

        미관측 차량의 ZoneVisit은 종료되지 않고 pause만 되므로, 부재가
        확정된 시점에도 마지막 관측 프레임의 방문이 non-terminal로 남아
        있다. 여기에 "그 프레임에서 외부측 조각과 접촉했는가"를 더해,
        출차 통로 안쪽에 정지한 채 가려진 차량을 배제한다.

        ``physical_exit()``이 방문을 종료시키기 **전에** 호출해야 한다 —
        종료 뒤에는 항상 False다. 상태를 변경하지 않는 순수 읽기다.

        motion 방향은 보지 않는다. 차단기 앞에 정지한 차량도 이미 외부측에
        도달해 있으므로 통과로 인정해야 하며, 방향을 요구하면 그 경우가
        미탐이 되어 세션이 영구 미결로 남는다.
        """

        contacts = self._exit_outward_contacts.get(physical_vehicle_id)
        if not contacts:
            return False
        # ``contacts``는 EXIT role 구역 id만 담는다(ZoneRegistry가 그렇게
        # 유도한다). 그래서 role 재확인 없이 교집합만 보면 된다.
        return any(
            visit.zone_id in contacts
            for visit in self._zone_visit_tracker.active_visits(physical_vehicle_id)
        )

    def _outward_contacts(
        self,
        vehicle: PhysicalVehicleSnapshot,
    ) -> frozenset[ZoneId]:
        """이번 프레임에 외부측 조각과 겹친 EXIT 구역 id를 반환한다(571).

        비율 임계값을 두지 않는다 — 차량이 기준선을 물리적으로 넘었다는
        사실만 요구한다.
        """

        return frozenset(
            zone_id
            for zone_id, polygon in self._exit_outward_polygons.items()
            if overlap_ratio(polygon, vehicle.bbox) > 0.0
        )
```

`physical_exit()`의 본문 시작(`observation = ObservationStatus(...)` 대입 앞)에 정리를 추가한다:

```python
        self._exit_outward_contacts.pop(physical_vehicle_id, None)
```

- [ ] **Step 4: 테스트가 통과함을 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests/parking/test_pipeline.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 전체 스위트로 회귀 확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests -q`
Expected: `2 failed, <N> passed` — 실패는 Global Constraints에 적힌 기존 2건뿐이다.

`checkpoint_state()`의 arity가 바뀌었으므로 이 값을 다루는 다른 호출자가 깨질 수 있다. `grep -rn "checkpoint_state\|restore_state" hw/jetson/src hw/jetson/tests`로 전부 확인한다. 값을 그대로 넘기기만 하는 호출자(`frame_observation_workflow`)는 수정이 필요 없지만, arity를 가정하는 곳이 있으면 함께 고친다.

- [ ] **Step 6: 커밋**

```bash
git add hw/jetson/src/parking/pipeline.py hw/jetson/tests/parking/test_pipeline.py
git commit -m "feat(ai): 출차 구역 외부측 도달을 통과 조건으로 요구 (571)"
```

---

## Task 4: 최종 회귀 확인

**Files:** 없음(검증만)

- [ ] **Step 1: 전체 스위트 재확인**

Run: `"C:/kiddo/ssafy/pjt1/hw/jetson/.venv/Scripts/python.exe" -m pytest tests -q`
Expected: 기존 2건 외 실패 없음.

- [ ] **Step 2: 브랜치 상태 확인**

```bash
git log --oneline feature/ai/565-exit-zone-traversal-signal..HEAD
git status
```

Expected: 스펙·계획 커밋과 Task 1·2·3 커밋만 있고 작업 트리가 깨끗함. 이 브랜치는 565 위에 stacked이므로 base가 `develop`이 아니라 565 브랜치다.
