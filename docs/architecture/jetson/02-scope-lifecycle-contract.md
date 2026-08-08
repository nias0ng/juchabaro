# Jetson Scope 수명주기 계약

> 상태: Draft · 관련 이슈: S15P11E202-461 · 책임: scope별 상태와 전이 조건

이 문서는 각 scope의 상태와 owner를 정의한다. 출력 의미는 [도메인 목적 및 출력 계약](./01-domain-purpose-and-output-contract.md), scope 사이 전파는 [전파 및 종료 계약](./03-scope-propagation-contract.md)을 따른다.

## 1. 공통 규칙

### 1.1 Domain·observation·delivery 분리

Domain lifecycle, 현재 관측 신뢰도, Backend delivery는 서로 다른 상태다. 관측이나 전달 상태만 바뀌었다고 domain transition을 만들지 않는다.

### 1.2 참조와 수명 소유를 구분

한 scope가 다른 scope를 참조하거나 평가 근거로 사용한다고 해서 참조 대상 종료가 자동 전파되지는 않는다. 직접 전파되는 경우는 [전파 행렬](./03-scope-propagation-contract.md)에 명시된 경우뿐이다.

특히 다음은 고정한다.

- TrackSegment 종료는 PhysicalVehicle 종료가 아니다.
- ParkingEpisode 종료는 Incident 종료가 아니다.
- movement는 BlockingRelation과 Incident의 `REEVALUATE` trigger다.
- Backend 업무 상태 완료는 Jetson Incident RESOLVE가 아니다.

### 1.3 공통 최소 record

모든 scope가 동일한 거대 base class를 가질 필요는 없다. 다만 영속 scope는 필요에 따라 다음 의미를 제공한다.

```text
scope identity
domain state
recordVersion
createdAt / updatedAt
observationState / lastReliableObservedAt
trusted accumulated duration
termination reason / terminatedAt
publicationRevision
```

`recordVersion`은 local 동시성 제어용이고 `publicationRevision`은 외부 공개 순서다. 내부 상태 변경마다 publication revision을 올리지 않는다. 모든 내부 전이를 영구 event log로 저장할 의무도 없다.

### 1.4 시간

- `occurredAt`: 현장 사실이 성립한 시각
- `recordedAt`: Jetson이 사실을 영속 확정한 시각
- `trustedDuration`: 정상 관측 sample로만 누적한 시간

재시작이나 camera unavailable 구간을 wall-clock 차이로 trustedDuration에 더하지 않는다. 모든 timestamp는 timezone-aware여야 하고, 순서 판단은 aggregate revision을 우선한다.

## 2. Observation 계약

| 상태 | 의미 | domain 처리 |
|---|---|---|
| `OBSERVED` | 필요한 관측과 dependency가 정상 | 신뢰 sample을 누적하고 전이 조건 평가 |
| `DEGRADED` | 일부 관측은 있으나 정상 전체 관측 조건을 충족하지 못함 | 부재·종료를 확정하지 않고 timer 정지 |
| `UNKNOWN` | 긍정과 부정을 모두 판단할 수 없음 | domain state 유지, timer 정지 |

대표 reason은 다음과 같다.

```text
CAMERA_UNAVAILABLE
PIPELINE_STALLED
PARTIAL_FRAME
TRACK_LOST
REIDENTIFICATION_UNCERTAIN
DEPENDENCY_UNAVAILABLE
PROCESS_RESTARTED
```

Observation reason이나 지속 시간 자체는 termination reason이 아니다.

### 2.1 신뢰 가능한 차량 부재

`[결정]` 관측 부재를 물리 종료 근거로 사용하려면 다음을 모두 만족해야 한다.

1. camera와 inference pipeline이 정상이다.
2. 대상 차량이 존재할 수 있는 전체 관리 영역이 frame에 포함된다.
3. 해당 구간의 frame·detector 결과가 유효하다.
4. `absenceConfirmationDurationSeconds` 동안 대상이나 재식별 후보가 관측되지 않는다.

이 조건을 만족한 결과는 단순 `TRACK_LOST`가 아니라 `NOT_PRESENT_CONFIRMED`다. 현재 모형은 camera 한 대가 전체 구역을 관측한다는 전제를 사용한다. 이 전제가 깨지는 실제 주차장이나 다중 camera 구성은 별도 설계가 필요하다.
한번 확정한 NOT_PRESENT 사실은 상위 consistency boundary가 종료 transaction을 commit하고 ack할 때까지 반복 전달한다. 최초 threshold 충족 시각을 immutable `occurredAt`으로 보존하며, 재전달이나 재시작 때문에 현재 시각으로 바꾸지 않는다. 후속 sample이 DEGRADED·UNKNOWN이면 새 부재 시간은 누적하지 않지만, 이미 확정한 사실을 취소하지는 않는다. 차량이 다시 관측되면 종료 commit 전 accumulator를 reset한다.

현재 모형에서는 NOT_PRESENT_CONFIRMED를 물리 차량 departure 근거로 사용한다. active ContextBinding 또는 행정 종료 뒤 보존한 session–vehicle correlation이 있으면 Session EXIT의 `FULL_AREA_ABSENCE` evidence가 될 수 있고, 어느 session과도 연결되지 않으면 local child와 Incident를 정리하는 `PHYSICAL_VEHICLE_LEFT` 입력이 된다.

장기 UNKNOWN에서는 scope의 ObservationState를 UNKNOWN으로 유지한다. 별도의 camera·pipeline operational health를 `DEGRADED`로 보고할 수 있지만 scope를 terminal로 만들지 않는다.

## 3. 식별자

공유 식별자의 정본은 [식별자 수명 및 매핑 계약](../identifier-contract.md)이다. 목표 설계에서 추가하거나 의미를 정규화하는 값은 다음과 같다.

| 식별자 | 의미 | 생성 시점 |
|---|---|---|
| `entryAttemptId` | 한 물리적 입차 인식 시도 | upstream에서 입차 시도 생성 시; 현재 wire `trackingId`의 목표 의미 |
| `contextBindingId` | PhysicalVehicle과 authoritative session/context의 한 연결 | binding 생성 시 |
| `blockingRelationId` | subject·victim·egress context의 한 차단 관계 | relation candidate 생성 시 |
| `incidentId` | 한 규칙 사건의 Candidate부터 RESOLVED까지 | Incident Candidate 생성 시 |
| `verificationAttempt` | 같은 request의 재확인 순번 | command 발행 주체가 새 시도 생성 시 |
| `evidenceId` | 한 immutable evidence artifact | capture 예약 시 |

`entryAttemptId`는 entry capture upstream이 생성하며 현재는 Raspberry Pi가 그 역할을 한다. 최종 wire 이름과 `contextBindingId` 전달 여부는 `[후속 계약]`이다. domain에서는 네트워크 retry와 다른 안정적인 값이 존재한다고 가정한다.

## 4. Scope catalog

| Scope | Owner | 생성부터 종료까지 |
|---|---|---|
| `TrackSegment` | tracking adapter | tracker segment 생성부터 소실·reset까지 |
| `PhysicalVehicle` | `EntityResolver` | 실차 가설부터 확정 부재와 child 정리까지 |
| `EntryMatchAttempt` | `EntryMatchCoordinator` | 입차 문맥 접수부터 물리 매칭이 terminal이고 access decision이 settled될 때까지 |
| `ContextBinding` | `ContextBindingCoordinator` | authoritative session/context 연결부터 exit·정정까지 |
| `ParkingSessionMirror` | `PhysicalPresenceCoordinator` | session 수신부터 실제 EXIT 또는 physical correlation이 끝내 없는 UNCONFIRMED session의 행정 종료까지 |
| `ZoneVisit` | `ZoneVisitTracker` | 구역 진입 후보부터 확정 이탈까지 |
| `ParkingEpisode` | `ParkingEpisodeTracker` | 정지 후보부터 이동·실제 exit까지 |
| `BlockingRelation` | `BlockingRelationTracker` | 차단 후보부터 관계 해소까지 |
| `Incident` | `IncidentReducer` | 규칙 후보부터 해소·취소까지 |
| `MoveVerificationAttempt` | `MoveVerificationCoordinator` | command 수락부터 immutable 결과까지 |

ParkingAssignment는 ParkingEpisode 안의 값이다. `PlacementEvidence`는
AssignmentResolver가 현재 footprint와 ZoneDefinition snapshot으로 만드는
immutable ephemeral value이며 domain scope, lifecycle, timer가 아니다.
`EgressBlockingEvidence`도 subject footprint와 EgressAisleDefinition snapshot으로
만드는 immutable ephemeral value이며 새 scope나 상태축이 아니다.
EvidenceArtifact와 outbox는 domain scope가 아니라 저장·전달 workflow이며
`04`에서 정의한다.

`ZoneOccupancySnapshot`, 활성 ToF 점유 구간,
`TofZoneAuthorizationAssessment`와 local warning projection은 process-local
observation·application state다. durable scope, 외부 식별자 또는 outbox
aggregate로 추가하지 않으며 별도 `occupancyEpochId`를 만들지 않는다.

## 5. TrackSegment

```text
ACTIVE → ENDED
```

TrackSegment는 ephemeral이다. tracker reset, max-age, process restart로 종료할 수 있다. 종료 사실은 `EntityResolver`에만 전달하며 다른 scope를 직접 끝내지 않는다. 재시작 후 복원하지 않고 새 segment를 만든다.

## 6. PhysicalVehicle

```text
CANDIDATE → ACTIVE → RETIRED
CANDIDATE → CANCELED
```

- 새 track이 기존 PhysicalVehicle과 동일하다는 근거가 없을 때 Candidate를 만든다.
- identity confirmation 뒤 ACTIVE가 된다.
- 현재 adapter는 ByteTrack이 ID를 확정한 track만 domain snapshot으로 낸다. 따라서 첫 snapshot에서 Candidate→ACTIVE를 적용하고 durable snapshot은 ACTIVE로 시작한다. ID가 없는 tentative detection은 aggregate를 만들지 않고 그 sample의 부재 timer와 entry identity 매칭을 모두 멈춘다.
- segment가 모두 소실되면 ACTIVE를 유지하고 observation을 DEGRADED 또는 UNKNOWN으로 둔다.
- 재식별되면 새 segment를 같은 PhysicalVehicle에 연결한다.

### 6.1 EntityResolver 결정 계약

EntityResolver는 PhysicalVehicle 동일성의 유일한 owner다. tracker가 한 frame에서
보고한 모든 `TrackObservation`과 확정 종료한 `TrackSegmentId`를 한 번에 받아
다음 순서로 결정한다.

1. 종료 segment의 active 연결만 해제하고 PhysicalVehicle의 짧은 runtime
   geometry history는 보존한다.
2. 계속 관측된 segment가 연결한 PhysicalVehicle을 먼저 예약한다.
3. 새 segment와 미예약 PhysicalVehicle 후보를 시간 간격, bbox 중심 이동,
   속도 예측 IoU, 면적·종횡비 일관성으로 hard gate와 score를 계산한다.
4. frame 전체에서 최대 점수의 전역 1:1 배정을 구한다. 입력 순서와 UUID 문자열은
   의미상 tie-break가 아니며 동일 PhysicalVehicle을 둘 이상의 segment에 배정하지 않는다.
5. 최적 배정과 선택 edge를 금지한 차선 배정의 점수차가 ambiguity margin보다
   작으면 연결을 확정하지 않는다.

결과는 `CONTINUED / REIDENTIFIED / CREATED / UNRESOLVED`의 비영속
`IdentityResolution`이다. `UNRESOLVED`는 새 PhysicalVehicle을 임의 생성하지
않고 `allIdentitiesResolved=false`와 `UNKNOWN / REIDENTIFICATION_UNCERTAIN`을
만든다. 이 sample에서는 부재, EntryMatch, ZoneVisit, ParkingEpisode,
BlockingRelation과 Incident의 trusted time을 모두 멈춘다. 다음 frame에서 근거가
충분해지면 같은 후보를 다시 평가한다.

재식별 근거에는 현재·직전 bbox와 관측 시각만 사용할 수 있다. zone, assignment,
PARKED, Incident, session·등록 차량 context와 YOLO confidence는 동일성의 결과나
하위 owner의 결론이므로 score 근거로 되먹이지 않는다. `forgetPhysicalVehicle`은
`NOT_PRESENT_CONFIRMED` 뒤 상위 종료 transaction이 commit된 후에만 호출하여
history를 제거한다.

ACTIVE를 정상 RETIRED로 만들려면 다음을 모두 만족해야 한다.

1. 실제 Session EXIT 또는 `NOT_PRESENT_CONFIRMED`가 있다.
2. active ContextBinding, ZoneVisit, ParkingEpisode와 BlockingRelation이 없다.
3. 관련 Incident가 모두 CANCELED 또는 RESOLVED다.

장기 미탐지나 cache eviction만으로 RETIRED로 만들지 않는다. RETIRED는 delivery 완료를 기다리지 않으며 미완료 publication은 terminal tombstone과 outbox가 독립적으로 보존한다.

## 7. EntryMatchAttempt와 ContextBinding

### 7.1 EntryMatchAttempt

EntryMatchAttempt는 두 개의 독립적인 축을 가진다.

```text
matchState = PENDING → MATCHED | EXPIRED | FAILED | CANCELED
decisionState = ALLOW | DENY | REVIEW_PENDING | REVIEW_ALLOW | REVIEW_DENY | REVIEW_EXPIRED
```

EntryMatchAttempt의 identity는 `entryAttemptId`다. 동일 입차 event의 네트워크 retry는 새 attempt가 아니다.

- `MATCHED`: 해당 entry attempt의 PhysicalVehicle이 확인됨
- `EXPIRED`: deadline까지 차량을 신뢰 가능하게 고르지 못함
- `FAILED`: payload나 계약 오류로 시도를 수행할 수 없음
- `CANCELED`: upstream이 시도를 명시적으로 취소함

camera unavailable 때문에 deadline까지 확인하지 못한 경우 `EXPIRED / SOURCE_UNAVAILABLE`로 남기며 임의 차량에 매칭하지 않는다.

ALLOW·REVIEW·DENY는 EntryMatchOutcome과 별개의 access decision이다. REVIEW·DENY 차량도 물리 매칭될 수 있으며 이를 FAILED로 기록하지 않는다.

decisionState는 Backend 결정의 revisioned mirror다. 같은 revision의 동일 내용은 retry이고 다른 내용은 계약 오류다. 현재 계약에서 higher revision 전이는 REVIEW 해소만 허용한다.

```text
REVIEW_PENDING → REVIEW_ALLOW | REVIEW_DENY | REVIEW_EXPIRED
```

settled decision은 현재 계약에서 immutable이며 REVIEW_PENDING으로 되돌리거나 ALLOW·DENY 사이를 재전이하지 않는다. `ALLOW`와 `REVIEW_ALLOW`에는 authoritative `sessionId`와 context가 반드시 포함된다. 한 `entryAttemptId`에는 authoritative sessionId를 최대 하나만 연결하며 다른 session은 새 entryAttemptId를 사용한다.

EntryMatchOutcome은 matchState가 terminal이 될 때 만들 수 있다. matchState가 terminal이고 decisionState도 `REVIEW_PENDING`이 아니면 attempt의 현재 업무는 settled다. 따라서 물리 매칭이 먼저 끝나도 REVIEW가 끝날 때까지 entryAttemptId와 match 결과를 보존한다.

### 7.2 ContextBinding

```text
BOUND → ENDED
```

다음을 모두 만족할 때만 binding을 만든다.

1. EntryMatchAttempt가 PhysicalVehicle을 MATCHED했다.
2. ALLOW 또는 `REVIEW_ALLOW`로 authoritative `sessionId`가 있다.
3. session이 이미 실제 EXIT 또는 행정 종료되지 않았다.
4. 대상 PhysicalVehicle이 ACTIVE이고 physical departure가 확정되지 않았다.

REVIEW 중 번호판·자격은 hint이며 `UNKNOWN`이다. 자격값 변경은 같은 binding의 context update로 처리하고 restricted-zone 규칙을 재평가한다. 이미 확정한 binding의 sessionId나 PhysicalVehicle을 다른 identity로 바꾸는 correction은 현재 범위에서 지원하지 않으며 conflict로 거부한다.

ALLOW 또는 REVIEW_ALLOW가 physical departure·RETIRED 뒤 늦게 도착하면 active binding을 만들지 않는다. authoritative correlation receipt만 남기고 retention 안의 pending historical handoff를 원래 occurredAt 순서로 materialize한다. 이미 PARKED였던 episode가 PHYSICAL_EXIT로 끝났다면 PARKED와 SessionExit을 만들되 UNPARKED는 만들지 않으며, ParkingSessionMirror는 곧바로 EXITED historical 상태로 기록한다. 이미 entryAttemptId로 공개한 Incident를 sessionId 추가만을 위해 재발행하지 않는다.

`sessionId`당 active ContextBinding과 `physicalVehicleId`당 active authoritative ContextBinding은 각각 최대 하나다. 한 physicalVehicleId에 출차를 발행할 수 있는 session-mirror correlation도 최대 하나다. 이 cardinality를 깨는 입력은 conflict로 거부한다.

## 8. ParkingSessionMirror

ParkingSessionMirror는 Backend 행정 상태, 현장 presence와 현재 관측 신뢰도를 한 enum으로 합치지 않는다.

```text
administrativeState = ACTIVE | CLOSED
physicalPresenceState = UNCONFIRMED | INSIDE | EXITED
physicalObservationState = OBSERVED | DEGRADED | UNKNOWN
physicalTerminationOrigin = JETSON_EXIT_CONFIRMED | null
physicalExitEvidence = ENTRY_EXIT_TRAVERSAL | FULL_AREA_ABSENCE | null
```

- `administrativeState.CLOSED`는 관리자 취소·데이터 정정·업무상 종료이며 물리 출차를 의미하지 않는다.
- `physicalPresenceState.UNCONFIRMED`는 session을 받았지만 PhysicalVehicle 연결이 아직 없는 초기 domain 상태다. INSIDE에서 관측이 나빠져도 UNCONFIRMED로 되돌리지 않고 physicalObservationState만 바꾼다.
- authoritative ContextBinding이 생기면 physicalPresenceState는 INSIDE가 된다.
- `physicalPresenceState.EXITED`만 session-scoped physical child 종료를 전파할 수 있다.
- 행정 종료 뒤에도 실제 차량이 남아 있으면 presence와 local Incident 관측을 계속한다.
- 행정 종료 시 `ContextBinding → ENDED / ADMIN_CLOSED`로 만들고 session-scoped publication을 보류한다.
- 이 보류는 stale session context로 새 사실을 여는 것을 막는 규칙이다. 이미 공개한 aggregate의 terminal revision은 저장된 correlation으로 계속 전달한다.
- mirror는 ContextBinding 종료 뒤에도 실제 출차를 연결할 수 있도록 `physicalVehicleId`와 원래 `entryAttemptId` correlation을 보존한다. 이 참조는 authoritative 자격 binding이 아니다.
- 마지막 context는 감사 근거로만 보존하고 자격 의존 규칙은 새 authoritative context 전까지 UNKNOWN이다.
- 행정 종료 뒤 실제 출차가 확인되면 같은 mirror의 physicalPresenceState를 EXITED로 바꿀 수 있다. 이는 session 재활성화가 아니다.

새로운 입차는 새 session이다. Mirror는 physical presence가 EXITED이고 미완료 publication·command가 없을 때 terminal storage로 축약할 수 있다. 한 번도 binding되지 않은 UNCONFIRMED mirror는 연결된 matchState가 EXPIRED·FAILED·CANCELED이고 administrativeState도 CLOSED일 때 `NO_PHYSICAL_CORRELATION` tombstone으로 축약한다. 이는 physical EXIT나 SessionExit을 만들지 않는다.

administrativeState가 먼저 CLOSED된 뒤 matchState가 MATCHED되면 active ContextBinding은 만들지 않되 mirror에 physicalVehicleId를 exit-only correlation으로 보존하고 presence를 INSIDE로 둔다. 대상이 이미 RETIRED라면 late historical correlation 경로로 mirror를 EXITED 처리한다. 단, 같은 PhysicalVehicle에 다른 exit-enabled mirror가 있으면 conflict로 거부하고 두 번째 출차 correlation을 만들지 않는다. 이 conflict mirror는 administrativeState가 CLOSED되면 `CORRELATION_CONFLICT` tombstone으로 축약하며 EXIT나 SessionExit을 만들지 않는다.

## 9. ZoneVisit

```text
ENTERING → INSIDE → EXITING → ENDED
    └→ CANCELED      └→ INSIDE
```

- `ENTERING`: zone 내부 진입 후보이며 timer 누적 중
- `INSIDE`: 진입 confirmation 충족
- `EXITING`: 내부였던 차량의 이탈 후보
- `ENDED`: 신뢰 가능한 외부 관측 또는 실제 exit 확인
- `CANCELED`: INSIDE 전에 후보가 사라지고 정상 관측에서 비성립 확인

실제 physical exit가 먼저 확인되면 ENTERING은 `CANCELED / PHYSICAL_EXIT`, INSIDE와 EXITING은 `ENDED / PHYSICAL_EXIT`가 된다. EXITING 중 다시 내부가 확인되면 exit timer를 버리고 INSIDE로 돌아간다.

UNKNOWN에서는 현재 state와 timer 하한을 유지한다. `EXITING → ENDED`에는 정상 전체 관측에서 zone 외부 또는 `NOT_PRESENT_CONFIRMED`가 필요하다.

활성 visit은 `zoneId + zoneDefinitionVersion`을 참조한다. 설정 조회 실패는 zone 삭제가 아니므로 `UNKNOWN / DEPENDENCY_UNAVAILABLE`로 둔다. 실행 중 ZoneDefinition hot replacement는 지원하지 않는다. 새 version은 active scope가 없는 통제된 기동에서 적용하며, active scope를 복구해야 하는 기동에는 기존 version을 함께 제공해야 한다.

`ENTRY_EXIT` ZoneDefinition은 `entryExitRole = ENTRY | EXIT`를 반드시 갖는다. `EXIT`는 명시적 `exitTraversal(line, outwardPoint, hysteresis)`를 추가로 갖고, 이 정의 없이 인접 AISLE 배치로 외향을 추론하지 않는다. EntryMatchCoordinator는 `ENTRY`에서만 입차 attempt를 매칭하며, 같은 sample의 ENTRY 후보가 두 대 이상이면 detector 순서로 임의 매칭하지 않고 보류한다.

정상 관측에서 active EXIT visit의 차량 bbox 중심이 기준선 외향 쪽
`hysteresis`를 넘으면 frame-local `ExitTraversalObservation(OUTWARD)`을 만든다.
application workflow는 이를 같은 frame transaction에서 차량별 durable
checkpoint로 latch한다. 이 checkpoint는 ZoneVisit 종료와 process restart 뒤에도
유지되며, 부재 확정 transaction이 읽고 소비한 경우에만 SessionExit 근거가 된다.
외향 통과 뒤 같은 기준선의 내향 쪽에서 `exitReentryConfirmationSeconds` 동안
연속 trusted 관측되면 재진입으로 보아 checkpoint를 삭제한다. 마지막 bbox와
active visit의 순간 조합만으로 과거 통과 사실을 재구성하지 않는다.

`(physicalVehicleId, zoneId)`당 non-terminal ZoneVisit은 하나만 허용한다.

## 10. ParkingEpisode

```text
STOP_PENDING → PARKED → MOVE_PENDING → ENDED
      └→ CANCELED          └→ PARKED
```

- `STOP_PENDING`: stationary 후보와 trusted timer 누적
- `PARKED`: 적용된 주차 확인 시간을 충족
- `MOVE_PENDING`: PARKED 뒤 movement confirmation 중
- `ENDED / MOVEMENT_CONFIRMED`: 이동이 확정되어 UNPARKED publication 대상
- `ENDED / PHYSICAL_EXIT`: PARKED 또는 MOVE_PENDING 중 실제 출차로 종료하며 별도 UNPARKED 없음
- `CANCELED`: PARKED 전 정상 관측에서 후보 비성립 확인

STOP_PENDING 중 실제 physical exit가 확인되면 `CANCELED / PHYSICAL_EXIT`다.

ParkingEpisode의 새 후보와 STOP_PENDING timer는 `ParkingEligibility`가
`ELIGIBLE`일 때만 진행한다. 정상 bbox가 `ENTRY_EXIT` polygon과 겹치거나 해당
ZoneVisit이 non-terminal이면 `INELIGIBLE`이며, 기존 STOP_PENDING은
`CANCELED / PARKING_INELIGIBLE`로 닫는다. 관측이 불신뢰하면 `UNKNOWN`으로 timer
chain만 끊는다. 이미 PARKED인 episode의 종료는 eligibility가 아니라 motion과
physical exit owner가 계속 담당한다. 이 경계 때문에 ENTRY와 EXIT 통로의 일시
정지가 PARKED·OUT_OF_ZONE Incident로 승격되지 않는다.

episode는 [직접 설정값](#14-직접-설정값) 중 주차·이동 판단에 실제 적용한 scalar를 생성 시 snapshot한다. UNKNOWN과 downtime을 timer에 합산하지 않으며 진행 중 episode에는 새 설정값을 소급 적용하지 않는다.

PARKED에서 처음 신뢰할 수 있는 `MOVING` sample은 `MOVE_PENDING`을 열고 movement
trusted timer를 0에서 시작한다. 그 뒤 신뢰할 수 있는 `MOVING` sample 사이의
간격만 더하며, 누적값이 episode에 snapshot한
`movementConfirmationDurationSeconds` 이상(`>=`)이 되는 첫 sample에서
`ENDED / MOVEMENT_CONFIRMED`로 전이한다. `UNKNOWN`, `DEGRADED`, restart downtime은
이미 누적한 하한을 보존하되 다음 trusted sample과의 시간 연결을 끊는다.
`MOVE_PENDING`에서 신뢰할 수 있는 `STATIONARY`가 다시 확인되면 같은 episode의
`PARKED`로 돌아가며 movement timer와 candidate 시각을 초기화한다.

MotionEstimator의 첫 sample, 불충분한 history, 허용 범위를 넘은 sample gap과
ambiguous band는 `MotionSignal.UNKNOWN`이다. 현재 bbox·identity가 정상이어도
ParkingEpisode에는 `UNKNOWN / DEPENDENCY_UNAVAILABLE`로 전달해 trusted chain을
끊는다. PARKED에 의존하는 RuleEvaluator도 같은 sample을 `UNKNOWN`으로 평가하며,
특히 `BAD_PARKING`, `OUT_OF_ZONE`, `AISLE_BLOCK`을 `NOT_MATCHED`로 바꿔
Incident clear를 시작하지 않는다. ZoneVisit과 현재 assignment geometry는 motion
dependency가 아니므로 정상 관측을 계속 사용한다.

ParkingAssignment는 다음 최소 값을 가진다.

```text
zoneId 또는 unassigned reason
representative footprint
assignment confidence
lastStableAt
```

assignment의 `zoneId`는 `GENERAL / DISABLED / EV_CHARGING`만 가리킬 수 있다. AISLE과 ENTRY_EXIT은 assignment 대상이 아니다.

STOP_PENDING에서는 신뢰 가능한 `STATIONARY` sample의 footprint와 그 sample에서
해석한 assignment 중 **최초 trusted placement 후보**를 episode에 미공개로 latch한다.
이 후보는 기존 ParkingEpisode assignment 저장 열에 함께 영속하므로 restart를
별도 상태축이나 비영속 sample window로 만들지 않는다. Motion owner가 이미
`STATIONARY`로 신뢰한 최초 실제 표본을 고정해, 확인 시간 동안 이어지는 여러
frame의 detector bbox jitter가 최종 배치를 바꾸지 않게 한다. 최초 sample에
assignment가 없었던 tracker 직접 호출만 이후 첫 non-null sample을 fallback으로
latch한다. 고정된 실제 sample의
footprint가 `representativeFootprint`, 시각이 `lastStableAt`이 된다. STOP_PENDING
assignment는 publication 근거가 아니며 CANCELED로 끝날 때 폐기한다.

AssignmentResolver는 이 representativeFootprint에서 PlacementEvidence를 다시
계산하여 `PARKED_SNAPSHOT` source로 표시한다. PARKED와 MOVE_PENDING
동안에는 새 frame의 bbox 진동으로 snapshot assignment·PlacementEvidence를
바꾸지 않는다. STOP_PENDING 또는 movement 확정 뒤 재평가에서는 현재
frame의 `EPHEMERAL_FRAME` evidence를 사용한다. MOVE_PENDING·motion
UNKNOWN에서는 snapshot을 보존하되 PARKED에 의존하는 RuleEvaluator signal은
`UNKNOWN / confirmable=false`로 멈춰 Incident clear를 시작하지 않는다.

ParkingEpisode가 `MOVEMENT_CONFIRMED`로 종료되면 assignment를 끝내고 관련 BlockingRelation·Incident에 `REEVALUATE`를 전달한다. 계속 위반이면 기존 Incident를 유지한다. `PHYSICAL_EXIT` 종료는 departure의 직접 종료 경로를 사용한다.

PhysicalVehicle당 non-terminal ParkingEpisode는 하나만 허용한다.

## 11. BlockingRelation

```text
CANDIDATE → BLOCKING → CLEAR_PENDING → RESOLVED
     └→ CANCELED          ↘ BLOCKING
```

identity는 `blockingRelationId`로 고정하며 subject PhysicalVehicle, victim
PhysicalVehicle과 `egressZoneId`를 포함한다. ParkingEpisode ID는 생성 근거로
보존할 수 있지만 수명을 소유하지 않는다. `egressZoneId`는 별도
EgressAisleDefinition snapshot이 부여한 식별자이며, 호환 필드명만
유지하고 ZoneDefinition의 `zoneId` namespace에는 속하지 않는다.

- Candidate에서 정상 geometry가 비성립하면 CANCELED
- 정상 geometry에서 차단 조건이 confirm되면 BLOCKING
- 이동·assignment·zone 변화는 `REEVALUATE` trigger
- 계속 차단하면 BLOCKING 유지
- 정상 전체 관측에서 불성립하면 CLEAR_PENDING
- clear confirmation 뒤 RESOLVED
- UNKNOWN이면 현재 state를 유지하고 timer를 멈춤

관련 차량의 실제 physical exit가 먼저 확인되면 CANDIDATE는 `CANCELED / PHYSICAL_EXIT`, BLOCKING과 CLEAR_PENDING은 `RESOLVED / PHYSICAL_EXIT`가 된다.

후보는 PARKED victim의 안정된 `ASSIGNED` 주차면에 매핑된 egress
영역과 다른 active subject 차량의 현재 footprint으로만 생성한다.
정상 관측에서 `subjectOverlap >= θsubject OR egressCoverage >= θegress`를
차단 geometry 성립으로 본다. 둘 다 미만이어야 비성립이며, 필수
관측이 불신뢰면 `UNKNOWN`이다. 이 비율과 임계값은 Assignment·
BAD_PARKING의 PlacementEvidence와 별도다. 최대 차량·relation 수와
평가 주기는 성능 실측으로 정한다.

`DOUBLE_PARKING` Incident의 `zoneId`는 egress 영역 자체의 id가 아니라,
BlockingRelation이 참조한 `EgressAisleDefinition.parkingZoneId`를 투영한다.
즉 피해 차량이 배정된 주차면을 가리키며, victim 차량 id와 함께 OPEN부터
고정한다.

`(subjectPhysicalVehicleId, victimPhysicalVehicleId, egressZoneId)`당 non-terminal BlockingRelation은 하나만 허용한다.

## 12. Incident

### 12.1 IncidentSignal

RuleEvaluator는 상태 없는 삼상태 signal만 만든다.

| Signal | 의미 | Reducer 처리 |
|---|---|---|
| `MATCHED` | 현재 규칙 술어가 성립함 | confirmable이면 후보 timer 누적·OPEN, 아니면 Candidate 생성·유지만 허용 |
| `NOT_MATCHED` | 필요한 입력을 모두 정상 관측했고 술어 불성립 | 후보 취소 또는 clear 진행 |
| `UNKNOWN` | 성립·불성립 모두 확정 불가 | lifecycle 유지, timer 정지 |

Signal은 IncidentKey, 관측 시각, confirmable 여부와 근거 참조를 가진다.
ParkingEpisode, ParkingAssignment와 PlacementEvidence는 parking rule의 평가
근거이지 Incident 수명이 아니다. RuleEvaluator는 PlacementEvidence에서
BAD_PARKING·OUT_OF_ZONE 술어를 계산하지만 signal 이전의 상태를
기억하지 않는다.

PARKED가 OPEN 조건인 규칙에서 movement와 ParkingEpisode의 MOVEMENT_CONFIRMED 종료만으로 `NOT_MATCHED`를 만들지 않는다. 한 신뢰 가능한 sample에서 규칙별 필수 geometry·assignment가 유효하고 위반 술어가 false이면 `NOT_MATCHED`를 만들며 IncidentReducer만 clear 시간을 누적한다. 필수 입력을 아직 판단할 수 없으면 `UNKNOWN / confirmable=false`로 기존 OPEN Incident를 유지한다.

### 12.2 상태

```text
MATCHED
→ incidentId 발급
→ CANDIDATE
→ OPEN
→ CLEAR_PENDING
→ RESOLVED
```

```text
CANDIDATE
  MATCHED + confirmable=false → CANDIDATE 유지, confirm timer·OPEN 금지
  MATCHED       → CANDIDATE, confirm timer 누적
  confirm 완료  → OPEN, publicationRevision = 1
  NOT_MATCHED   → CANCELED, publication 없음
  UNKNOWN       → CANDIDATE 유지, timer 정지

OPEN
  MATCHED       → OPEN
  NOT_MATCHED   → CLEAR_PENDING
  UNKNOWN       → OPEN 유지

CLEAR_PENDING
  NOT_MATCHED   → clear timer 누적 후 RESOLVED
  MATCHED       → OPEN
  UNKNOWN       → CLEAR_PENDING 유지, timer 정지
```

`REEVALUATE`는 위 상태가 아니라 새 IncidentSignal을 요청하는 trigger다.

### 12.3 동일성과 직접 종료 입력

IncidentKey는 rule별로 고정한다.

```text
전용구역·EV 초과                    = zoneVisitId + ruleCode
BAD_PARKING·OUT_OF_ZONE·AISLE_BLOCK = physicalVehicleId + ruleCode
DOUBLE_PARKING                      = blockingRelationId + ruleCode
```

동일 key에는 non-terminal Incident를 하나만 허용한다. ParkingEpisode, ParkingAssignment, spot과 현재 zone은 parking rule key가 아니다.

| 규칙 그룹 | 직접 종료 입력 | 재평가 trigger |
|---|---|---|
| 전용구역·EV 초과 | 해당 ZoneVisit ENDED, `PHYSICAL_VEHICLE_LEFT` | context 변경 |
| 불량 주차·구역 외·통행로 | `PHYSICAL_VEHICLE_LEFT` | ParkingEpisode movement·MOVEMENT_CONFIRMED 종료, assignment·geometry 변경 |
| 이중주차 | BlockingRelation RESOLVED, 관련 `PHYSICAL_VEHICLE_LEFT` | subject/victim 이동·assignment 변경 |

parking rule에서 ParkingEpisode의 MOVEMENT_CONFIRMED 종료는 직접 종료 입력이 아니다. 재평가 결과 `NOT_MATCHED`와 clear confirmation을 거쳐야 RESOLVED한다. `PHYSICAL_VEHICLE_LEFT`는 session 유무와 관계없이 정상 전체 관측 또는 실제 출차로 차량 부재가 확정됐다는 입력이다.

Incident는 CANDIDATE부터 같은 `incidentId`를 유지한다. publication revision은 OPEN부터 단조 증가한다. RESOLVED 뒤 신뢰 가능한 clear 구간을 거쳐 같은 규칙이 재성립하면 새 Incident를 만든다.

### 12.4 규칙별 confirm/clear 정책

`IncidentReducer`는 새 CANDIDATE를 만들 때 `ruleCode`로 timing 정책을 한 번
선택하고 `confirmDurationSeconds`와 `clearDurationSeconds`를 Incident에
snapshot한다. 진행 중 Incident와 restart로 복원한 Incident는 이후 runtime
정책이 바뀌어도 저장된 scalar를 계속 사용한다. 명시되지 않은 future rule만
전역 compatibility fallback을 사용하며, 같은 ruleCode의 override를 둘 이상
등록하는 구성은 시작 시 거부한다.

RuleEvaluator는 이 정책을 읽거나 timer를 누적하지 않는다. Viewer 진단은
reducer가 선택한 값을 조회해 실제 `IncidentSignal`과 함께 내보낼 수 있지만,
판정값을 다시 계산하지 않는다.

| 규칙 그룹 | confirm의 의미 | clear의 의미 |
|---|---|---|
| 전용구역 무자격·EV 초과 | 이미 확인된 ZoneVisit과 authoritative context에서 위반 술어가 연속으로 신뢰됨 | 같은 visit이 유지되는 동안 자격·초과 술어가 연속으로 false임 |
| BAD_PARKING·OUT_OF_ZONE·AISLE_BLOCK | PARKED 의존성과 유효한 placement 입력을 만족한 위반 술어가 연속으로 신뢰됨 | 유효한 재평가 sample에서 위반 술어가 연속으로 false임 |
| DOUBLE_PARKING | BlockingRelation owner가 confirm한 관계 신호가 연속으로 신뢰됨 | 관계가 nonterminal인 동안 해소 신호가 연속으로 신뢰됨 |

ZoneVisit ENDED, BlockingRelation RESOLVED, `PHYSICAL_VEHICLE_LEFT`처럼 상위
owner가 이미 확정한 직접 종료 입력은 rule의 clear debounce를 다시 적용하지
않는다. 이는 관측 기반 `NOT_MATCHED`와 scope 종료 사실을 구분하기 위함이다.

## 13. MoveVerificationAttempt

```text
ACCEPTED → CHECKING → COMPLETED
        ↘ CANCELED
        ↘ FAILED
```

결과는 다음 중 하나다.

```text
RESOLVED
STILL_ACTIVE
UNKNOWN
```

- command identity는 `requestId + verificationAttempt`다.
- command는 비어 있지 않은 `targetIncidentIds`를 포함한다. 하나의 request가 여러 Incident를 병합할 수 있다.
- 모든 target Incident는 같은 이동 대상 `subjectPhysicalVehicleId`를 가져야 하며, 서로 다른 차량은 별도 command로 확인한다.
- 동일 command retry는 같은 결과를 반환한다.
- movement 여부는 evidence일 뿐 결과 자체가 아니다.
- 대상별 최신 Incident가 모두 RESOLVED면 전체 결과는 `RESOLVED`다.
- 하나라도 최신 규칙이 MATCHED면 전체 결과는 `STILL_ACTIVE`다.
- MATCHED는 없지만 하나라도 판단 불가하거나 CLEAR_PENDING이라면 전체 결과는 `UNKNOWN`이다.
- deadline까지 신뢰 판단을 얻지 못하면 `UNKNOWN`이다.
- 실제 Session EXIT가 먼저 확정되면 `RESOLVED / SESSION_EXITED`가 될 수 있다.

결과는 전체 결과와 incidentId별 `RESOLVED / STILL_ACTIVE / UNKNOWN`을 함께 보존한다. 정확한 DTO는 후속 계약이다.

## 14. 직접 설정값

| 값 | 현재 상태 | 의미 |
|---|---|---|
| `parkingConfirmationDurationSeconds` | `[결정] 600` | PARKED 확정에 필요한 trusted stationary 시간 |
| `absenceConfirmationDurationSeconds` | `[제안값] TBD` | 정상 전체 관측에서 물리 부재 확인 시간 |
| `trustedSampleMaxGapSeconds` | `[제안값] TBD` | 연속 trusted frame으로 인정할 최대 sample 간격 |
| `reidentificationMaxGapSeconds` | `[제안값] TBD` | 종료 segment history를 새 segment 후보로 사용할 최대 시간; absence confirmation보다 작아야 함 |
| `reidentificationMinScore` | `[제안값] TBD` | 전역 1:1 geometry 배정 edge의 최소 수락 점수 |
| `reidentificationAmbiguityMargin` | `[제안값] TBD` | 최적 배정과 선택 edge를 금지한 차선 배정 사이의 최소 점수차 |
| `motionWindowSeconds` | `[제안값] TBD` | bbox motion evidence를 계산할 시간 창 |
| `motionMinObservationSpanSeconds` | `[제안값] TBD` | motion 판정에 필요한 최소 관측 span |
| `motionMaxSampleGapSeconds` | `[제안값] TBD` | motion history를 연속으로 인정할 최대 sample 간격 |
| `motionStationaryThreshold` | `[제안값] TBD` | median bbox diagonal 대비 정지 evidence 상한 |
| `motionMovingThreshold` | `[제안값] TBD` | median bbox diagonal 대비 이동 evidence 하한; stationary threshold보다 커야 함 |
| `motionMinSamples` | `[제안값] TBD` | endpoint 한 표본의 튐과 연속 이동을 구분하기 위한 최소 표본 수; 3 이상 |
| `motionMinTrendConsistency` | `[제안값] TBD` | 이동 방향·크기 일관성의 최소 비율 |
| `movementConfirmationDurationSeconds` | `[제안값] TBD` | PARKED 뒤 이동 확정 시간 |
| zone entry/exit confirmation | `[제안값] TBD` | ZoneVisit 진입·이탈 debounce |
| `exitReentryConfirmationSeconds` | `[제안값] 1.0` | durable EXIT 외향 latch를 취소할 연속 내향 관측 시간; ZoneVisit debounce와 별도 |
| `assignmentMinOverlap` | `[제안값] TBD` | primary overlap을 assignment 후보로 인정할 하한 |
| `assignmentAmbiguityMargin` | `[제안값] TBD` | primary·secondary dominance gap의 ambiguity 포함 상한 |
| `badParkingMinPrimaryOverlap` | `[제안값] TBD` | OUT_OF_ZONE이 아닌 sample에서 단일 주차면이 확보해야 할 최소 overlap |
| `badParkingMinSecondaryOverlap` | `[제안값] TBD` | 두 번째 주차면 침범으로 BAD_PARKING을 시작하는 overlap |
| `outOfZoneMinSpotOverlap` | `[제안값] TBD` | 전체 주차면 합집합 안에 있음을 인정할 최소 overlap |
| ToF enter/exit distance | `[제안값] 현장 실측 필요` | `enter < exit` hysteresis로 `OCCUPIED / VACANT` 거리 evidence를 구분 |
| ToF enter/exit confirmation duration | `[제안값] 현장 실측 필요` | stable `OCCUPIED` 시작과 stable `VACANT` 종료에 필요한 trusted 시간 |
| ToF trusted sample max gap / stale duration | `[제안값] 현장 실측 필요` | candidate 연속성과 observation `DEGRADED / UNKNOWN` 경계 |
| ToF occupancy / monitoring freshness | `[제안값] 현장 실측 필요` | 권한 평가에서 센서와 camera 관측 시점을 함께 신뢰할 수 있는 범위 |
| rule별 incident confirm/clear duration | `[제안값] 아래 표` | 새 Incident에 snapshot하는 OPEN·RESOLVE debounce; 직접 종료 입력에는 미적용 |
| entry match deadline | `[후속 계약] TBD` | 입차 문맥과 차량 매칭 제한 시간 |
| EV allowed duration·clock | `[후속 계약] 법령 근거 필요` | EV_OVERSTAY 값과 UNKNOWN 중 wall-clock 처리 |

### 실영상 replay 기반 Incident timing 제안

아래 값은 2026-08-05 Pipeline Viewer replay 세 건에서 얻은 provisional
권장값이다. YOLO confidence `0.25`, parking confirm `5.0s`, movement confirm
`0.5s`, zone entry/exit `1.0s/5.0s`, BlockingRelation confirm/clear
`1.0s/1.0s` 조건에 종속된다. Viewer의 compatibility 기본값을 변경하는 결정은
아니며, 추가 영상과 Jetson target 성능 측정 뒤 다시 조정한다.

| 규칙 | confirm | clear | 근거 |
|---|---:|---:|---|
| `DISABLED_ZONE_UNAUTHORIZED` | `0.0s` | `0.0s` | ZoneVisit owner가 entry `1.0s`, exit `5.0s`를 이미 확인하고 terminal visit은 직접 종료한다. |
| `EV_ZONE_UNAUTHORIZED` | `0.0s` | `0.0s` | 제한구역 점유는 확인된 ZoneVisit을 소비하므로 Incident에서 같은 debounce를 반복하지 않는다. |
| `EV_OVERSTAY` | `0.0s` | `0.0s` | allowed-duration 임계 통과 자체가 누적 사실이고 ZoneVisit 종료가 직접 전파된다. |
| `BAD_PARKING` | `0.5s` | `0.5s` | PARKED `5.0s` 뒤의 placement 신호를 한 번 더 짧게 안정화하되 실제 위반 신호 `4.833s/5.533s`는 보존한다. |
| `OUT_OF_ZONE` | `0.5s` | `0.5s` | 복도 주차의 최초 confirmable 신호가 `10.501s` 유지되어 `0.5s` debounce로 실제 사건을 보존한다. |
| `AISLE_BLOCK` | `0.5s` | `0.5s` | OUT_OF_ZONE과 같은 PARKED/placement 경계를 사용하고 단일 frame geometry 전이를 걸러낸다. |
| `DOUBLE_PARKING` | `0.0s` | `0.0s` | BlockingRelation owner의 `1.0s/1.0s`를 소비하므로 Incident에서 이중 지연하지 않는다. |

placement 규칙을 실제 `IncidentReducer`에 재적용했을 때 `0.5s/0.5s`는 두
BAD_PARKING OPEN을 각각 약 `0.533s` 지연했고 RESOLVE를 약 `0.533s`,
`0.967s` 지연하면서 전이를 모두 보존했다. clear `1.0s`는 두 번째 RESOLVE를
약 `2.767s` 지연했으므로 이 표본에서는 채택하지 않는다. `UNKNOWN` 구간은
trusted time을 늘리거나 clear로 승격하지 않는다.

설정값을 profile 상태로 감싸지 않는다. 해당 값이 진행 중 판단에 영향을 주면
scope 생성 시 실제 scalar 값을 snapshot한다. Incident rule timing 묶음은
composition 입력일 뿐 durable profile identity가 아니며, 각 Incident에는 선택된
두 scalar만 저장한다.

현재 reference implementation의 assignment·placement 다섯 threshold
(`assignmentMinOverlap`, `assignmentAmbiguityMargin`,
`badParkingMinPrimaryOverlap`, `badParkingMinSecondaryOverlap`,
`outOfZoneMinSpotOverlap`)는 한 pipeline 실행 동안 불변인 run policy다. active
PhysicalVehicle·ParkingEpisode·Incident를 복원하면서 이 값을 바꾸는 배포는
지원하지 않는다. 값을 바꿀 때는 active scope가 없는 통제된 새 실행(Replay는
새 DB)이어야 하고, export가 실행 전체 policy snapshot을 보존한다. 향후 hot
reload나 active scope를 유지한 policy 교체를 지원하려면 이 제한을 제거하기 전에
적용 scalar의 durable scope snapshot을 먼저 추가해야 한다.

MotionEstimator 설정은 영속 scope profile이 아니다. 각 `MotionEstimate`가 실제
적용한 stationary/moving threshold와 window 진단 근거를 내보내고, replay
산출물은 실행 전체 policy snapshot을 함께 보존한다. provisional 수치를 코드의
숨은 상수만으로 적용해 export와 실제 판정값이 달라지게 해서는 안 된다.

PhysicalVehicle은 생성 당시의 `absenceConfirmationDurationSeconds`와 `trustedSampleMaxGapSeconds`를 함께 snapshot한다. 배포 설정 변경 뒤에도 기존 차량의 진행 중 부재 판단은 그 값을 사용하고, 새 PhysicalVehicle부터 새 scalar를 적용한다.

`[결정]` 일반 배포의 `parkingConfirmationDurationSeconds`는 600이다. 시연에서는 같은 scalar를 명시적으로 override할 수 있으며 시연 뒤 600으로 복귀한다. 이를 위해 별도 profile 상태를 만들지 않는다.

## 15. ToF 점유와 현장 경고 수명주기

`ZoneOccupancySnapshot.stable_state`는 한 ToF 센서가 결속된 구역의 안정된
점유 사실이고 `observation`은 그 사실을 현재 얼마나 신뢰할 수 있는지 나타내는
독립 상태다.

```text
UNKNOWN → VACANT
UNKNOWN → OCCUPIED
VACANT ↔ OCCUPIED
```

- `[결정]` 확인 시간을 충족한 `OCCUPIED` 전이부터 확인 시간을 충족한 `VACANT`
  전이까지를 하나의 활성 점유 구간으로 본다. 이 구간은 별도 durable
  aggregate나 Incident가 아니라 process-local sensor lifecycle이다.
- sensor read 실패는 진행 중 candidate를 끊고 observation을
  `DEGRADED / UNKNOWN`으로 바꾸지만, 마지막으로 확정한 stable state와 활성
  점유 구간을 종료하지 않는다. 신뢰 가능한 `VACANT`만 물리 점유 종료
  근거가 된다.
- 안정된 `OCCUPIED`는 현장 경고 활성화의 필수 조건이지만 충분조건은 아니다.
  최신 PhysicalVehicle·ZoneVisit·ContextBinding·차량 자격과 관측 신뢰도를
  함께 평가해야 한다.
- 활성 점유 구간 전체에서 구역별 reconciliation lifecycle을 유지한다. 확정
  판정 뒤에는 대기할 수 있지만 최신 상태로 다시 수렴할 경로를 닫지 않으며,
  미확정 판정이나 projection 실패는 pending으로 유지한다. 재평가 wake-up과
  실패 backoff의 상세 전파는 `03`, runtime retry 경계는 `04`가 정의한다.
- `VACANT`가 확정되면 해당 구역의 pending 재평가와 retry를 취소하고 현장
  경고를 해제한다. 권한이 `AUTHORIZED`로 정정되면 같은 점유 구간 안에서도
  경고를 해제할 수 있다.
- 활성 점유 구간의 `UNAUTHORIZED`는 경고를 활성화하고 `AUTHORIZED`는
  해제한다. `UNKNOWN` 또는 미적용 평가는 새 경고를 활성화하지 않으며 관측
  불확실성만으로 이미 활성화한 경고를 해제하지도 않는다.
- 동일한 desired projection을 반복 적용하는 것은 새 경고 전이가 아니다.
  음성은 local warning이 비활성에서 활성으로 바뀌는 경계에서만 시작하며,
  actuator retry나 동일한 context 재적용은 음성을 다시 시작시키지 않는다.

sensor observation이 `DEGRADED / UNKNOWN`이면 권한 판정도 확정할 수 없으므로
새 경고를 활성화하거나 기존 경고를 해제하지 않는다. 어느 경우에도 observation
불신뢰만으로 `VACANT`를 추론하지 않는다.

## 16. Owner 경계

1. tracking adapter는 TrackSegment만 생성·종료한다. MotionEstimator는 resolved
   PhysicalVehicle의 bbox·관측 시각으로 ephemeral motion evidence만 만들며
   PhysicalVehicle identity, ParkingEpisode 또는 Incident lifecycle을 변경하지
   않는다.
2. EntityResolver만 PhysicalVehicle 동일성을 변경하며 frame 전체의 전역 1:1
   결정과 ambiguity 보류를 소유한다. 다른 owner의 결과를 재식별 evidence로
   되먹이지 않는다.
3. EntryMatchCoordinator는 물리 매칭 결과를 만들고 ContextBindingCoordinator만 binding을 변경한다.
4. ZoneVisitTracker와 ParkingEpisodeTracker는 각자의 시간적 사실만 소유한다.
   AssignmentResolver는 ZoneRegistry가 검증한 snapshot과 footprint에서
   PlacementEvidence·ParkingAssignment 값을 순수 계산하며 어떤 lifecycle도
   소유하지 않는다.
5. RuleEvaluator는 Incident를 저장하지 않는다.
6. IncidentReducer만 Incident를 생성·OPEN·RESOLVE한다.
7. PhysicalPresenceCoordinator만 bound·unbound physical departure의 다중-scope 종료 transaction을 조정한다.
8. publisher는 domain state를 바꾸지 않는다.
9. `OccupancyStateManager`만 ToF stable occupancy와 candidate를 변경한다.
10. `TofZoneAuthorizationService`는 한 occupancy snapshot과 최신 차량 문맥을
    상태 없이 평가하며 ZoneVisit·ContextBinding·Incident를 변경하지 않는다.
11. ToF local warning owner만 장애인·EV 전용구역 LED·speaker projection을
    변경한다. IncidentReducer와 publisher는 actuator를 제어하지 않는다.
