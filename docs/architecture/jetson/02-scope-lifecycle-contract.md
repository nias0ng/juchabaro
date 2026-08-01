# Jetson Scope 수명주기 계약

> 상태: Draft · 관련 이슈: S15P11E202-461 · 범위: Jetson target domain contract · 비범위: 구현 상세, 저장소·SQL 설계, 테스트 계획, 배포 계획

이 문서는 Jetson 도메인에서 시간에 따라 생성·활성·종료되는 scope의 공통 수명주기 계약과 scope별 고유 상태 머신을 정의한다. 이 문서의 상태는 현재 구현을 설명하는 것이 아니라 목표 도메인 계약을 고정한다.

현재 시스템에서 이미 합의된 식별자의 생성 주체·수명·전달 경로는 [식별자 수명 및 매핑 계약](../identifier-contract.md)을 따른다. Scope 사이의 종료 전파와 재평가 규칙은 [Jetson Scope 전파 및 종료 계약](./03-scope-propagation-contract.md)에서 다룬다.

## 설계 원칙

### 세 가지 상태 축을 분리한다

하나의 enum에 도메인 사실, 관측 가능성, Backend 전달 상태를 섞지 않는다.

| 축 | 답하는 질문 | 예 |
|---|---|---|
| Domain state | 이 scope가 표현하는 사실이 무엇인가 | `PARKED`, `OPEN`, `BLOCKING` |
| Observation state | 현재 그 사실을 신뢰 가능하게 관측하는가 | `OBSERVED`, `DEGRADED`, `UNKNOWN` |
| Delivery state | 공개할 전이가 Backend에 적용됐는가 | `PENDING`, `DELIVERED`, `DEAD_LETTER` |

따라서 다음 조합은 유효하다.

```text
Incident.domainState       = OPEN
Incident.lifecyclePhase    = ACTIVE
Incident.observationState  = UNKNOWN
Outbox.deliveryState       = DELIVERED
```

카메라가 끊겼다는 이유로 `OPEN`을 `RESOLVED`로, `PARKED`를 `ENDED`로, `INSIDE`를 `OUTSIDE`로 바꾸지 않는다.

### 공통 phase와 scope 고유 상태를 분리한다

`LifecyclePhase`는 모든 scope를 같은 용어로 비교하기 위한 축이다. `ZoneVisit.INSIDE`, `Incident.OPEN` 같은 업무 의미는 scope 고유 domain state에 둔다.

```text
PROVISIONAL -> ACTIVE -> TERMINATED
PROVISIONAL ----------> TERMINATED
ACTIVE ---------------> TERMINATED
```

`TERMINATED -> ACTIVE`는 허용하지 않는다. 재방문·재주차·재시도·재발생은 새 scope ID로 표현한다.

### 참조 관계만으로 종료를 전파하지 않는다

각 scope는 자신의 정상 종료 조건과 허용된 강제 종료 주체를 명시한다. 어떤 scope가 다른 scope를 참조한다는 사실만으로 자동 종료하지 않는다.

다음 사유는 물리적 도메인 사실의 종료가 아니다.

```text
TRACK_LOST
SOURCE_UNAVAILABLE
REIDENTIFICATION_UNCERTAIN
PROCESS_RESTARTED
```

이 사유들은 `PhysicalVehicle`, `ZoneVisit`, `ParkingEpisode`, `BlockingRelation`, `Incident`의 관측 상태만 바꾼다. 단, 자신이 관측 세션인 `TrackSegment`는 tracker reset이나 process restart로 종료될 수 있으며, 그 종료는 하위 물리 사실에 전파되지 않는다.

## 공통 수명주기 용어

### LifecyclePhase

| Phase | 의미 |
|---|---|
| `PROVISIONAL` | scope는 생성됐지만 확정 조건을 통과하지 못했다. |
| `ACTIVE` | scope가 자신의 도메인 사실이나 workflow 책임을 수행한다. |
| `TERMINATED` | scope 수명이 끝났으며 다시 활성화하지 않는다. |

`ACTIVE`는 Backend에 전송됐다는 뜻이 아니다. `EntryMatchAttempt.PENDING`, `OutboxRecord.DEAD_LETTER`처럼 진행 중이거나 운영 조치를 기다리는 workflow도 `ACTIVE`일 수 있다.

### TerminationKind

| Kind | 의미 | 예 |
|---|---|---|
| `NORMAL` | scope 자체의 정상 종료 조건이 확인됨 | 구역 이탈, 주차 후 이동, 사건 원인 해소 |
| `CANCELED` | 확정 전 후보가 조건을 충족하지 못함 | `ENTERING` 중 presence 해제 |
| `FORCED` | 권한 있는 상위 scope나 외부 정정으로 종료됨 | `ParkingSession EXIT` |
| `EXPIRED` | 명시적인 workflow 기한이 만료됨 | 입차 매칭 기한 만료 |
| `FAILED` | 계약·데이터 오류로 scope를 더 진행할 수 없음 | 복구 불가능한 command 오류 |

PROVISIONAL scope가 ACTIVE가 되지 못하고 끝나면 원칙적으로 `CANCELED`다. 후보 취소는 외부 `RESOLVE`가 아니다.

### ObservationState

| State | 의미 | 공통 처리 |
|---|---|---|
| `OBSERVED` | 현재 판단에 필요한 관측이 신뢰 가능함 | hysteresis를 거쳐 긍정·부정 사실을 확정할 수 있다. |
| `DEGRADED` | 일부 관측은 있지만 완전한 판단에는 부족함 | absence나 종료를 확정하지 않는다. 기본적으로 시간을 누적하지 않는다. |
| `UNKNOWN` | 긍정도 부정도 확정할 수 없음 | domain state를 유지하고 시간 누적을 정지하며 종료 전이를 만들지 않는다. |

관측 사유는 최소한 다음을 구분한다.

```text
SOURCE_UNAVAILABLE
TRACK_MISSING
LOW_CONFIDENCE
REIDENTIFICATION_UNCERTAIN
DEPENDENCY_UNAVAILABLE
PROCESS_RESTARTED
```

모든 scope가 `ObservationRecord`를 갖는 것은 아니다. 물리 사실을 관측하는 `PhysicalVehicle`, `ZoneVisit`, `ParkingEpisode`, `BlockingRelation`, `Incident`, `MoveVerificationAttempt`에는 필요하다. 순수 전달 workflow인 `OutboxRecord`에는 적용하지 않는다.

## 공통 Lifecycle record

다음은 모든 scope가 공유해야 할 개념 계약이다. 하나의 기반 class를 상속해야 한다는 구현 지침이 아니다.

### ScopeRef

```text
ScopeRef
- scopeKind
- scopeId
```

- `scopeId`는 생성 후 변경하지 않는다.
- `scopeId`, Backend 상관 식별자, `Idempotency-Key`를 구분한다.
- 동일한 물리 대상이라도 재방문·재주차·재시도는 새 scope ID를 받는다.

### 목표 식별자 확장

이 목표 설계는 현재 식별자 계약에 아직 없는 다음 식별자를 요구한다. 아래 표는 기존 구현 사실이 아니라 `Accepted` 전 팀 합의와 식별자 계약 반영이 필요한 목표 계약이다.

| 식별자 | 의미 | 생성 책임 |
|---|---|---|
| `contextBindingId` | 한 PhysicalVehicle과 한 ParkingSession의 연속 binding | `VehicleContextCoordinator` |
| `blockingRelationId` | subject·victim·egress corridor의 한 연속 차단 관계 | `BlockingRelationTracker` |
| `evidenceId` | 한 immutable evidence artifact | `EvidenceCoordinator` |
| `transitionId` | 한 scope의 immutable lifecycle transition | 해당 scope owner |
| `deliveryId` | 한 destination으로 전달할 한 publication | publication consistency boundary |
| `reconciliationId` | 한 reconciliation 교환의 상관관계 | reconciliation 시작 주체 |
| `edgeDeviceId` | publication을 만든 Jetson 장치 identity | 장치 provisioning authority |
| `bootId` | 한 Jetson process boot 구간 | application runtime |

`publicationRevision`, `deliveryAttempt`, `Idempotency-Key`는 식별자처럼 보이지만 서로 다른 순번·전달 의미를 가지며 아래 버전 계약을 따른다. 이 문서 묶음이 `Accepted`가 되면 위 식별자를 [식별자 수명 및 매핑 계약](../identifier-contract.md)에 통합한다.

각 scope의 `ScopeRef.scopeId`는 다음 identity를 사용한다. Composite identity는 문자열을 이어 붙이라는 구현 지침이 아니라 구성 요소 전체가 동일성에 참여한다는 의미다.

| Scope | Scope identity |
|---|---|
| CameraObservationState | `(edgeDeviceId, cameraId, bootId, sourceGeneration)` |
| TrackSegment | `(edgeDeviceId, bootId, cameraId, trackSegmentId)` |
| PhysicalVehicle | `physicalVehicleId` |
| EntryMatchAttempt | `(sessionId, matchAttempt)` |
| ContextBinding | `contextBindingId` |
| ParkingSessionMirror | `sessionId` |
| ZoneVisit | `zoneVisitId` |
| ParkingEpisode | `parkingEpisodeId` |
| BlockingRelation | `blockingRelationId` |
| Incident | `incidentId` |
| MoveVerificationAttempt | `(requestId, verificationAttempt)` |
| OutboxRecord | `deliveryId` |
| EvidenceArtifact | `evidenceId` |

### ScopeLifecycle

```text
ScopeLifecycle
- scope: ScopeRef
- phase: LifecyclePhase
- createdAt
- activatedAt?
- terminatedAt?
- lastTransitionAt
- termination?
- lifecycleSequence
- recordVersion
```

| 필드 | 의미 |
|---|---|
| `createdAt` | scope가 처음 생성된 도메인 시각 |
| `activatedAt` | PROVISIONAL에서 ACTIVE가 된 시각. 처음부터 ACTIVE면 `createdAt`과 같다. |
| `terminatedAt` | TERMINATED가 된 도메인 시각 |
| `lastTransitionAt` | 마지막 lifecycle 전이가 실제 발생한 시각 |
| `termination` | 종료 종류·사유·원인 |
| `lifecycleSequence` | 해당 scope 내부 lifecycle 전이 순번 |
| `recordVersion` | 저장된 record 변경을 구분하는 버전 |

### Termination

```text
Termination
- kind: TerminationKind
- reasonCode
- occurredAt
- causedBy?: ScopeRef | CommandRef | CorrectionRef
```

`reasonCode`는 임의 문자열이 아니라 scope별로 정의된 값을 사용한다. `FORCED` 종료에는 `causedBy`가 필수다. 이 정보가 있어야 현재 registry나 관측을 재조회하지 않고 종료 원인을 감사할 수 있다.

### ObservationRecord

```text
ObservationRecord
- state: ObservationState
- stateSince
- lastReliableObservedAt?
- reasonCodes[]
- observationSequence
```

Observation state만 변경되면 lifecycle sequence는 증가하지 않는다. 다만 record 내용이 변경됐으므로 record version과 observation sequence는 증가한다.

### LifecycleTransition

현재 snapshot만으로는 전이 원인과 시순을 재구성할 수 없으므로 lifecycle 변경은 불변 전이 사실로 표현한다.

```text
LifecycleTransition
- transitionId
- scope: ScopeRef
- sequence
- transitionCode
- fromPhase?
- toPhase
- occurredAt
- recordedAt
- cause
- termination?
```

전이 원인은 최소한 다음 종류를 구분한다.

```text
OBSERVATION
TIMER
COMMAND
PARENT_SCOPE
CORRECTION
RECOVERY
```

`transitionCode`는 scope별 언어를 사용한다. `occurredAt`은 도메인 사실 발생 시각이고 `recordedAt`은 로컬 기록 시각이다. `cause`에는 원인 종류, scope별 reason code, 원인 scope·command·correction 참조를 포함한다.

### 시간 계약

- 외부로 공개하거나 durable record에 남기는 시각은 timezone offset을 포함한 절대 시각이다.
- confirmation·clear·stationary·visit duration은 신뢰 가능한 관측 구간의 누적 시간으로 계산한다.
- timer는 단순한 `current wall clock - startedAt`으로 복원하지 않는다.
- process downtime, camera unavailable, observation `UNKNOWN` 구간은 trusted duration에 포함하지 않는다.
- 시스템 clock correction이나 Backend clock skew만으로 lifecycle 전이를 만들거나 취소하지 않는다.
- publication에 포함된 `occurredAt`은 publication revision이 생성된 뒤 변경하지 않는다.

## 버전과 순번 계약

| 값 | 증가 조건 | 용도 | 외부 전송 |
|---|---|---|---|
| `lifecycleSequence` | domain lifecycle 전이 발생 | scope 내부 전이 순서 | 직접 사용하지 않음 |
| `recordVersion` | 저장 record 변경 | 동시성·변경 감지 | 전송하지 않음 |
| `publicationRevision` | Backend에 공개할 도메인 전이 생성 | aggregate 공개 전이 순서 | API payload에 사용 |
| `deliveryAttempt` | 같은 publication의 네트워크 재시도 | 재시도·운영 진단 | domain API에 전송하지 않음 |

```text
Incident CANDIDATE 생성
  lifecycleSequence = 1, recordVersion = 1, publicationRevision = 0

Incident OPEN
  lifecycleSequence = 2, recordVersion = 2, publicationRevision = 1

카메라 장애로 observation UNKNOWN
  lifecycleSequence = 2, recordVersion = 3, publicationRevision = 1

Incident RESOLVE
  lifecycleSequence = 3, recordVersion = 4, publicationRevision = 2

RESOLVE HTTP 재시도
  publicationRevision = 2, deliveryAttempt = 2
```

네트워크 재시도는 publication revision을 증가시키지 않는다.

## 공통 불변조건

1. Scope ID는 생성 후 변경하지 않는다.
2. TERMINATED scope를 동일 ID로 재활성화하지 않는다.
3. `phase=TERMINATED`이면 `terminatedAt`과 `termination`이 필수다.
4. TERMINATED가 아니면 `terminatedAt`과 `termination`이 없어야 한다.
5. `FORCED` 종료에는 권한 있는 원인 `causedBy`가 필수다.
6. `DEGRADED`와 `UNKNOWN`은 lifecycle phase를 직접 변경하지 않는다.
7. UNKNOWN 기간은 정지·점유·확정 시간에 합산하지 않는다.
8. 재시작 직후 관측 기반 scope는 domain state를 복원하되 observation은 `UNKNOWN`으로 시작한다.
9. 중단 전후 wall-clock 차이를 신뢰 시간으로 소급 합산하지 않는다.
10. lifecycle 전이만 lifecycle sequence를 증가시킨다.
11. 저장 record가 변경될 때마다 record version을 증가시킨다.
12. 외부 공개 전이가 생길 때만 publication revision을 증가시킨다.
13. 같은 publication의 재시도는 payload와 idempotency key를 바꾸지 않는다.
14. 각 scope의 상태는 지정된 owner만 변경한다.
15. 다른 모듈은 observation·command·signal·scope transition을 전달할 뿐 상태를 직접 쓰지 않는다.
16. 상위 scope 종료는 전파 계약에 명시된 하위 scope에만 영향을 준다.
17. lifecycle state와 delivery state를 하나의 record나 enum으로 합치지 않는다.

## Scope catalog

| Scope | 분류 | Owner | 주요 책임 |
|---|---|---|---|
| `CameraObservationState` | 관측 source | `CameraHealthMonitor` | 프레임 source의 신뢰 가능성 |
| `TrackSegment` | 관측 | `TrackingAdapter` | tracker ID가 유지되는 일시 추적 구간 |
| `PhysicalVehicle` | 동일성 | `EntityResolver` | 여러 TrackSegment를 하나의 실차로 연결 |
| `EntryMatchAttempt` | workflow | `EntryMatchCoordinator` | session과 PhysicalVehicle을 연결하는 한 번의 시도 |
| `ContextBinding` | 도메인 관계 | `VehicleContextCoordinator` | PhysicalVehicle과 ParkingSession·자격 문맥 연결 |
| `ParkingSessionMirror` | 상위 업무 scope | `SessionLifecycleCoordinator` | Backend ParkingSession의 Jetson 측 mirror |
| `ZoneVisit` | 공간 사실 | `ZoneVisitTracker` | 차량의 특정 구역 연속 방문 |
| `ParkingEpisode` | 주차 사실 | `ParkingEpisodeTracker` | 정지 후보부터 주차 확정과 이동 종료까지 |
| `BlockingRelation` | 차량 간 공간 관계 | `BlockingRelationTracker` | 가해·피해 차량 사이의 출차 경로 차단 |
| `Incident` | 사건 | `IncidentReducer` | 규칙 신호를 동일 사건의 후보·OPEN·RESOLVE로 축약 |
| `MoveVerificationAttempt` | workflow | `MoveVerificationCoordinator` | Backend가 요청한 사건 재확인 |
| `OutboxRecord` | delivery workflow | `OutboxPublisher` | 공개 전이의 재시도·ACK 상태 |
| `EvidenceArtifact` | evidence workflow | `EvidenceCoordinator` | 사건 증거의 생성·상관·전달 |

`ParkingAssignment`는 독립 scope가 아니라 `ParkingEpisode`에 속한 versioned value로 둔다. `VehicleContext`는 Backend가 권한을 가진 versioned value이며 `ContextBinding`을 통해 차량 판단에 제공한다. `ZoneDefinition`은 versioned reference data다. `MotionSignal`과 `PresenceSignal`은 scope가 아니라 상태 머신에 들어가는 입력 사실이다.

### Scope lifecycle 요약 행렬

이 행렬은 각 scope가 같은 상황을 서로 다른 종료 의미로 번역하지 않도록 생성·불확실성·종료·외부 전이를 한눈에 고정한다. 상세 confirmation과 reason code는 아래 개별 상태 머신을 따른다.

| Scope | 생성·활성 기준 | `UNKNOWN` 처리 | 정상 종료 | 그 밖의 terminal | 외부 전이 |
|---|---|---|---|---|---|
| CameraObservationState | source 시작 후 `STARTING`, frame 신뢰도에 따라 active | source 자체는 `DEGRADED / UNAVAILABLE`로 표현 | 명시적 source stop | process/application 종료로 이전 source session 종료 | 없음 |
| TrackSegment | 새 tracker ID로 `TRACKING` | camera 장애 중 소실을 물리 부재로 사용하지 않음 | tracker 제거·max age 종료 | tracker reset·process restart | 없음 |
| PhysicalVehicle | 매칭되지 않은 segment로 후보 생성, 동일성 확인 후 active | identity와 child 유지, timer·판정 보류 | child·binding·미완료 publication이 없는 안전한 retire | 후보 취소, 근거가 있는 identity merge·correction | 없음 |
| EntryMatchAttempt | 입차 문맥 접수로 `PENDING` | 기한 전 유지, 기한 종료 시 원인을 구분한 `EXPIRED` | 신뢰 가능한 연결로 `MATCHED` | `EXPIRED / FAILED`; Session 선종료·유효 command 취소로 `CANCELED` | terminal 매칭 결과 |
| ContextBinding | Match 성공으로 `BOUND` | 물리 관측 불확실만으로 종료하지 않음 | 독립적인 물리 정상 종료 없음 | Session 종료·binding 재할당·authoritative invalidation | 없음 |
| ParkingSessionMirror | 입차 문맥을 복구 가능하게 접수하면 `ACTIVE` | 출차를 추정하지 않고 ACTIVE 유지 | Jetson 출차 확인 | Backend authoritative `CLOSED` | Jetson 출차 확인 때만 EXIT |
| ZoneVisit | entry threshold로 `ENTERING`, 확인 후 `INSIDE` | lifecycle 유지, entry·exit timer 정지 | 신뢰 가능한 이탈로 `ENDED` | 후보 `CANCELED`; Session 종료·권한 있는 zone definition 변경으로 `FORCED` | 방문 기반 Incident RESOLVE를 유발할 수 있음 |
| ParkingEpisode | trusted stationary로 `STOP_PENDING`, 확인 후 `PARKED` | lifecycle·assignment 유지, timer 정지 | 신뢰 가능한 이동으로 `ENDED` | 후보 `CANCELED`; Session 종료로 `FORCED` | PARKED; 정상 이동 종료면 UNPARKED |
| BlockingRelation | subject·victim·corridor 차단 후보로 생성 | relation 유지, clear timer 정지 | 차단 해소로 `ENDED` | 후보 `CANCELED`; 관련 Session 종료·권한 있는 corridor 정정으로 `FORCED` | DOUBLE_PARKING Incident 전이의 lifetime 근거 |
| Incident | `MATCHED` signal로 후보, confirm 후 OPEN | 후보·OPEN 유지, confirm·clear timer 정지 | 원인 해소 또는 lifetime scope의 정상 종료로 `RESOLVED` | 후보 `CANCELED`; Session 종료·authoritative correction으로 `FORCED` | OPEN / RESOLVE |
| MoveVerificationAttempt | Backend command 접수로 `ACCEPTED` | deadline까지 판단 불가하면 결과 `UNKNOWN` | immutable 결과로 `COMPLETED` | 유효 command 취소로 `CANCELED`, 계약 오류로 `FAILED` | RESOLVED / STILL_ACTIVE / UNKNOWN |
| OutboxRecord | publication과 같은 consistency boundary에서 생성 | observation 축 적용 안 함 | Backend 적용 확인으로 `DELIVERED` | 강제 삭제 없음; DEAD_LETTER도 active 책무 | 원본 publication 전달 |
| EvidenceArtifact | Incident revision의 capture 요청으로 생성 | source 불가를 Incident 종료로 전파하지 않음 | 업로드 `DELIVERED` | 생성 전 `EXPIRED`, 복구 불가 `FAILED`; 부모 종료로 취소하지 않음 | Evidence upload 또는 unavailable 확인 |

## CameraObservationState

### 목적과 owner

`CameraObservationState`는 해당 카메라 source가 현재 신뢰 가능한 프레임을 공급하는지 표현한다. 일반 차량 도메인 scope라기보다 다른 관측 scope의 신뢰도를 공급하는 source 상태 머신이다. Owner는 `CameraHealthMonitor`다.

### 상태

| Domain state | Phase | 의미 |
|---|---|---|
| `STARTING` | PROVISIONAL | 장치 초기화와 첫 정상 frame을 기다림 |
| `AVAILABLE` | ACTIVE | 신뢰 가능한 frame을 정상 공급 |
| `DEGRADED` | ACTIVE | frame 손실·지연·품질 저하가 있으나 일부 관측 가능 |
| `UNAVAILABLE` | ACTIVE | 신뢰 가능한 frame을 공급하지 못함 |
| `STOPPED` | TERMINATED | 명시적인 application·source 종료 |

### 전이 계약

```text
STARTING
  -> AVAILABLE    정상 frame 확인
  -> DEGRADED     불완전한 frame만 확인
  -> UNAVAILABLE  초기화 실패나 input timeout

AVAILABLE
  -> DEGRADED     품질 저하 확인 구간 충족
  -> UNAVAILABLE  heartbeat·input 중단 확인
  -> STOPPED      명시적 source 종료

DEGRADED
  -> AVAILABLE    회복 확인 구간 충족
  -> UNAVAILABLE  중단 확인 구간 충족
  -> STOPPED      명시적 source 종료

UNAVAILABLE
  -> DEGRADED     프레임 공급 재개, 아직 회복 확인 전
  -> AVAILABLE    회복 확인 구간 충족
  -> STOPPED      명시적 source 종료
```

첫 frame 한 장만으로 `UNAVAILABLE -> AVAILABLE`을 확정하지 않는다. 재시작하면 새 camera source session을 생성하고 `STARTING`에서 시작한다. Source 상태 변경은 다른 scope에 observation 품질로만 전파하며 Backend 도메인 출력을 직접 만들지 않는다.

## TrackSegment

### 목적과 owner

`TrackSegment`는 ByteTrack 등 tracker가 하나의 tracker ID로 유지하는 일시적인 추적 구간이다. Owner는 `TrackingAdapter`다.

### 상태와 전이

| Domain state | Phase | 의미 |
|---|---|---|
| `TRACKING` | ACTIVE | 현재 frame에서 tracker가 추적 중 |
| `LOST_PENDING` | ACTIVE | 일시 미탐지지만 tracker 보존 기간 내 |
| `ENDED` | TERMINATED | 해당 tracker segment가 끝남 |

```text
새 tracker ID -> TRACKING
TRACKING -> LOST_PENDING  frame에서 일시 미탐지
LOST_PENDING -> TRACKING  동일 tracker ID 재탐지
TRACKING | LOST_PENDING -> ENDED  tracker removed, max age 초과, tracker reset
```

`TrackSegment.ENDED`는 물리 차량이 떠났다는 사실이 아니다. 종료 사실은 `EntityResolver`에만 전달하고 `ZoneVisit`, `ParkingEpisode`, `Incident`를 직접 종료하지 않는다. 카메라 unavailable 중 max age가 지난 것도 물리적 부재 증거로 사용하지 않는다. TrackSegment는 재시작 후 복원하지 않고 새 segment를 생성한다.

## PhysicalVehicle

### 목적과 owner

`PhysicalVehicle`은 여러 `TrackSegment`를 Jetson이 하나의 실차로 판단하는 기간의 동일성이다. Owner는 `EntityResolver`다.

### 상태

| Domain state | Phase | 의미 |
|---|---|---|
| `CANDIDATE` | PROVISIONAL | 새 실차 identity 가설이 아직 안정되지 않음 |
| `ACTIVE` | ACTIVE | 도메인에서 하나의 물리 차량으로 사용 가능 |
| `RETIRED` | TERMINATED | 이 identity를 새 관측에 더 이상 사용하지 않음 |

### 전이 계약

```text
매칭되지 않은 TrackSegment -> CANDIDATE
CANDIDATE -> ACTIVE   identity 확인 조건 충족
CANDIDATE -> RETIRED  오탐지·소실로 가설 취소
CANDIDATE -> RETIRED  기존 PhysicalVehicle과 동일성 확인 후 기존 identity에 segment 연결

ACTIVE + 새 TrackSegment -> ACTIVE
ACTIVE + 모든 segment 소실 -> ACTIVE / observation DEGRADED 또는 UNKNOWN
ACTIVE + 재식별 성공 -> ACTIVE / observation OBSERVED
ACTIVE -> RETIRED  안전한 identity 정리 조건 충족
```

`CANDIDATE -> RETIRED`에서 가설을 취소한 경우 termination kind는 `CANCELED`다. ACTIVE identity는 다음을 모두 만족할 때만 정상적으로 retire할 수 있다.

- 활성 `ContextBinding`이 없다.
- non-terminal `ZoneVisit`, `ParkingEpisode`, `BlockingRelation`, `Incident` 등 이 identity를 수명 범위로 사용하는 child scope가 없다.
- 재식별 보존 기간이 만료됐다.
- 공개된 child의 미확인 상태나 전달하지 못한 전이가 없다.

세션에 연결됐거나 공개된 사실을 보유한 차량은 장기 미탐지라도 `ACTIVE + UNKNOWN`으로 보존한다. 메모리 cache에서는 내릴 수 있지만 lifecycle을 종료하지 않는다.

재시작 후에는 세션이나 공개 사실에 연결된 identity를 observation `UNKNOWN`으로 복원한다. 위치만으로 다른 차량에 기존 상태를 자동 상속하지 않는다.

불변조건:

- 하나의 활성 TrackSegment는 동시에 하나의 PhysicalVehicle에만 연결된다.
- 하나의 활성 ParkingSession은 동시에 하나의 PhysicalVehicle에만 binding된다.
- `RETIRED`를 재활성화하지 않는다.
- identity merge·correction은 successor와 근거를 명시하고 묵시적으로 상태를 옮기지 않는다.

## EntryMatchAttempt

### 목적과 owner

`EntryMatchAttempt`는 Backend가 생성한 `sessionId`를 하나의 `physicalVehicleId`와 연결하려는 한 번의 제한 시간 workflow다. Owner는 `EntryMatchCoordinator`다.

### 상태와 전이

| Domain state | Phase | 의미 |
|---|---|---|
| `PENDING` | ACTIVE | 매칭 창 내에서 후보를 평가 중 |
| `MATCHED` | TERMINATED | 하나의 PhysicalVehicle과 신뢰 가능하게 연결됨 |
| `EXPIRED` | TERMINATED | 매칭 기한이 만료됨 |
| `FAILED` | TERMINATED | 복구 불가능한 계약·데이터 오류 |
| `CANCELED` | TERMINATED | 매칭 전 ParkingSession 종료 등으로 진행 근거가 사라짐 |

```text
입차 문맥 접수 -> PENDING
PENDING -> MATCHED   단일 PhysicalVehicle과 신뢰 가능한 매칭
PENDING -> EXPIRED   매칭 기한 만료
PENDING -> FAILED    복구 불가능한 계약·데이터 오류
PENDING -> CANCELED  ParkingSession 선종료·명시적 command 취소
```

카메라가 unavailable이면 즉시 실패나 매칭 성공으로 번역하지 않는다. 기한이 남았다면 `PENDING`을 유지하고, 기한이 끝나면 `EXPIRED`로 종료하되 사유를 `NO_VEHICLE_MATCH`, `SOURCE_UNAVAILABLE`, `AMBIGUOUS_MATCH`로 구분한다.

불변조건:

- 동일 session의 활성 `PENDING` attempt는 최대 하나다.
- 재시도는 `(sessionId, matchAttempt)`의 `matchAttempt`를 증가시켜 새 scope로 생성한다.
- 같은 idempotency key의 재전달은 기존 attempt 결과를 반환한다.
- `MATCHED`된 session에 새 attempt를 생성하지 않는다.
- 접수 응답을 확정하기 전에 attempt가 복구 가능한 상태여야 한다.

`MATCHED`, `EXPIRED`, `FAILED`, `CANCELED`는 서로 구분되는 terminal 결과다. 특히 `CANCELED`를 차량 부재나 매칭 오류로 번역하지 않으며, 매칭 결과 조회 계약에서도 구분할 수 있어야 한다.

## ContextBinding

### 목적과 owner

`ContextBinding`은 `PhysicalVehicle`과 `ParkingSession`을 연결하고 `vehicleId`, 전기차·장애인 차량 자격 문맥을 제공한다. Owner는 `VehicleContextCoordinator`다.

### 상태와 전이

| Domain state | Phase | 의미 |
|---|---|---|
| `BOUND` | ACTIVE | PhysicalVehicle과 ParkingSession이 활성으로 연결됨 |
| `ENDED` | TERMINATED | 연결이 더 이상 유효하지 않음 |

```text
EntryMatchAttempt.MATCHED -> BOUND
BOUND + 동일 차량 자격 정정 -> BOUND / contextVersion 증가
BOUND -> ENDED  CONTEXT_REASSIGNED
BOUND -> ENDED  INVALIDATED
BOUND -> ENDED  SESSION_EXITED
```

자격 정보 정정은 binding 종료가 아니라 동일 binding의 `contextVersion` 변경이며 restricted-zone 규칙 재평가 입력이다. 반면 연결 대상 PhysicalVehicle을 바꾸는 것은 기존 binding을 종료하고 새 binding을 만드는 정정이다. 기존 차량의 ParkingEpisode·Incident를 새 차량에 자동 상속하지 않는다.

TrackSegment 종료, PhysicalVehicle 미탐지, 카메라 장애로 binding을 종료하지 않는다. 동일 session과 PhysicalVehicle에 활성 binding은 각각 최대 하나다.

## ParkingSessionMirror

### 목적과 owner

`ParkingSessionMirror`는 Backend가 생성하고 관리하는 ParkingSession의 Jetson 측 상위 scope다. Owner는 `SessionLifecycleCoordinator`다. ParkingEpisode와 구분하며, 하나의 ParkingSession 안에 여러 ParkingEpisode가 순차적으로 생길 수 있다.

### 상태와 전이

| Domain state | Phase | 의미 |
|---|---|---|
| `ACTIVE` | ACTIVE | Backend의 주차 세션이 현재 유효함 |
| `EXITED` | TERMINATED | 세션의 현장 수명이 끝남 |

```text
입차 문맥을 복구 가능하게 접수 -> ACTIVE
ACTIVE -> EXITED  신뢰 가능한 출차 확인
ACTIVE -> EXITED  Backend authoritative closure
```

매칭 성공 전에도 session mirror는 존재할 수 있다. 출구 근처 TrackSegment 소실이나 카메라 장애는 EXIT가 아니다. 출차 방향과 EXIT 조건을 확인하지 못하면 `ACTIVE`를 유지한다.

Backend가 먼저 종료를 확정한 경우 Jetson이 EXIT publication을 새로 만들지 않는다. `EXITED`된 session에 늦게 도착한 PARKED나 Incident OPEN을 적용하지 않는다. Session 종료의 하위 scope 영향은 전파 계약에서 정의한다.

## ZoneVisit

### 목적과 owner

`ZoneVisit`은 하나의 PhysicalVehicle이 특정 버전의 구역 안에 진입하기 시작한 시점부터 이탈이 확정될 때까지의 연속 공간 관계다. Owner는 `ZoneVisitTracker`다.

### 상태

| Domain state | Phase | 의미 |
|---|---|---|
| `ENTERING` | PROVISIONAL | 진입 threshold를 넘었지만 확인 시간 전 |
| `INSIDE` | ACTIVE | 구역 안에 있음이 확인됨 |
| `EXITING` | ACTIVE | 해제 threshold 미만이지만 이탈 확인 시간 전 |
| `ENDED` | TERMINATED | 확인된 이탈 또는 권한 있는 강제 종료 |
| `CANCELED` | TERMINATED | ENTERING 후보가 확정 전 해제됨 |

### 전이 계약

```text
OUTSIDE에서 entry threshold 충족 -> 새 ZoneVisit / ENTERING

ENTERING
  -> INSIDE    trusted entry confirmation duration 충족
  -> CANCELED  신뢰 가능한 presence 해제
  -> ENTERING  observation UNKNOWN, timer 정지

INSIDE
  -> EXITING   exit threshold 미만
  -> INSIDE    presence 유지
  -> INSIDE    observation UNKNOWN, lifecycle 유지

EXITING
  -> ENDED     trusted exit confirmation duration 충족
  -> INSIDE    presence 회복
  -> EXITING   observation UNKNOWN, timer 정지
```

### Zone definition snapshot

ZoneVisit은 진입 당시 적용한 구역 정의의 최소 snapshot을 보존한다.

```text
zoneId
zoneDefinitionVersion
zoneType
allowedMinutes?
rule-relevant policy snapshot
```

이 snapshot은 종료 시점에 현재 `ZoneRegistry`를 재조회해 rule code를 재구성하지 않기 위한 것이다. 전체 geometry를 각 visit에 복제해야 한다는 뜻은 아니지만, `zoneDefinitionVersion`은 진행 중 visit 동안 immutable geometry를 다시 얻을 수 있는 참조여야 한다. 최신 mutable definition만 남기고 진행 중 visit의 기준 geometry를 잃어서는 안 된다.

Active visit의 `RuleEvaluator`도 이 snapshot의 `zoneType`, `allowedMinutes`, policy version을 사용해 적용 규칙을 선택한다. 현재 registry는 새 관측의 geometry와 새 definition 적용 여부를 제공할 뿐, 진행 중 visit의 규칙 identity를 조용히 바꾸지 않는다.

권한 있는 설정 전이로 구역 정의가 교체·삭제됐음이 확인되면 기존 visit을 `FORCED` 종료하고, 새 정의에서도 presence가 성립하면 새 `zoneVisitId`를 생성한다. 반면 현재 `ZoneRegistry` 조회 실패, 일시적인 설정 미로딩, dependency 장애는 정의 삭제가 아니다. 이 경우 visit lifecycle을 유지하고 observation을 `UNKNOWN / DEPENDENCY_UNAVAILABLE`로 둔다. `(physicalVehicleId, zoneId, zoneDefinitionVersion)`당 non-terminal visit은 최대 하나다. UNKNOWN 기간은 진입·이탈 확인 시간에 포함하지 않는다.

`ZoneVisitEnded`는 visit ID, 종료 사유, 발생 시각을 함께 전달한다. 종료된 visit에서 현재 registry를 조회해 `IncidentSignal(NOT_MATCHED)`를 재생성하지 않는다. 재진입은 새 visit이다.

## ParkingEpisode

### 목적과 owner

`ParkingEpisode`는 차량이 정지 후보가 된 시점부터 주차 확정과 후속 이동 확인까지의 연속된 정지·주차 행위다. Owner는 `ParkingEpisodeTracker`다.

### 상태

| Domain state | Phase | 의미 |
|---|---|---|
| `STOP_PENDING` | PROVISIONAL | 정지는 관측됐지만 주차 확인 시간 전 |
| `PARKED` | ACTIVE | 신뢰 가능한 정지 누적 조건을 충족해 주차가 확정됨 |
| `MOVE_PENDING` | ACTIVE | 이동 신호는 있지만 주차 종료 확인 전 |
| `ENDED` | TERMINATED | 이동 또는 권한 있는 상위 종료로 episode가 끝남 |
| `CANCELED` | TERMINATED | STOP_PENDING 후보가 주차 확정 전 해제됨 |

### 전이 계약

```text
MOVING에서 trusted STATIONARY 확인 -> 새 ParkingEpisode / STOP_PENDING

STOP_PENDING
  -> PARKED    trusted stationary duration이 parking confirmation 기준 충족
  -> CANCELED  movement confirmation 충족
  -> STOP_PENDING  observation UNKNOWN, timer 정지

PARKED
  -> MOVE_PENDING  movement signal 시작
  -> PARKED        stationary 유지
  -> PARKED        observation UNKNOWN, lifecycle 유지

MOVE_PENDING
  -> ENDED   trusted movement confirmation duration 충족
  -> PARKED  stationary 회복
  -> MOVE_PENDING  observation UNKNOWN, timer 정지
```

ParkingSession EXIT는 허용된 강제 종료다.

- `STOP_PENDING -> CANCELED / FORCED`
- `PARKED | MOVE_PENDING -> ENDED / FORCED`

`STOP_PENDING -> PARKED`는 PARKED 공개 전이를, 신뢰 가능한 이동에 따른 `PARKED | MOVE_PENDING -> ENDED`는 UNPARKED 공개 전이를 생성한다. Session EXIT로 강제 종료된 경우에는 별도 UNPARKED를 공개하지 않는다.

ContextBinding이 아직 없는 채로 PARKED가 확정될 수 있다. 이 경우 내부 PARKED 사실은 유지하고 외부 publication만 문맥 연결까지 보류한다.

ParkingEpisode는 시작 당시 적용한 최소 policy snapshot을 보존한다.

```text
parkingPolicyVersion
parkingConfirmDuration = 600 seconds
movement confirmation policy
trusted-time accumulation policy
```

600초는 ParkingEpisode에서만 주차 확정에 사용한다. ZoneVisit의 존재·전용구역 무자격·EV 초과 점유·구역 소유자 선정 조건으로 재사용하지 않는다. Policy가 바뀌어도 진행 중 episode의 과거 누적 시간을 새 기준으로 소급 재해석하지 않는다.

### ParkingAssignment와 BlockingRelation

ParkingAssignment는 episode에 속한 versioned value다. `STOP_PENDING`에서 후보를 계산할 수 있지만 `PARKED`에서 대표 assignment를 확정한다. bbox jitter만으로 assignment를 계속 바꾸지 않는다. 구역 외 주차는 `zoneId=null`인 확정 assignment로 표현할 수 있다.

**ParkingEpisode 종료는 BlockingRelation 종료가 아니다.** Episode 종료는 차단 관계의 재평가 trigger일 뿐이다. 차량이 움직여 기존 ParkingEpisode는 끝났지만 여전히 다른 차량의 출차 경로를 막을 수 있으므로, geometry와 관계 조건을 다시 확인한 뒤에만 BlockingRelation을 종료한다.

불변조건:

- PhysicalVehicle당 non-terminal ParkingEpisode는 최대 하나다.
- 하나의 episode에서 PARKED publication은 최대 한 번이다.
- UNKNOWN 기간과 process downtime을 정지 누적 시간에 포함하지 않는다.
- ENDED episode를 재활성화하지 않는다.

## BlockingRelation

### 목적과 owner

`BlockingRelation`은 특정 subject 차량이 victim 차량의 출차 가능 경로를 연속적으로 막는 공간 관계다. Owner는 `BlockingRelationTracker`다. 단순히 두 bbox가 하나의 주차면을 겹쳤다는 사실로 생성하지 않는다.

### 상태와 전이

| Domain state | Phase | 의미 |
|---|---|---|
| `CANDIDATE` | PROVISIONAL | 차단 가능성은 있지만 확인 전 |
| `BLOCKING` | ACTIVE | 출차 경로 차단이 확인됨 |
| `CLEAR_PENDING` | ACTIVE | 해소 신호는 있지만 확인 전 |
| `ENDED` | TERMINATED | 차단 관계 해소가 확인되거나 권한 있는 강제 종료 |
| `CANCELED` | TERMINATED | 후보가 확정 전 해제됨 |

```text
possible blocking 탐지 -> CANDIDATE

CANDIDATE
  -> BLOCKING  trusted blocking confirmation duration 충족
  -> CANCELED  신뢰 가능한 관계 해제
  -> CANDIDATE observation UNKNOWN, timer 정지

BLOCKING
  -> CLEAR_PENDING  clear signal 확인
  -> BLOCKING       blocking 유지
  -> BLOCKING       observation UNKNOWN, lifecycle 유지

CLEAR_PENDING
  -> ENDED    trusted clear confirmation duration 충족
  -> BLOCKING blocking 회복
  -> CLEAR_PENDING observation UNKNOWN, timer 정지
```

관계의 동일성은 최소한 subject PhysicalVehicle, victim PhysicalVehicle, egress corridor를 포함한다. 생성 당시 ParkingEpisode ID는 근거로 보존할 수 있지만 relation의 lifetime을 자동으로 ParkingEpisode에 종속시키지 않는다.

다음은 재평가 trigger이지 즉시 종료 조건이 아니다.

- subject ParkingEpisode 종료
- victim ParkingEpisode 종료
- `movementDetected=true`

신뢰 가능한 geometry에서 차단 불성립이 확인될 때만 정상 종료한다. Subject나 victim ParkingSession EXIT, egress corridor 정의 제거, 관리자 공간 정정은 허용된 강제 종료다.

불변조건:

- subject와 victim은 같을 수 없다.
- 동일 subject·victim·corridor 조합의 non-terminal relation은 최대 하나다.
- `BLOCKING`이 종료된 후 다시 차단이 성립하면 새 `blockingRelationId`를 생성한다.
- 한쪽 차량의 관측이 UNKNOWN이면 relation을 종료하지 않는다.

## Incident

### 목적과 owner

`Incident`는 규칙의 현재 성립 신호를 시간에 걸친 동일 사건의 후보·OPEN·RESOLVE로 축약한다. `IncidentReducer`만 Incident 상태를 변경한다. `RuleEvaluator`는 상태를 보존하지 않고 `IncidentSignal`만 생성한다.

### IncidentSignal 삼상태 계약

`matched: bool`로는 규칙 불성립과 판단 불가를 구분할 수 없으므로 다음 세 값을 사용한다.

| Match state | 의미 | Reducer 기본 처리 |
|---|---|---|
| `MATCHED` | 현재 신뢰 가능한 사실에서 규칙이 성립 | 후보 생성·유지, 확정 조건 충족 시 OPEN |
| `NOT_MATCHED` | 현재 신뢰 가능한 사실에서 규칙이 불성립 | 후보 취소 또는 OPEN 사건의 clear 확인 |
| `UNKNOWN` | 성립과 불성립 모두 확정할 수 없음 | lifecycle 유지, 확정·해소 timer 정지 |

Signal은 최소한 incident key, match state, confirmable 여부, 관측 시각, evidence를 갖는다. 자격 정보가 UNKNOWN이거나 필수 공간 관계를 관측할 수 없으면 `NOT_MATCHED`가 아니라 `UNKNOWN`이다.

### 상태와 전이

| Domain state | Phase | 의미 |
|---|---|---|
| `CANDIDATE` | PROVISIONAL | 규칙 성립 신호는 있지만 공개 확정 전 |
| `OPEN` | ACTIVE | 공개 조건을 충족해 Backend에 전달 가능한 사건 |
| `CLEAR_PENDING` | ACTIVE | 불성립 신호는 있지만 해소 확인 전 |
| `RESOLVED` | TERMINATED | OPEN된 사건의 원인 해소가 확인됨 |
| `CANCELED` | TERMINATED | OPEN 전 후보가 취소됨 |

```text
활성 incident 없음 + MATCHED -> CANDIDATE

CANDIDATE
  -> OPEN      confirmable + confirmation condition 충족
  -> CANCELED  trusted NOT_MATCHED
  -> CANDIDATE UNKNOWN, timer 정지

OPEN
  -> OPEN           MATCHED
  -> CLEAR_PENDING  trusted NOT_MATCHED
  -> RESOLVED       lifetime scope authoritative 종료
  -> OPEN           UNKNOWN, lifecycle 유지

CLEAR_PENDING
  -> RESOLVED  trusted clear confirmation duration 충족
  -> OPEN      MATCHED 재확인
  -> CLEAR_PENDING UNKNOWN, timer 정지
```

다음 lifetime 종료 input은 종료 시점에 현재 규칙을 재구성하지 않고 Incident를 즉시 해소할 수 있다.

- lifetime scope인 ZoneVisit의 확정 종료
- lifetime scope인 ParkingEpisode의 확정 종료
- lifetime scope인 BlockingRelation의 확정 종료
- ParkingSession EXIT

IncidentReducer는 OPEN 당시 보존한 lifetime scope 연결을 사용한다. 현재 ZoneRegistry나 RuleEvaluator로 `NOT_MATCHED` signal을 재구성하지 않는다.

자격·문맥 정정은 lifetime 종료가 아니다. `RuleEvaluator`가 정정된 context로 현재 규칙을 다시 평가하고, 신뢰 가능한 `NOT_MATCHED`를 만들었을 때만 Reducer가 clear·RESOLVE를 진행한다.

### 사건 동일성과 출력

Incident key는 다음을 포함한다.

```text
ruleCode
exactly one lifetimeScope
subject
victim?
```

| 전이 | 외부 publication |
|---|---|
| `CANDIDATE -> OPEN` | `OPEN`, publication revision 증가 |
| `OPEN` 또는 `CLEAR_PENDING`에서 `RESOLVED` | `RESOLVE`, publication revision 증가 |
| `CANDIDATE -> CANCELED` | 없음 |
| observation `UNKNOWN` | 없음 |

해소된 사건에 같은 규칙이 재성립하면 기존 Incident를 재활성화하지 않고 새 `incidentId`를 생성한다. 단, 신뢰 가능한 clear 구간과 적용되는 lifetime scope 조건을 통과해야 하며 늦게 도착한 과거 signal로 새 사건을 만들지 않는다.

불변조건:

- Incident에는 lifetime scope가 정확히 하나 존재한다.
- OPEN과 RESOLVE는 같은 `incidentId`를 사용한다.
- publication revision은 공개 전이에서만 증가한다.
- UNKNOWN으로 Incident를 RESOLVE하지 않는다.
- RESOLVED Incident를 재활성화하지 않는다.
- RuleEvaluator와 Pipeline은 Incident 상태를 직접 변경하지 않는다.

## MoveVerificationAttempt

### 목적과 owner

`MoveVerificationAttempt`는 Backend가 지정한 Incident의 현재 현장 상태를 요청 이후 관측으로 재확인하는 한 번의 workflow다. Owner는 `MoveVerificationCoordinator`다.

### 상태와 결과

| Domain state | Phase | 의미 |
|---|---|---|
| `ACCEPTED` | ACTIVE | command를 접수했지만 현장 확인 시작 전 |
| `CHECKING` | ACTIVE | 요청 이후의 신뢰 가능한 관측을 수집·평가 중 |
| `COMPLETED` | TERMINATED | 해당 attempt 결과가 확정됨 |
| `CANCELED` | TERMINATED | Backend 취소 등으로 시도가 취소됨 |
| `FAILED` | TERMINATED | 대상 계약 오류 등으로 시도를 진행할 수 없음 |

`COMPLETED` 결과는 다음 세 값이다.

| Result | 의미 |
|---|---|
| `RESOLVED` | 대상 Incident 원인이 해소됐거나 session EXIT로 종료됨 |
| `STILL_ACTIVE` | 신뢰 가능한 재평가에서 규칙 원인이 여전히 성립 |
| `UNKNOWN` | deadline까지 판단할 만한 관측을 얻지 못함 |

```text
command를 복구 가능하게 접수 -> ACCEPTED

ACCEPTED
  -> COMPLETED / RESOLVED  Incident가 이미 RESOLVED
  -> CHECKING              대상과 요청이 유효
  -> FAILED                request·incident 계약 오류

CHECKING
  -> COMPLETED / RESOLVED      Incident 해소 확인
  -> COMPLETED / STILL_ACTIVE  trusted rule match 유지 확인
  -> COMPLETED / UNKNOWN       deadline까지 신뢰 관측 부족
  -> COMPLETED / RESOLVED      ParkingSession EXIT
  -> CANCELED                  유효한 취소 command
```

`movementDetected`는 결과가 아니라 evidence다. 차량이 움직였어도 전용구역 내부에 남았거나 차단 관계를 유지하면 `STILL_ACTIVE`다. 카메라 장애나 TrackSegment 소실은 `RESOLVED`가 아니라 `UNKNOWN`의 근거다.

Attempt 동일성은 `(requestId, verificationAttempt)`다. 동일 attempt 결과는 불변이다. 기존 attempt가 활성인 동안 더 높은 attempt를 묵시적으로 덮어쓰지 않는다. 재시작 공백을 관측 시간으로 계산하지 않고 deadline까지 새 관측이 부족하면 `UNKNOWN`을 반환한다.

## OutboxRecord

### 목적과 owner

`OutboxRecord`는 이미 확정된 도메인 publication을 Backend에 멱등적으로 전달하는 workflow다. 도메인 사실을 생성·수정하지 않는다. Owner는 `OutboxPublisher`다.

### 상태와 전이

| Delivery state | Phase | 의미 |
|---|---|---|
| `PENDING` | ACTIVE | 전송 가능한 publication이 대기 중 |
| `IN_FLIGHT` | ACTIVE | 하나의 publisher가 전송 중 |
| `RETRY_WAIT` | ACTIVE | 일시 실패 후 다음 시도 시각 대기 |
| `DEAD_LETTER` | ACTIVE | 자동 재시도를 멈추고 운영 개입을 기다리는 미완료 책무 |
| `DELIVERED` | TERMINATED | Backend가 적용한 결과를 확인함 |

```text
publication과 함께 생성 -> PENDING
PENDING | RETRY_WAIT -> IN_FLIGHT  전송 claim
IN_FLIGHT -> DELIVERED             적용 ACK 확인
IN_FLIGHT -> RETRY_WAIT            재시도 가능한 실패
PENDING | RETRY_WAIT -> DEAD_LETTER  자동 재시도 정책 소진·영구 오류
DEAD_LETTER -> RETRY_WAIT          명시적인 운영 재처리
```

`DEAD_LETTER`는 종료된 성공이 아니라 아직 해소하지 못한 전달 책무이므로 ACTIVE로 둔다. 자동 삭제하지 않고, 운영 재처리 전에도 기존 publication revision·payload·idempotency key를 변경하지 않는다.

불변조건:

- 같은 aggregate·publication revision·destination의 publication은 하나다.
- enqueue 후 payload는 불변이며 재시도 시 현재 domain state로 재생성하지 않는다.
- 같은 publication revision은 같은 idempotency key를 계속 사용한다.
- 전송 실패는 원본 domain lifecycle을 rollback하지 않는다.
- `DELIVERED` record를 재활성화하지 않는다.

## EvidenceArtifact

### 목적과 owner

`EvidenceArtifact`는 특정 Incident publication을 뒷받침하는 이미지와 metadata의 생성·상관·전달 workflow다. Owner는 `EvidenceCoordinator`다. Incident 판단자나 상태 owner가 아니다.

### 상태와 전이

| Workflow state | Phase | 의미 |
|---|---|---|
| `CAPTURE_REQUESTED` | ACTIVE | 특정 Incident revision의 증거 캡처를 요청함 |
| `READY` | ACTIVE | 이미지와 metadata가 유효하게 생성됨 |
| `WAITING_EVENT_ID` | ACTIVE | Incident OPEN ACK의 Backend `eventId`를 기다림 |
| `UPLOAD_PENDING` | ACTIVE | Backend 업로드 가능 상태 |
| `RETRY_WAIT` | ACTIVE | 일시 업로드 실패 후 재시도 대기 |
| `DELIVERED` | TERMINATED | Backend 업로드 ACK를 확인함 |
| `FAILED` | TERMINATED | 손상·손실 등으로 artifact를 더 이상 전달할 수 없음 |
| `EXPIRED` | TERMINATED | 유효한 artifact 생성 전의 명시적 capture 기한이 만료됨 |

```text
증거 캡처 요청 -> CAPTURE_REQUESTED
CAPTURE_REQUESTED -> READY    유효한 artifact 생성
CAPTURE_REQUESTED -> FAILED   생성 불가
CAPTURE_REQUESTED -> EXPIRED  artifact 생성 전 capture deadline 만료
READY -> WAITING_EVENT_ID     Backend eventId 없음
READY | WAITING_EVENT_ID -> UPLOAD_PENDING  eventId 확보
UPLOAD_PENDING -> DELIVERED   업로드 ACK
UPLOAD_PENDING -> RETRY_WAIT  재시도 가능한 실패
RETRY_WAIT -> UPLOAD_PENDING  재시도 시각 도달
RETRY_WAIT -> FAILED          복구 불가능한 업로드 오류
```

한 번 `READY`가 된 artifact는 Incident RESOLVE나 Session EXIT를 이유로 취소·만료시키지 않고 기존 OPEN 근거로 전달한다. `EXPIRED`는 아직 유효한 artifact가 생성되지 않은 capture 요청에만 허용한다. Evidence 실패는 Incident lifecycle을 rollback하지 않는다. Artifact는 `evidenceId`, `incidentId`, incident publication revision, capture 시각, 유형, content checksum을 상관 정보로 보존한다.

`FAILED`는 성공 ACK와 같지 않다. 전달 가능한 binary가 영구 손실·손상됐다면 복구할 수 없는 이유와 마지막으로 검증한 metadata를 보존하고, Backend 또는 명시된 운영 권한자가 `EVIDENCE_UNAVAILABLE` 처리를 확인해야 부모 Incident의 보존을 더 이상 막지 않는다. 이 확인은 Incident를 취소하거나 evidence가 전달됐다고 가장하는 행위가 아니다.

## Scope owner 경계

```text
TrackingAdapter
  -> TrackObservation과 TrackSegmentTransition 생성

EntityResolver
  -> PhysicalVehicle 동일성 변경

ZoneVisitTracker / ParkingEpisodeTracker / BlockingRelationTracker
  -> 각자 scope 상태 변경

RuleEvaluator
  -> 현재 규칙을 삼상태로 평가하고 IncidentSignal 생성
  -> Incident 상태는 변경하지 않음

IncidentReducer
  -> IncidentSignal과 scope termination을 Incident 상태로 축약

Application pipeline
  -> 순서와 오류 경계를 조립
  -> 개별 scope 상태를 직접 변경하지 않음

OutboxPublisher
  -> 전달 상태만 변경
  -> 전송 결과로 domain lifecycle을 다시 판정하지 않음
```

이 경계를 지켜야 tracker 소실이 주차 종료로, 카메라 장애가 Incident RESOLVE로, HTTP 실패가 도메인 상태 rollback으로 번역되는 것을 방지할 수 있다.
