# 출차 구역 통과를 SessionExit 근거로 사용하는 구현 계획 (Jira 565)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 차량이 출차 구역(`ENTRY_EXIT` / `entryExitRole: EXIT`)을 통과한 것이 관측된 부재만 SessionExit으로 백엔드에 발행하고, 통과가 관측되지 않은 부재는 로컬에서만 종료해 오출차를 막는다.

**Architecture:** 미관측 차량의 ZoneVisit은 종료되지 않고 pause만 되므로(`src/parking/pipeline.py:341-356`), 부재 확정 시점에도 마지막 관측 프레임의 방문이 non-terminal로 남아 있다. `ParkingPipeline`에 이 방문을 읽는 순수 읽기 메서드를 추가하고, `PhysicalPresenceWorkflow.plan_departure()`가 `physical_exit()`으로 방문을 종료시키기 **전에** 그것을 읽어 발행 여부와 evidence를 결정한다. 늦은 correlation 경로(`PendingHandoffWorkflow`)는 방문이 이미 종료돼 재계산할 수 없으므로, departure 시점에 PhysicalVehicle의 termination_reason으로 영속한 값을 읽는다.

**Tech Stack:** Python 3.10.12, pytest — `hw/jetson`의 기존 스택과 동일.

## Global Constraints

- 대상 브랜치: `feature/ai/565-exit-zone-traversal-signal` (`origin/develop` 21eadc6 기준으로 이미 생성됨). Jira 565 = 이 브랜치 = 이 MR.
- 스펙: [`docs/superpowers/specs/2026-08-05-exit-zone-traversal-signal-design.md`](../specs/2026-08-05-exit-zone-traversal-signal-design.md) — 구현 중 모호한 점이 있으면 이 문서를 먼저 확인한다.
- **새 임계값을 만들지 않는다.** `ABSENCE_CONFIRMATION_SECONDS`, `ZONE_ENTRY_CONFIRM_SECONDS`, `ZONE_EXIT_CONFIRM_SECONDS`를 읽거나 바꾸지 않는다.
- **마이그레이션을 만들지 않는다.** `physical_exit_evidence` CHECK 제약이 이미 `ENTRY_EXIT_TRAVERSAL`을 허용하고(`src/storage/migrations/0001_initial.sql:118-121`), `physical_vehicles.termination_reason`은 CHECK 없는 자유 TEXT다.
- **Incident 종료 사유와 ContextBinding 종료 사유의 값을 바꾸지 않는다.** Incident 종료 사유는 API 7의 `terminationReason`으로 wire에 노출된다. `SESSION_EXITED`/`PHYSICAL_VEHICLE_LEFT`를 그대로 유지한다.
- 부재 확정 로직(`src/tracking/presence_confirmer.py`)과 ZoneVisit 추적 로직(`src/parking/zone_visit_tracker.py`)은 건드리지 않는다.
- 로컬 수명주기(PhysicalVehicle RETIRED, child scope 종료, ContextBinding 종료)는 통과 여부와 무관하게 현행을 유지한다.
- 테스트 실행은 `hw/jetson`에서 `python -m pytest` (README 관례).

---

## Task 1: `ParkingPipeline.exit_zone_traversal_observed()` 추가

**Files:**
- Modify: `hw/jetson/src/parking/pipeline.py` — 심볼: `from src.parking.models import (...)` import 블록, `ParkingPipeline`에 신규 메서드
- Modify: `hw/jetson/tests/parking/test_pipeline.py` — `zone()` 헬퍼에 파라미터 추가, 신규 fixture, 신규 테스트 6개

**Interfaces:**
- Consumes: 없음(이 태스크가 시작점)
- Produces: `ParkingPipeline.exit_zone_traversal_observed(physical_vehicle_id: PhysicalVehicleId) -> bool` — Task 2가 `physical_presence_workflow.py`에서 호출한다. 위치 인자 하나를 받는 순수 읽기다.

- [ ] **Step 1: 테스트 파일에 fixture와 헬퍼 파라미터 추가**

`hw/jetson/tests/parking/test_pipeline.py`의 import 블록에서 `from src.parking.models import (...)`에 `EntryExitRole`과 `PresenceSignal`을 추가한다(알파벳 순서 유지 — `AssignmentState`, `BlockingRelationState`, `EntryExitRole`, `IncidentState`, `IncidentTransitionType`, `ParkingState`, `ParkingTransitionType`, `PresenceSignal`, `ZoneDefinition`, ... 순):

```python
from src.parking.models import (
    AssignmentState,
    BlockingRelationState,
    EntryExitRole,
    IncidentState,
    IncidentTransitionType,
    ParkingState,
    ParkingTransitionType,
    PresenceSignal,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisitState,
)
```

`SECOND_SPOT` 정의(69-70번째 줄 근처) 바로 아래에 출차 구역용 폴리곤과 bbox를 추가한다. `FIRST_SPOT`(x 0.10~0.30)과 겹치지 않는 좌표라서 주차 구역 방문이 함께 열리지 않는다:

```python
EXIT_SPOT = ((0.60, 0.10), (0.80, 0.10), (0.80, 0.30), (0.60, 0.30))
IN_EXIT = BoundingBox(0.62, 0.12, 0.78, 0.28)
```

`zone()` 헬퍼(77-94번째 줄)에 `entry_exit_role` 키워드 인자를 추가한다:

```python
def zone(
    zone_id: int,
    zone_type: ZoneType,
    polygon=SQUARE,
    *,
    allowed_duration_seconds: float | None = None,
    egress_zone_ids: tuple[ZoneId, ...] = (),
    entry_exit_role: EntryExitRole | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=polygon,
        zone_definition_version=VERSION,
        calibration_reference=CALIBRATION,
        entry_exit_role=entry_exit_role,
        allowed_duration_seconds=allowed_duration_seconds,
        charger_class="FAST" if zone_type is ZoneType.EV_CHARGING else None,
        egress_zone_ids=egress_zone_ids,
    )
```

`GENERAL_B` 정의(104번째 줄 근처) 바로 아래에 두 zone fixture를 추가한다. 둘은 같은 폴리곤을 쓰지만 role이 다르다 — 각 테스트가 서로 다른 pipeline 인스턴스를 만들므로 같은 registry에 함께 들어가지 않는다:

```python
EXIT_ZONE = zone(
    9,
    ZoneType.ENTRY_EXIT,
    EXIT_SPOT,
    entry_exit_role=EntryExitRole.EXIT,
)
ENTRY_ZONE = zone(
    8,
    ZoneType.ENTRY_EXIT,
    EXIT_SPOT,
    entry_exit_role=EntryExitRole.ENTRY,
)
```

- [ ] **Step 2: 실패하는 테스트 6개 작성**

`hw/jetson/tests/parking/test_pipeline.py` 맨 끝(마지막 테스트 뒤)에 추가한다:

```python
def test_open_exit_zone_visit_counts_as_traversal() -> None:
    """마지막으로 관측된 위치가 출차 구역이면 통과로 인정한다(565)."""

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A, EXIT_ZONE), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT)))
    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_entering_visit_below_confirmation_still_counts_as_traversal() -> None:
    """ZONE_ENTRY_CONFIRM_SECONDS를 못 채우고 지나간 차도 통과로 인정한다.

    이게 이 정의의 핵심이다(565) — INSIDE 확정을 요구하면 빨리 나간 차가
    미탐되고, 그 세션은 영구히 닫히지 않는다.
    """

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A, EXIT_ZONE), entry_seconds=10.0)
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT)))
    pipeline.process(batch(1, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_parking_zone_visit_alone_is_not_traversal() -> None:
    pipeline, _, _, _, _ = make_pipeline((GENERAL_A,), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0)))
    pipeline.process(batch(1, snapshot(1)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_entry_role_zone_visit_is_not_traversal() -> None:
    """같은 ENTRY_EXIT 구역이라도 role이 ENTRY면 출차 근거가 아니다(565)."""

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A, ENTRY_ZONE), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT)))
    pipeline.process(batch(1, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_traversal_is_no_longer_observed_after_physical_exit() -> None:
    """읽기 순서 회귀: physical_exit()이 방문을 종료시키면 근거가 사라진다(565)."""

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A, EXIT_ZONE), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT)))
    pipeline.process(batch(1, unobserved=(CAR,)))
    assert pipeline.exit_zone_traversal_observed(CAR) is True

    pipeline.physical_exit(physical_vehicle_id=CAR, observed_at=at(2))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_visit_of_unknown_zone_is_ignored_without_raising() -> None:
    """설정 교체로 사라진 zone의 방문은 예외 없이 통과 미인정으로 처리한다(565).

    이 경로는 departure commit 중에 실행되므로 예외를 던지면 차량 종료
    자체가 실패한다.
    """

    pipeline, visit_tracker, _, _, _ = make_pipeline((GENERAL_A,), entry_seconds=1.0)
    visit_tracker.update(
        physical_vehicle_id=CAR,
        zone_id=ZoneId(999),
        signal=PresenceSignal.PRESENT,
        observation=observed(0),
        observed_at=at(0),
    )

    assert pipeline.exit_zone_traversal_observed(CAR) is False
```

- [ ] **Step 3: 테스트가 실패함을 확인**

Run: `cd hw/jetson && python -m pytest tests/parking/test_pipeline.py -k traversal -v`
Expected: FAIL — `AttributeError: 'ParkingPipeline' object has no attribute 'exit_zone_traversal_observed'`. 위 6개 테스트가 모두 이 이유로 실패해야 정상이다.

- [ ] **Step 4: `pipeline.py`에 메서드 구현**

`hw/jetson/src/parking/pipeline.py`의 `from src.parking.models import (...)` 블록에 `EntryExitRole`과 `ZoneType`을 추가한다(알파벳 순서 유지):

```python
from src.parking.models import (
    BlockingRelation,
    BlockingRelationState,
    EntryExitRole,
    Incident,
    IncidentKeyScope,
    IncidentReduction,
    IncidentTransition,
    ParkingAssignment,
    ParkingEpisode,
    ParkingPipelineResult,
    ParkingState,
    ParkingTransition,
    ParkingTransitionType,
    PresenceSignal,
    ZoneDefinition,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitState,
)
```

`def physical_exit(`(487번째 줄) 바로 **앞에** 새 메서드를 삽입한다:

```python
    def exit_zone_traversal_observed(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> bool:
        """마지막 관측에서 출차 구역 방문이 열려 있었는지 반환한다(565).

        미관측 차량의 ZoneVisit은 종료되지 않고 pause만 되므로(``process()``의
        unobserved 처리 참고), 부재가 확정된 시점에도 마지막 관측 프레임의
        방문이 non-terminal로 남아 있다. 따라서 이 읽기는 "마지막으로 관측된
        위치가 출차 구역이었나"와 같다. 주차 중 출차 구역을 스쳤다가 다른
        위치에서 계속 관측된 차량은 그 방문이 이미 닫혀 있어 False가 된다.

        ``physical_exit()``이 방문을 종료시키기 **전에** 호출해야 한다 —
        종료 뒤에는 항상 False다. 상태를 변경하지 않는 순수 읽기다.
        """

        for visit in self._zone_visit_tracker.active_visits(physical_vehicle_id):
            definition = self._zones.get_or_none(visit.zone_id)
            if definition is None:
                # 설정 교체로 사라진 zone의 방문은 통과 근거로 쓰지 않는다.
                # 이 경로는 departure commit 중에 실행되므로 예외를 던지면
                # 차량 종료 자체가 실패한다.
                continue
            if (
                definition.zone_type is ZoneType.ENTRY_EXIT
                and definition.entry_exit_role is EntryExitRole.EXIT
            ):
                return True
        return False

```

- [ ] **Step 5: 테스트가 통과함을 확인**

Run: `cd hw/jetson && python -m pytest tests/parking/test_pipeline.py -v`
Expected: 전부 PASS (신규 6개 + 기존 테스트 전부).

- [ ] **Step 6: 커밋**

```bash
git add hw/jetson/src/parking/pipeline.py hw/jetson/tests/parking/test_pipeline.py
git commit -m "feat(ai): ParkingPipeline에 출차 구역 통과 관측 읽기 추가 (565)"
```

---

## Task 2: `plan_departure`의 발행 판단과 evidence 교체

**Files:**
- Modify: `hw/jetson/src/application/physical_presence_workflow.py` — 심볼: 모듈 docstring, `import logging`·`logger`, 상수 `ABSENCE_WITHOUT_EXIT_EVIDENCE`, `PhysicalDeparturePlan`, `PhysicalPresenceWorkflow.plan_departure`, `PhysicalPresenceWorkflow.complete_departure`
- Modify: `hw/jetson/tests/application/test_frame_observation_workflow.py` — 심볼: `_ParkingPipeline` stub, 기존 테스트 2개의 evidence 기대값, 신규 테스트 2개

**커버리지 확인** — mirror 유무 × 통과 유무 4조합이 모두 고정된다: mirror+통과는 기존 테스트 2개(747·819번째 줄), mirror+미통과는 신규 테스트 1, mirror 없음+통과는 기존 `test_unbound_departure_retires_locally_without_session_exit`, mirror 없음+미통과는 신규 테스트 2.

**Interfaces:**
- Consumes: Task 1의 `ParkingPipeline.exit_zone_traversal_observed(physical_vehicle_id)`
- Produces: `PhysicalDeparturePlan.vehicle_termination_reason: str` (신규 필드) 와 모듈 상수 `ABSENCE_WITHOUT_EXIT_EVIDENCE = "ABSENCE_WITHOUT_EXIT_EVIDENCE"` — Task 3이 `pending_handoff_workflow.py`에서 이 상수를 import해 `vehicle.termination_reason`과 비교한다.

- [ ] **Step 1: 테스트 stub에 새 메서드를 추가하고 기대값을 새 계약으로 바꾼다**

`hw/jetson/tests/application/test_frame_observation_workflow.py`의 `_ParkingPipeline` stub(144번째 줄)에서 `__init__`에 통과 여부를 제어하는 플래그를 추가하고, `physical_exit` 정의(178번째 줄) 앞에 새 메서드를 추가한다.

`__init__`의 `self.exit_reasons: list[str] = []` 다음 줄에 추가:

```python
        self.exit_zone_traversal = True
```

`def physical_exit(` 바로 앞에 추가:

```python
    def exit_zone_traversal_observed(self, physical_vehicle_id) -> bool:
        assert physical_vehicle_id == VEHICLE_ID
        return self.exit_zone_traversal

```

같은 파일 747번째 줄과 819번째 줄의 다음 단정을 교체한다(두 곳 모두 동일한 문장이다 — 통과가 관측된 정상 출차이므로 evidence가 바뀐다):

```python
        assert mirror.physical_exit_evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
```

- [ ] **Step 2: 통과가 없을 때의 동작을 고정하는 테스트 2개 추가**

같은 파일의 `test_unbound_departure_retires_locally_without_session_exit`(906번째 줄 근처) **바로 뒤에** 두 테스트를 추가한다. 준비는 이 파일에 이미 있는 헬퍼(`_seed_bound_departure`, `_SessionWorkflow`, `_ParkingPipeline`, `_PublicationPreparer`, `_workflow`, `_batch`, `_outbox_count`, `_confirmed_absent_vehicle`)를 그대로 쓴다 — 새 헬퍼를 만들지 않는다:

```python
def test_bound_absence_without_exit_zone_traversal_does_not_publish_session_exit(
    tmp_path: Path,
) -> None:
    """출차 구역 통과가 관측되지 않은 부재는 백엔드에 발행하지 않는다(565).

    로컬 수명주기는 그대로 닫는다 — 부재 확정 사실은 forget ACK까지 매
    프레임 반복되므로 소비하지 않으면 무한 반복이고, BOUND binding을 남기면
    RETIRE 자체가 UnfinishedPhysicalVehicleScopeError로 실패한다.
    """

    connection = open_database(tmp_path / "departure-no-evidence.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    parking.exit_zone_traversal = False
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        _seed_bound_departure(connection)

        result = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        binding = ContextBindingRepository(connection).get(BINDING_ID)
        mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)

        # 로컬 수명주기는 현행 그대로 닫힌다.
        assert result.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert binding.state is ContextBindingState.ENDED
        # Incident 종료 사유(API 7 wire 노출)는 바뀌지 않는다.
        assert parking.exit_reasons == [SESSION_EXITED]
        # 진단용 차량 종료 사유만 구분된다.
        assert vehicle.termination_reason == ABSENCE_WITHOUT_EXIT_EVIDENCE
        # 백엔드로는 아무것도 나가지 않고 mirror는 손대지 않는다.
        assert _outbox_count(connection) == 0
        assert mirror.physical_presence_state is PhysicalPresenceState.INSIDE
        assert mirror.physical_termination_origin is None
        assert mirror.physical_exit_evidence is None
        assert mirror.exited_at is None
        assert mirror.publication_revision == 0
    finally:
        connection.close()


def test_unbound_absence_without_exit_zone_traversal_records_absence_reason(
    tmp_path: Path,
) -> None:
    """session이 없는 차량도 통과 여부를 평가해 사유로 남긴다(565).

    나중에 세션이 늦게 붙을 수 있으므로, 늦은 correlation이 읽을 수 있도록
    mirror 유무와 무관하게 사유를 영속한다.
    """

    connection = open_database(tmp_path / "unbound-no-evidence.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    parking.exit_zone_traversal = False
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _confirmed_absent_vehicle()
            )

        result = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        assert result.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert vehicle.termination_reason == ABSENCE_WITHOUT_EXIT_EVIDENCE
        # Incident 종료 사유는 현행 값을 유지한다.
        assert parking.exit_reasons == [PHYSICAL_VEHICLE_LEFT]
        assert _outbox_count(connection) == 0
    finally:
        connection.close()
```

import에 `ABSENCE_WITHOUT_EXIT_EVIDENCE`를 추가한다 — 이 파일이 `SESSION_EXITED`와 `PHYSICAL_VEHICLE_LEFT`를 이미 import하는 곳에 함께 넣는다.

- [ ] **Step 3: 테스트가 실패함을 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_frame_observation_workflow.py -v`
Expected: FAIL — 신규 테스트는 `ImportError: cannot import name 'ABSENCE_WITHOUT_EXIT_EVIDENCE'`, evidence를 바꾼 기존 테스트 2개는 `AssertionError`로 실패한다.

- [ ] **Step 4: 모듈 docstring과 상수·logger 추가**

`hw/jetson/src/application/physical_presence_workflow.py`의 모듈 docstring(파일 맨 위)을 교체한다:

```python
"""NOT_PRESENT_CONFIRMED를 하나의 durable 물리 종료로 조립한다.

이 workflow는 tracking timeout을 출차로 바꾸지 않는다. TrackingBatch가
정상 전체 관측으로 확정한 ``NOT_PRESENT_CONFIRMED``만 받아
session correlation을 고정하고 child scope를 종료한다. 모든 변경은
상위 frame UnitOfWork에 참여하며, TrackingPipeline ACK는 commit 뒤에만
호출되어야 한다.

부재 확정을 곧 출차로 발행하지는 않는다(565). 단일 카메라에서 "전체 영역"은
카메라 화각이므로, 주차장 안에 있으면서 화각만 벗어난 차량과 실제로 나간
차량을 부재만으로 구분할 수 없다. 그래서 출차 구역(``ENTRY_EXIT`` /
``EXIT``) 통과가 관측된 부재만 SessionExit으로 발행하고, 통과가 관측되지
않은 부재는 로컬 수명주기만 닫는다. 후자의 session은 Jetson이 닫지 않으므로
행정 종료가 필요하며, 진단을 위해 PhysicalVehicle의 termination_reason에
``ABSENCE_WITHOUT_EXIT_EVIDENCE``를 남긴다.
"""
```

`from __future__ import annotations` 아래 import 구역에 `import logging`을 추가한다(기존 `import sqlite3`과 같은 블록, 알파벳 순서로 `logging`이 `sqlite3`보다 앞).

`PHYSICAL_VEHICLE_LEFT = "PHYSICAL_VEHICLE_LEFT"`(39번째 줄) 다음에 상수와 logger를 추가한다:

```python
ABSENCE_WITHOUT_EXIT_EVIDENCE = "ABSENCE_WITHOUT_EXIT_EVIDENCE"

logger = logging.getLogger(__name__)
```

- [ ] **Step 5: `PhysicalDeparturePlan`에 필드 추가**

같은 파일의 `PhysicalDeparturePlan`(62-70번째 줄)을 교체한다:

```python
@dataclass(frozen=True, kw_only=True)
class PhysicalDeparturePlan:
    """child 저장 후 PhysicalVehicle RETIRED를 검증할 종료 plan."""

    physical_vehicle_id: PhysicalVehicleId
    parking_result: ParkingPipelineResult
    session_exit_transition: SessionExitTransition | None
    termination_reason: str
    vehicle_termination_reason: str
    already_terminal: bool = False
```

`termination_reason`은 Incident 종료 사유와 ContextBinding 종료 사유로 쓰이며 Incident 종료 사유는 API 7의 wire에 노출된다 — 값을 바꾸지 않는다. `vehicle_termination_reason`은 PhysicalVehicle 종료 사유 전용이며 출차 구역 통과 여부를 담는다.

- [ ] **Step 6: `plan_departure`에 통과 판정 배선**

같은 파일 `plan_departure`의 early-terminal 분기(100-112번째 줄)에서 `PhysicalDeparturePlan` 생성에 새 필드를 추가한다. 이미 종료된 차량은 저장된 사유를 그대로 재사용한다:

```python
        if vehicle.state in {
            PhysicalVehicleState.RETIRED,
            PhysicalVehicleState.CANCELED,
        }:
            existing_reason = vehicle.termination_reason or PHYSICAL_VEHICLE_LEFT
            return PhysicalDeparturePlan(
                physical_vehicle_id=physical_vehicle_id,
                parking_result=_empty_parking_result(),
                session_exit_transition=None,
                termination_reason=existing_reason,
                vehicle_termination_reason=existing_reason,
                already_terminal=True,
            )
```

같은 메서드의 `termination_reason = (...)` 블록(146-153번째 줄)을 교체한다. 통과 판정은 `physical_exit()`이 방문을 종료시키기 전에 읽어야 하고, mirror 유무와 무관하게 항상 평가한다 — mirror가 없는 차량도 나중에 세션이 늦게 붙을 수 있기 때문이다:

```python
        traversal_observed = self._parking_pipeline.exit_zone_traversal_observed(
            physical_vehicle_id
        )
        termination_reason = (
            SESSION_EXITED if mirror is not None else PHYSICAL_VEHICLE_LEFT
        )
        vehicle_termination_reason = (
            termination_reason
            if traversal_observed
            else ABSENCE_WITHOUT_EXIT_EVIDENCE
        )
        if not traversal_observed:
            logger.warning(
                "부재가 확정됐지만 출차 구역 통과가 관측되지 않아 SessionExit을 "
                "발행하지 않습니다: physical_vehicle_id=%s session_id=%s "
                "absence_confirmed_at=%s",
                physical_vehicle_id,
                None if mirror is None else mirror.parking_session_id,
                occurred_at,
            )
        parking_result = self._parking_pipeline.physical_exit(
            physical_vehicle_id=physical_vehicle_id,
            observed_at=occurred_at,
            incident_termination_reason=termination_reason,
        )
```

- [ ] **Step 7: mirror 갱신과 발행을 통과 여부로 가드**

같은 메서드의 `session_exit: SessionExitTransition | None = None` 블록(170-200번째 줄)에서 조건에 `traversal_observed`를 더하고 evidence를 교체한다. `if mirror is not None:`을 다음으로 교체한다:

```python
        session_exit: SessionExitTransition | None = None
        if mirror is not None and traversal_observed:
            if mirror.physical_vehicle_id != physical_vehicle_id:
                raise RuntimeError(
                    "exit correlation references another PhysicalVehicle"
                )
            exited_mirror = replace(
                mirror,
                physical_presence_state=PhysicalPresenceState.EXITED,
                physical_observation=vehicle.observation,
                physical_termination_origin=(
                    PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
                ),
                physical_exit_evidence=PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL,
                exited_at=occurred_at,
                record_version=mirror.record_version + 1,
                publication_revision=mirror.publication_revision + 1,
                updated_at=max(occurred_at, mirror.updated_at),
            )
            mirror_repository.save(
                exited_mirror,
                expected_record_version=mirror.record_version,
            )
            session_exit = SessionExitTransition(
                parking_session_id=mirror.parking_session_id,
                physical_vehicle_id=physical_vehicle_id,
                publication_revision=exited_mirror.publication_revision,
                occurred_at=occurred_at,
                origin=PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED,
                evidence=PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL,
            )
```

통과가 없으면 mirror를 전혀 건드리지 않는다. `physical_presence_state <> 'EXITED'`일 때 `physical_termination_origin`/`physical_exit_evidence`/`exited_at_us`가 모두 NULL이어야 하는 CHECK(`src/storage/migrations/0001_initial.sql:134-144`)를 그대로 만족한다.

같은 메서드 끝의 `return PhysicalDeparturePlan(...)`(202-207번째 줄)에 새 필드를 추가한다:

```python
        return PhysicalDeparturePlan(
            physical_vehicle_id=physical_vehicle_id,
            parking_result=parking_result,
            session_exit_transition=session_exit,
            termination_reason=termination_reason,
            vehicle_termination_reason=vehicle_termination_reason,
        )
```

- [ ] **Step 8: `complete_departure`가 새 필드를 쓰게 한다**

같은 파일 `complete_departure`의 `retired = replace(...)`(244-251번째 줄)에서 `termination_reason=plan.termination_reason`을 교체한다:

```python
        retired = replace(
            vehicle,
            state=PhysicalVehicleState.RETIRED,
            record_version=vehicle.record_version + 1,
            terminated_at=occurred_at,
            termination_reason=plan.vehicle_termination_reason,
            updated_at=max(vehicle.updated_at, occurred_at),
        )
```

- [ ] **Step 9: 테스트가 통과함을 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_frame_observation_workflow.py -v`
Expected: 전부 PASS.

- [ ] **Step 10: 커밋**

```bash
git add hw/jetson/src/application/physical_presence_workflow.py hw/jetson/tests/application/test_frame_observation_workflow.py
git commit -m "feat(ai): 출차 구역 통과가 관측된 부재만 SessionExit으로 발행 (565)"
```

---

## Task 3: 늦은 correlation 경로에 같은 규칙 적용

**Files:**
- Modify: `hw/jetson/src/application/pending_handoff_workflow.py` — 심볼: `from src.application.physical_presence_workflow import ...` import, `correlate_historical_sessions`의 RETIRED 분기(226-255번째 줄)
- Modify: `hw/jetson/tests/application/test_pending_handoff_workflow.py` — 심볼: `_retired_vehicle` 헬퍼, `test_late_allow_after_retirement_creates_historical_exit_without_binding`, 신규 테스트 1개

**Interfaces:**
- Consumes: Task 2의 `ABSENCE_WITHOUT_EXIT_EVIDENCE` 상수 (`src/application/physical_presence_workflow.py`)
- Produces: 없음(이 태스크로 기능 완성)

- [ ] **Step 1: 실패하는 테스트 작성 + 기존 테스트 기대값 갱신**

`hw/jetson/tests/application/test_pending_handoff_workflow.py`의 `_retired_vehicle` 헬퍼(133-147번째 줄)에 사유를 파라미터로 뺀다. 기본값은 기존 값을 유지해 다른 테스트가 영향받지 않는다:

```python
def _retired_vehicle(
    termination_reason: str = "PHYSICAL_VEHICLE_LEFT",
) -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.RETIRED,
        observation=ABSENT,
        absence_trusted_seconds=5.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        absence_confirmed_at=T1,
        terminated_at=T1,
        termination_reason=termination_reason,
        record_version=2,
        created_at=T0,
        updated_at=T1,
    )
```

`test_late_allow_after_retirement_creates_historical_exit_without_binding`의 469번째 줄 단정을 교체한다:

```python
        assert session_exit.evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
```

같은 테스트 함수 바로 뒤에 신규 테스트를 추가한다:

```python
def test_late_allow_after_absence_without_exit_evidence_creates_no_exit(
    tmp_path: Path,
) -> None:
    """출차 근거 없이 종료된 차량은 늦은 correlation에서도 출차로 만들지 않는다(565).

    이 경로에서는 통과 여부를 재계산할 수 없다 — 차량이 이미 RETIRED이고
    ZoneVisit도 함께 종료됐다. 그래서 departure 시점에 termination_reason으로
    영속한 값을 읽는다.
    """

    connection = open_database(tmp_path / "historical-no-evidence.db")
    workflow = PendingHandoffWorkflow()
    attempt = _matched_allow_attempt()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _retired_vehicle(
                    termination_reason=ABSENCE_WITHOUT_EXIT_EVIDENCE,
                )
            )
            EntryMatchAttemptRepository(connection).add(attempt)
            result = workflow.correlate_historical_sessions(
                (attempt,),
                observed_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        assert result.session_exit_transitions == ()
        # 확인할 수 없는 출차 상태를 만들어 두지 않는다.
        assert ParkingSessionMirrorRepository(connection).get(SESSION_ID) is None
    finally:
        connection.close()
```

import에 `ABSENCE_WITHOUT_EXIT_EVIDENCE`를 추가한다 — 이 파일이 `src.application.physical_presence_workflow`에서 이미 무언가를 import하고 있으면 거기에 함께 넣고, 없으면 새 import 줄을 추가한다.

- [ ] **Step 2: 테스트가 실패함을 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_pending_handoff_workflow.py -v`
Expected: FAIL — 신규 테스트는 `result.session_exit_transitions == ()` 단정에서 실패하고(현재는 사유와 무관하게 SessionExit을 만든다), evidence를 바꾼 기존 테스트는 `AssertionError`로 실패한다.

- [ ] **Step 3: `pending_handoff_workflow.py` 수정**

`hw/jetson/src/application/pending_handoff_workflow.py`의 `from src.application.physical_presence_workflow import SessionExitTransition`(23번째 줄)을 교체한다:

```python
from src.application.physical_presence_workflow import (
    ABSENCE_WITHOUT_EXIT_EVIDENCE,
    SessionExitTransition,
)
```

`correlate_historical_sessions`의 RETIRED 분기(226-255번째 줄)를 교체한다. 사유 확인을 mirror 갱신보다 **앞에** 둬서, 통과 근거가 없는 차량은 mirror를 만들지도 갱신하지도 않는다:

```python
            if vehicle.state is PhysicalVehicleState.RETIRED:
                if vehicle.terminated_at is None:
                    raise RuntimeError("RETIRED PhysicalVehicle lost terminated_at")
                if (
                    mirror is not None
                    and mirror.physical_presence_state
                    is PhysicalPresenceState.EXITED
                ):
                    continue
                if vehicle.termination_reason == ABSENCE_WITHOUT_EXIT_EVIDENCE:
                    # 출차 구역 통과가 관측되지 않은 부재는 출차가 아니다(565).
                    # 이 시점에는 ZoneVisit이 이미 종료돼 재계산할 수 없으므로
                    # departure가 영속한 사유를 그대로 신뢰한다. 확인할 수 없는
                    # 출차 상태를 mirror에 만들어 두지 않는다.
                    continue
                updated = self._historical_mirror(
                    attempt=attempt,
                    vehicle=vehicle,
                    mirror=mirror,
                    presence_state=PhysicalPresenceState.EXITED,
                    updated_at=observed_at,
                )
                self._save_mirror(mirror_repository, mirror, updated)
                exits.append(
                    SessionExitTransition(
                        parking_session_id=session_id,
                        physical_vehicle_id=physical_vehicle_id,
                        publication_revision=updated.publication_revision,
                        occurred_at=vehicle.terminated_at,
                        origin=(
                            PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
                        ),
                        evidence=PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL,
                    )
                )
                continue
```

- [ ] **Step 4: 테스트가 통과함을 확인**

Run: `cd hw/jetson && python -m pytest tests/application/test_pending_handoff_workflow.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add hw/jetson/src/application/pending_handoff_workflow.py hw/jetson/tests/application/test_pending_handoff_workflow.py
git commit -m "feat(ai): 늦은 correlation 경로도 출차 구역 통과를 요구 (565)"
```

---

## Task 4: 전체 회귀와 계약 문서 수정

**Files:**
- Modify: `docs/HW API 정리.md` — 심볼: API 10(SessionExit)의 `evidence` 설명 문장과 계약 목록
- 검증 대상: `hw/jetson/tests` 전체

**Interfaces:**
- Consumes: Task 1·2·3의 완성된 동작
- Produces: 없음

- [ ] **Step 1: 전체 jetson 테스트 스위트로 회귀 확인**

Run: `cd hw/jetson && python -m pytest tests -v`
Expected: 전부 PASS, 스킵/에러 없음.

실패가 있으면 대부분 `FULL_AREA_ABSENCE`를 기대하던 테스트다. 다음 명령으로 남은 곳을 전부 찾는다:

```bash
grep -rn "FULL_AREA_ABSENCE" hw/jetson/tests hw/jetson/src
```

**주의**: `FULL_AREA_ABSENCE`를 쓰는 모든 곳을 바꾸면 안 된다. enum 값과 DB CHECK 제약은 그대로 남기고, **workflow가 생산하는 evidence를 단정하는 곳만** 바꾼다. 단순히 fixture로 임의의 evidence 값을 만들어 직렬화를 검증하는 테스트(`tests/domain/test_models.py`, `tests/replay/test_publication_preparer.py`, `tests/communication/test_backend_publication_preparer.py`, `tests/storage/test_session_frame_repositories.py`)는 손대지 않는다.

- [ ] **Step 2: 계약 문서의 evidence 설명 교체**

`docs/HW API 정리.md`의 API 10(SessionExit) 절에서 다음 문장을 찾는다:

> `evidence`는 현재 `ENTRY_EXIT_TRAVERSAL` 또는 `FULL_AREA_ABSENCE`다. 현행 한-camera 파일럿은 정상 전체 영역 관측으로 확정한 `FULL_AREA_ABSENCE`를 사용한다.

다음으로 교체한다:

```markdown
`evidence`는 현재 `ENTRY_EXIT_TRAVERSAL` 또는 `FULL_AREA_ABSENCE`다. 현행 한-camera
파일럿은 출차 구역 통과가 관측된 부재만 발행하므로 `ENTRY_EXIT_TRAVERSAL`만 사용한다.
`FULL_AREA_ABSENCE`는 계약에 남아 있지만 현재 구현이 생산하지 않는다.
```

같은 절의 `### 계약` 목록에 다음 두 항목을 추가한다:

```markdown
- Jetson은 출차 구역(`ENTRY_EXIT` / `EXIT`) 통과가 관측된 부재만 SessionExit으로 발행한다.
- 통과가 관측되지 않은 부재는 Jetson 로컬에서만 종료되고 Backend에 발행되지 않는다.
해당 session은 Jetson이 닫지 않으므로 행정 종료가 필요하다.
```

- [ ] **Step 3: `evidence` 요청 예시도 함께 맞춘다**

같은 절의 request 예시 JSON에서 `"evidence": "FULL_AREA_ABSENCE"`를 `"evidence": "ENTRY_EXIT_TRAVERSAL"`로 바꾼다.

- [ ] **Step 4: 브랜치 상태 확인**

```bash
git log --oneline origin/develop..HEAD
git status
```

Expected: 설계 문서 커밋 2개 + 이 계획 커밋 + Task 1·2·3 커밋 3개만 있고 작업 트리가 깨끗함.

- [ ] **Step 5: 커밋**

```bash
git add "docs/HW API 정리.md"
git commit -m "docs(ai): SessionExit evidence 계약을 출차 구역 통과 기준으로 갱신 (565)"
```

---

## 이 계획에 없는 것 (스펙의 §비범위와 동일)

- **폴리곤 상단 여백 문제**: 출차 구역과 프레임 경계 사이에서 마지막 관측이 끊기면 통과가 잡히지 않는다. 파일럿 영상으로 실제 이탈 궤적을 확인한 뒤 별도 태스크로 폴리곤을 조정한다(설정 변경, 로직 변경 아님).
- **end-to-end 발행 검증**: `HW_API_KEY`가 비어 있으면 outbox 워커가 생성되지 않고(`src/main.py`), 검증 스크립트에는 `BackendClient`가 없다. 실제 백엔드와 붙여 확인하는 것은 별도 태스크다.
- **출차 근거 없는 부재를 백엔드에 알리는 경로**: 새 API가 필요하고 계약 협의 대상이다.
