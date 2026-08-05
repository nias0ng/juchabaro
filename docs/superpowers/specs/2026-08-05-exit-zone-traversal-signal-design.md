# 출차 구역 통과를 SessionExit 근거로 사용하는 설계 (Jira 565)

## 배경

백엔드가 출차 정보를 필요로 한다는 요구가 나와, 현재 Jetson이 출차를 어떻게 판정하고 실제로 무엇을 보내는지 확인했다. 확인 결과는 다음과 같다.

**판정 로직**: `PhysicalVehiclePresenceConfirmer`(`hw/jetson/src/tracking/presence_confirmer.py`)가 차량별 부재 시간을 누적하고, `ABSENCE_CONFIRMATION_SECONDS`(현재 5.0초, `.env.example:53`)를 넘으면 `absence_confirmed_at`을 확정한다. 누적 조건은 엄격하다 — `trusted_full_area_sample`(전체 영역 정상 관측 + 모든 detection에 tracker ID)인 프레임에서만 더하고, 프레임 간격이 `TRUSTED_SAMPLE_MAX_GAP_SECONDS`를 넘으면 그 구간은 더하지 않는다. tracker 소실과 process 재시작은 출차 근거가 아니다.

**발행 경로**: 확정되면 `PhysicalPresenceWorkflow.plan_departure()`가 세션 미러를 찾아 `SessionExitTransition`을 만들고, outbox를 거쳐 `POST /api/hw/parking/exit`로 발행된다(`src/communication/backend_client.py`). 백엔드에도 수신 endpoint가 이미 있다(`backend/.../hw/controller/HwController.java`).

**문제**: 출차 근거가 `FULL_AREA_ABSENCE` 하나로 하드코딩돼 있다(`src/application/physical_presence_workflow.py:183`, `:199`). 단일 카메라 파일럿에서 "전체 영역"은 곧 카메라 화각이므로, 차가 주차장 안에 있으면서 화각만 벗어나면(출구 통로, 기둥 가림) 5초 뒤 출차로 확정된다. 오출차가 나면 백엔드 세션이 조기 종료되고, 그 차는 재입차 없이 다시 correlate되지 않으며, 되돌리는 API도 계약에 없다.

**기회**: 출차 구역이 이미 폴리곤으로 정의돼 있다 — `config/zone_definition.json`과 `config/zone_definition.pilot.json` 둘 다 zone 9 = `ENTRY_EXIT` / `entryExitRole: EXIT`이다. 그런데 `EntryExitRole.EXIT`를 소비하는 판정 코드가 하나도 없다. `ENTRY`만 입차 OCR 매칭에 쓰이고(`src/session/entry_match_coordinator.py:75-76`), `EXIT`은 파싱·검증과 오버레이 색칠까지만 된다. 계약에도 자리가 이미 예약돼 있다 — `PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL`(`src/session/models.py:76`)이 enum과 DB CHECK 제약(`src/storage/migrations/0001_initial.sql:118-121`)에 있는데 아무도 이 값을 생산하지 않는다.

즉 원래 설계자가 비워둔 자리를 채우는 작업이다.

## 범위

- 대상: `PhysicalPresenceWorkflow.plan_departure()`의 SessionExit 발행 판단과 근거(evidence) 결정.
- 부재 확정 자체(`PhysicalVehiclePresenceConfirmer`, `ABSENCE_CONFIRMATION_SECONDS`)는 건드리지 않는다. 언제 "안 보인다"고 확정하는지는 그대로 두고, 그 확정을 **출차로 인정할지**만 판단한다.
- ZoneVisit 추적 로직과 `ZONE_ENTRY_CONFIRM_SECONDS`/`ZONE_EXIT_CONFIRM_SECONDS`도 건드리지 않는다.
- 주차 구역 이탈(unpark, `PARKED → ENDED`) 판정은 별개 작업이다(Jira 534). 이 스펙은 주차장 이탈만 다룬다.

## 결정: 통과가 없으면 출차로 확정하지 않는다

부재가 확정됐지만 출차 구역을 지난 적이 없는 차량은 **SessionExit을 발행하지 않는다.** 세 가지 안을 검토했다.

- **A. 확정하지 않는다** — 오출차 방어가 가장 강하다. 대가는 세션이 닫히지 않는 것이다. **채택.**
- B. 발행하되 근거 강도로 구분해 백엔드 정책에 넘긴다 — wire 변경이 없지만 오출차가 백엔드까지 도달한다.
- C. 근거 강도에 따라 부재 확정 시간을 차등한다 — 새 임계값이 필요하고 오출차를 늦추기만 한다.

A를 채택한 이유는 오출차의 결과가 되돌릴 수 없기 때문이다(세션 조기 종료 + 재correlate 불가 + 복구 API 없음). A의 실패 모드(세션 미결)는 관리자 수동 종료로 해소할 수 있는 반면, 오출차는 해소 경로가 없다.

## 결정: "통과했다"의 정의

**부재 누적이 시작된 마지막 관측 프레임에 그 차량의 출차 구역 방문이 열려 있었으면 통과로 인정한다.**

이 정의를 고른 이유:

- **새 임계값이 없다.** "최근 N초 안에 방문 기록" 같은 정의는 N을 새로 정해야 한다.
- **빠르게 지나간 차도 잡힌다.** 출차 구역은 프레임 폭의 15%(x 0.56~0.71)여서 통과 체류가 `ZONE_ENTRY_CONFIRM_SECONDS`(1.0초, `.env.example:37`)에 걸치느냐 마느냐가 경계다. 방문이 `INSIDE`까지 확정되기를 요구하면 빨리 나간 차가 미탐되고, A 규칙상 그 세션은 영구 미결이 된다. 이 정의는 `ENTERING` 상태만으로도 통과로 인정한다.
- **주차 중 스친 경우는 자동 배제된다.** 조종하다 출차 구역을 살짝 밟은 차는 그 뒤 다른 위치에서 계속 관측되므로, 부재가 시작되는 시점에는 그 방문이 이미 닫혀 있다.

이 정의가 읽기만으로 구현되는 이유는 미관측 차량의 ZoneVisit이 **종료되지 않고 pause만 되기** 때문이다(`src/parking/pipeline.py:341-356`, 주석에 의도가 명시돼 있음). 실제 종료는 `ParkingPipeline.physical_exit()`(`:487`)가 `ZoneVisitTracker.physical_exit()`을 호출할 때 일어난다(`:506`). 그래서 `plan_departure` 시점에는 마지막 관측 프레임의 방문이 아직 non-terminal이고, `ZoneVisitTracker.active_visits()`가 그대로 반환한다(`src/parking/zone_visit_tracker.py:239-246`). 그 구현이 쓰는 `_NON_TERMINAL_STATES`에 `ENTERING`이 포함돼 있어(`:40-44`) 위 세 번째 항목이 성립한다.

**남는 구멍**: 출차 구역을 지난 뒤 그 위쪽 여백(폴리곤 상단 y 0.08과 프레임 경계 사이)에서 마지막으로 관측되면 통과로 잡히지 않는다. 이건 로직을 느슨하게 하는 대신 폴리곤을 프레임 상단까지 늘려 해결한다 — 파일럿 영상에서 실제 이탈 궤적이 어디서 끊기는지 확인한 뒤 판단한다(§후속 참고).

## 변경 사항

### 1. `ParkingPipeline`에 순수 읽기 메서드 추가

```python
def exit_zone_traversal_observed(self, physical_vehicle_id: PhysicalVehicleId) -> bool:
    """이 차량이 마지막 관측에서 출차 구역 방문을 열어둔 채였는지 반환한다."""
```

`self._zone_visit_tracker.active_visits(physical_vehicle_id)`의 각 방문에 대해 `self._zones.get_or_none(visit.zone_id)`로 zone 정의를 조회하고, `zone_type is ZoneType.ENTRY_EXIT and entry_exit_role is EntryExitRole.EXIT`인 것이 하나라도 있으면 `True`.

`get()`이 아니라 `get_or_none()`을 쓴다(`src/parking/zone_registry.py:234`, `:242`). ZoneVisit은 생성 당시의 `zone_definition_version`을 들고 있어서, 설정이 교체된 뒤 그 zone이 사라졌을 수 있다. 이 경로는 departure commit 중에 실행되므로 예외를 던지면 종료 자체가 실패한다. 정의를 못 찾은 방문은 통과 근거로 인정하지 않고 넘긴다.

새 지오메트리 계산, 새 임계값, 새 영속 필드가 없다. 상태를 변경하지 않는 순수 읽기다.

**순서 의존**: 이 메서드는 `physical_exit()`이 방문을 종료시키기 **전에** 호출해야 한다. docstring에 명시하고, 종료 후 호출하면 `False`가 되는 것을 고정하는 회귀 테스트를 둔다.

### 2. `plan_departure`의 발행 판단 확장

`src/application/physical_presence_workflow.py:149`의 `physical_exit()` 호출보다 앞에서 통과 여부를 읽고, mirror 처리 분기에 반영한다.

| mirror | 출차 구역 통과 | 동작 |
|---|---|---|
| 있음 | 있음 | SessionExit 발행. `evidence=ENTRY_EXIT_TRAVERSAL`, mirror `physical_presence_state=EXITED`, `termination_reason=SESSION_EXITED` |
| 있음 | 없음 | **발행하지 않는다.** mirror를 갱신하지 않는다. `termination_reason=ABSENCE_WITHOUT_EXIT_EVIDENCE` |
| 없음 | 무관 | 현행 유지 (`PHYSICAL_VEHICLE_LEFT`, 로컬 종료만) |

`PhysicalExitEvidence.FULL_AREA_ABSENCE` 하드코딩(`:183`, `:199`)이 `ENTRY_EXIT_TRAVERSAL`로 교체된다. `physical_exit_evidence` CHECK 제약이 이미 두 값을 모두 허용하므로 **마이그레이션이 없다**(`0001_initial.sql:118-121`).

통과가 없는 경우 mirror를 전혀 건드리지 않는 것이 스키마상 적법하다 — `physical_presence_state <> 'EXITED'`일 때 `physical_termination_origin`/`physical_exit_evidence`/`exited_at_us`가 모두 NULL이어야 하는 CHECK(`0001_initial.sql:134-144`)를 그대로 만족한다.

`ABSENCE_WITHOUT_EXIT_EVIDENCE`는 `physical_vehicles.termination_reason`에 기록된다. 이 컬럼은 CHECK 제약이 없는 자유 TEXT라 마이그레이션이 필요 없다.

### 3. 로컬 수명주기는 현행 유지

통과가 없어도 PhysicalVehicle은 `RETIRED`하고, child scope(ZoneVisit·ParkingEpisode·Incident)와 ContextBinding은 지금처럼 종료한다. 두 가지 이유로 이 부분을 바꾸지 않는다.

- 부재 확정 사실은 상위 owner의 `forget()` ack까지 **매 프레임 반복된다**(`src/tracking/presence_confirmer.py:118-139`). 소비하지 않으면 무한 반복이다.
- BOUND 상태의 ContextBinding을 남기면 `_active_scope_names`의 검사(`src/application/physical_presence_workflow.py:267-271`)에 걸려 `UnfinishedPhysicalVehicleScopeError`로 **RETIRE 자체가 실패**한다.

즉 이 변경은 "로컬 수명주기는 그대로 닫고, 백엔드 발행과 mirror 상태만 억제한다"로 구현된다.

### 4. 관측 가능성

발행하지 않은 출차가 조용히 사라지지 않도록 두 가지를 남긴다.

- `physical_vehicles.termination_reason = 'ABSENCE_WITHOUT_EXIT_EVIDENCE'`
- 경고 수준 로그 (physical_vehicle_id, session_id, absence_confirmed_at 포함)

백엔드에 "출차 근거 없는 부재" 사실을 별도로 알리는 경로는 이번 범위 밖이다 — 새 API라 계약 협의가 먼저 필요하다(§후속).

### 5. 계약 문서 수정

`docs/HW API 정리.md` API 10(SessionExit)의 다음 문장이 사실과 달라진다.

> `evidence`는 현재 `ENTRY_EXIT_TRAVERSAL` 또는 `FULL_AREA_ABSENCE`다. 현행 한-camera 파일럿은 정상 전체 영역 관측으로 확정한 `FULL_AREA_ABSENCE`를 사용한다.

이 변경 후 `FULL_AREA_ABSENCE`는 wire에 **영구히 나가지 않는다.** 문장을 교체하고 다음 조항을 계약에 추가한다.

- Jetson은 출차 구역(`ENTRY_EXIT` / `EXIT`) 통과가 관측된 부재만 SessionExit으로 발행한다.
- 통과가 관측되지 않은 부재는 로컬에서만 종료되고 Backend에 발행되지 않는다. 해당 session은 Jetson이 닫지 않으므로 행정 종료가 필요하다.

백엔드 담당자가 확인해야 하는 부분이다.

## 테스트 계획

- mirror 유무 × 통과 유무 4조합의 `plan_departure` 결과 (발행 여부, evidence, mirror 상태, termination_reason)
- `ENTERING` 상태(1.0초 미달)의 출차 구역 방문만 있어도 통과로 인정되는지 — 이 정의의 핵심이므로 명시적으로 고정한다
- 통과 없을 때 outbox에 아무것도 적재되지 않고 mirror가 `EXITED`가 아닌지
- 출차가 아닌 구역(`GENERAL`, `AISLE`, `ENTRY` role) 방문만 열려 있으면 통과로 인정되지 않는지
- 읽기 순서 회귀: `physical_exit()` 이후 `exit_zone_traversal_observed()`가 `False`
- 현재 ZoneRegistry에 없는 zone_id의 방문이 열려 있어도 예외 없이 통과 미인정으로 처리되는지
- 기존 SessionExit 테스트들의 evidence 기대값을 `ENTRY_EXIT_TRAVERSAL`로 갱신

## 받아들이는 대가

통과가 관측되지 않은 세션은 **Jetson이 닫을 방법이 없다.** 그 차가 다시 나타나도 새 PhysicalVehicle이 되어 기존 mirror에 재correlate되지 않는다. 관리자 수동 종료(백엔드 행정 `CLOSED`)가 유일한 해소 경로다. 이는 A안 채택 시 의식적으로 받아들인 결과이며, §4의 로그와 termination_reason으로 진단 가능하게만 만든다.

## 비범위 / 후속

- **폴리곤 상단 여백 문제**: 출차 구역과 프레임 경계 사이에서 마지막 관측이 끊기는 경우. 파일럿 영상으로 실제 이탈 궤적을 확인한 뒤, 필요하면 별도 태스크로 폴리곤을 조정한다(로직 변경이 아니라 설정 변경).
- **출차 근거 없는 부재를 백엔드에 알리는 경로**: 새 API가 필요하고 계약 협의 대상이다.
- **end-to-end 발행 검증**: 현재 `HW_API_KEY`가 비어 있으면 outbox 워커가 생성되지 않고(`src/main.py`), 검증에 쓰는 `scripts/watch_live_stream.py`·`scripts/replay_pilot_video.py`에는 `BackendClient`가 없다. 즉 지금까지 백엔드로 나간 출차는 0건이며 통합 검증이 된 적이 없다. 이 검증은 별도 태스크다.
- **부재 확정 시간(`ABSENCE_CONFIRMATION_SECONDS=5.0`) 실측 재조정**: 현재 값을 그대로 재사용한다.
