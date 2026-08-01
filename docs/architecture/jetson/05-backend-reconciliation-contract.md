# Jetson–Backend 상태 Reconciliation 계약

> 상태: Draft · 관련 이슈: S15P11E202-461 · 범위: Jetson과 Backend 사이의 상태 권한, 비교, 복구, 충돌 및 retention 계약 · 비범위: 구현 저장소, DB schema, HTTP controller 구현, 테스트·배포·migration 계획

## 목적

Reconciliation은 Jetson과 Backend가 보유한 상태가 다를 때, 각 상태의 authoritative owner와 이미 공개된 전이의 revision을 기준으로 일관성을 회복하는 운영 계약이다.

다음 상황을 복구 대상으로 한다.

- Jetson 프로세스 재시작
- Backend 연결 회복 또는 장기 offline 후
- Backend가 요청을 처리했지만 Jetson이 ACK를 받지 못한 상황
- outbox `DEAD_LETTER`
- Jetson local state 복구 또는 device 교체
- Backend의 차량 자격·세션 상태 정정
- Backend command 누락 또는 Jetson 결과 미적용
- terminal record의 compaction·purge 전 최종 상태 확인

Reconciliation은 새로운 주차·위반 사실을 판정하는 기능이 아니다. 관측하지 못한 물리 상태를 Backend 기록으로 추측하는 기능도 아니다.

## 핵심 원칙

1. 상태별 authoritative owner를 따르며, 전체 시스템을 하나의 승자로 판정하지 않는다.
2. Jetson이 공개한 aggregate는 `publicationRevision` 및 `transitionHash`로 비교한다.
3. 같은 aggregate의 같은 revision에서 hash가 다르면 자동으로 덮어쓰지 않고 충돌로 격리한다.
4. Backend의 업무 상태는 Jetson의 현장 판정 상태를 덮어쓰지 않는다.
5. Backend의 세션·차량 자격 기준 정보는 Jetson mirror를 교정할 수 있다.
6. 재전송은 저장된 immutable transition을 같은 Idempotency-Key로 보내며, 현재 상태에서 과거 payload를 재구성하지 않는다.
7. Backend의 적용 확인 전에 공개 terminal payload와 delivery 증거를 삭제하지 않는다.
8. 복구된 관측 기반 scope는 새로운 신뢰 가능한 관측 전까지 `ObservationState.UNKNOWN`이다.
9. Reconciliation 응답 도착 전 local state가 다시 변경되었다면 응답으로 최신 상태를 덮어쓰지 않고 재비교한다.

## 상태 권한

| 상태·사실 | Authoritative owner | Reconciliation 계약 |
|---|---|---|
| Camera availability | Jetson | Backend가 변경하지 않는다. |
| `TrackSegment` | Jetson | Backend와 공유하지 않는다. |
| `PhysicalVehicle` 동일성 | Jetson | Backend가 ID를 생성·병합·복구하지 않는다. |
| `physicalVehicleId ↔ sessionId` ContextBinding | Jetson | Backend session과 context는 복구할 수 있지만 물리 차량에 자동 binding하지 않는다. |
| Backend `ParkingSession` 생성·업무 상태 | Backend | `CLOSED`는 Jetson `ParkingSessionMirror`와 하위 scope의 authoritative 강제 종료 근거다. |
| Jetson 출차 관측 사실과 EXIT publication | Jetson | 신뢰 가능한 출차 관측을 immutable EXIT 전이로 만든다. Backend가 아직 ACTIVE면 저장된 전이를 적용해 session을 닫는다. |
| Jetson `ParkingSessionMirror` lifecycle | Jetson이 mirror 관리, Backend closure가 강제 종료 권한 보유 | Jetson 출차 확인 또는 Backend `CLOSED`로 terminal이 되며 termination reason으로 두 경로를 구분한다. |
| `vehicleId`·전기차·장애인 차량 자격 | Backend | 더 높은 `contextVersion`을 Jetson에 적용한 후 규칙을 재평가한다. |
| `ZoneVisit` | Jetson | Backend는 opaque `zoneVisitId`를 상관관계로 보존할 수는 있으나 현재 진입·이탈을 교정하지 않는다. |
| `ParkingEpisode` lifecycle | Jetson | Backend는 적용한 edge revision을 mirror한다. |
| `BlockingRelation` | Jetson | Backend는 Incident의 근거로만 참조한다. |
| Edge `Incident` lifecycle | Jetson | Backend는 적용한 OPEN·RESOLVE revision을 mirror한다. |
| Backend event 업무 상태 | Backend | Jetson Incident lifecycle과 별도로 유지한다. |
| `MoveVerification` command | Backend | Jetson은 누락된 유효 command를 다시 수신할 수 있다. |
| `MoveVerificationResult` | Jetson | Backend는 적용 여부와 업무 후속 조치를 관리한다. |
| Idempotency 처리 결과·applied edge revision | Backend | Jetson delivery state와 correlation을 교정하는 근거다. |

### Edge Incident와 Backend event의 분리

```text
Jetson Incident
= 현장에서 위반 규칙의 원인이 성립하는가

Backend business event
= 이 사건에 대한 요청·알림·관리자 처리가 어디까지 진행됐는가
```

Backend에서 event가 관리자 처리로 `RESOLVED`되어도 Jetson의 규칙 원인이 계속 성립하면 Edge Incident는 `OPEN`을 유지한다. Jetson Incident `RESOLVE`는 현장 원인 해소를 알리지만 Backend의 알림·감사·관리자 workflow 기록을 삭제하지 않는다.

Backend의 `appliedEdgeRevision`과 `businessStatus`는 별도 값으로 보존해야 한다.

## 비교 단위

Jetson과 Backend는 Jetson이 공개한 aggregate를 다음 값으로 비교한다.

```text
edgeDeviceId
aggregateType
aggregateId
publicationRevision
transitionType
transitionHash
```

| 필드 | 의미 |
|---|---|
| `edgeDeviceId` | aggregate를 공개한 Jetson device |
| `aggregateType` | `PARKING_EPISODE`, `INCIDENT`, `MOVE_VERIFICATION`, `PARKING_SESSION_EXIT` 등 공개 단위 |
| `aggregateId` | aggregate lifecycle 동일성 |
| `publicationRevision` | Backend에 공개된 도메인 전이의 단조 증가 순번 |
| `transitionType` | 해당 revision의 전이 종류 |
| `transitionHash` | canonical publication payload의 hash |

`transitionHash`는 네트워크 응답이나 현재 snapshot이 아니라, 해당 revision에서 전송하도록 고정된 immutable transition payload를 기준으로 한다.

Backend는 각 edge aggregate에 대해 최소한 다음 적용 정보를 조회 가능하게 보존한다.

```text
edgeDeviceId
aggregateType
aggregateId
appliedEdgeRevision
lastTransitionType
lastTransitionHash
appliedAt
Backend correlation IDs
```

Incident correlation의 `eventId`, `requestId`, `notificationId` 등은 Edge Incident의 ID나 revision을 대체하지 않는다.

## Reconciliation 실행 조건

- Jetson startup
- Backend connectivity 회복
- 장기 offline 후
- outbox `DEAD_LETTER` 발생
- local durable state 복구 또는 device 교체
- Backend의 reconciliation 요청
- 정기 운영 주기
- 공개 scope 또는 authoritative parent 종료 child의 terminal full record를 tombstone으로 축약하거나 purge하기 전
- retention contract version 변경 시

Reconciliation은 camera frame 처리와 분리한다. Local durable state가 정상적으로 복구된 재시작에서는 Backend 응답을 기다리며 내부 판정 전체를 멈추지 않는다. 새 공개 전이는 outbox에 보존하고 reconciliation 결과로 적용·재전송 상태를 교정한다.

## Reconciliation 교환 계약

Reconciliation은 논리적으로 다음 세 사실을 교환한다. Transport endpoint, chunk 방식, DTO 이름은 이 도메인 계약의 범위가 아니다.

```text
Jetson ReconciliationManifest
→ Backend AuthoritativeSnapshot
→ Jetson SnapshotApplicationAck
```

### 1. ReconciliationManifest

Manifest는 한 비교 시점의 local 주장과 미완료 전달 책무를 요약한다.

| 범주 | 필수 의미 |
|---|---|
| 교환 identity | `reconciliationId`, `edgeDeviceId`, 계약 version, 생성 시각·사유 |
| active mirror | ACTIVE ParkingSessionMirror, OPEN Incident, PARKED ParkingEpisode, 진행 중 MoveVerificationAttempt |
| terminal 미확인 | Backend 적용 확인이 없는 terminal aggregate·tombstone |
| delivery | `PENDING`, `RETRY_WAIT`, `IN_FLIGHT`, `DEAD_LETTER` publication과 미완료 EvidenceArtifact |
| 비교 값 | aggregate type·ID, publication revision, transition type·hash, delivery state, correlation 요약 |

Manifest에는 raw frame, bbox, TrackSegment, PhysicalVehicle 위치, 전체 evidence image 또는 비교에 필요 없는 차량 개인정보를 포함하지 않는다. Manifest 기준 시점 뒤에 생긴 전이는 기존 outbox 순서와 다음 비교 대상으로 남는다.

### 2. AuthoritativeSnapshot

Backend snapshot은 다음 두 종류의 사실을 구분한다.

| 종류 | 내용 |
|---|---|
| Backend authoritative fact | Session의 `ACTIVE / CLOSED / NOT_FOUND`, context version과 차량 자격, 유효한 pending command, retention contract |
| Edge application fact | aggregate별 applied revision, 마지막 transition type·hash, 적용 시각, Backend correlation |

Backend가 Jetson보다 높은 applied revision을 보유한 재해 복구 상황에서는 단순 비교 요약과 별도로 `AppliedTransitionRecoveryEnvelope`을 제공한다. 이 envelope은 Jetson이 과거 공개 사실의 최소 유효 aggregate를 복원할 수 있을 정도로 원래 publication의 의미를 포함해야 한다.

| Aggregate | Recovery envelope 최소 의미 |
|---|---|
| ParkingEpisode | episode ID, session ID, 적용 상태, revision·hash, PARKED 시각, 종료 시각(해당 시), assignment/zone |
| Incident | incident ID, 공개 subject session ID·victim session ID, rule code, lifetime scope kind·ID, zone, first observed·occurred 시각, 적용 transition, revision·hash, correlation |
| MoveVerification | request ID, verification attempt, 결과, 대상 incident revision, publication revision·hash |
| ParkingSession EXIT | session ID, exit occurred 시각, publication revision·hash |

Envelope이 없거나 hash를 검증할 수 없으면 Backend 요약만으로 aggregate의 도메인 필드를 추측해 복구하지 않는다.

Publication에 historical `physicalVehicleId`가 포함돼 있었다면 recovery envelope은 감사용 opaque reference로 보존할 수 있다. 이를 현재 PhysicalVehicle identity나 ContextBinding을 복구·재연결하는 근거로 사용하지 않는다.

### 3. SnapshotApplicationAck

Jetson은 snapshot 전체 적용 결과를 `COMPLETED / PARTIAL / CONFLICT`로 확인한다. 이 ACK는 Jetson이 Backend snapshot을 소비했다는 사실이다. Backend가 edge publication을 적용했다는 증거는 direct transition response 또는 snapshot의 revision·hash·correlation인 `BackendApplicationConfirmation`이다. 두 확인을 같은 의미로 사용하지 않는다.

같은 `reconciliationId`의 snapshot은 동일한 snapshot identity와 내용 hash를 유지해야 하고, Jetson은 동일 적용 ACK를 재전달할 수 있어야 한다.

## Revision·hash 비교 계약

| Jetson local | Backend applied | 처리 |
|---|---|---|
| 같은 revision·같은 hash | 동일 | Backend 적용을 확인하고 local delivery를 confirmed로 교정한다. |
| Jetson revision이 높음 | Backend가 낮음 | 저장된 정확한 transition을 동일 revision·Idempotency-Key로 재전송한다. |
| Backend revision이 높음 | Jetson이 낮음 | 과거에 적용한 edge transition임을 hash·recovery payload로 검증한 후 최소 mirror·tombstone을 복구한다. |
| 같은 revision·다른 hash | 충돌 | 자동 덮어쓰기·새 revision 생성·임의 재전송을 금지한다. |
| Jetson aggregate 존재 | Backend `NOT_FOUND` | 미적용 transition이면 재전송한다. 과거 ACK 기록이 있다면 Backend 데이터 충돌로 격리한다. |
| Jetson aggregate 없음 | Backend aggregate 존재 | 검증 가능한 공개 transition의 최소 상태만 복구하고 observation은 UNKNOWN으로 둔다. |
| Jetson revision 기록 존재, immutable payload 유실 | Backend도 미적용 | `LOCAL_PUBLICATION_LOST` 충돌로 격리하고 payload를 추측해 새로 만들지 않는다. |

Backend가 더 높은 revision을 보유한 것은 Backend가 Edge lifecycle을 독자적으로 진행시켰다는 의미가 아니다. Jetson이 과거에 공개했으나 local receipt·state가 유실된 전이만 복구 근거가 될 수 있다.

## Scope별 Reconciliation

### ParkingSessionMirror

Backend는 session에 대해 `ACTIVE`, `CLOSED`, `NOT_FOUND`를 구분해 반환한다.

| Jetson | Backend | 처리 |
|---|---|---|
| `ACTIVE` | `ACTIVE` | local session을 유지하고 더 높은 context version을 적용한다. |
| `ACTIVE` | `CLOSED` | Backend 권한으로 SessionMirror와 관련 하위 scope를 명시적으로 강제 종료한다. |
| `EXITED / LOCAL_EXIT_CONFIRMED`, EXIT 미적용 | `ACTIVE` | 저장된 EXIT transition을 재전송한다. |
| `EXITED / BACKEND_CLOSED` | `CLOSED` | authoritative closure correlation을 확인하고 새 edge EXIT를 만들지 않는다. |
| `ACTIVE` | `NOT_FOUND` | 자동 종료하지 않고 `RECONCILIATION_CONFLICT`로 격리한다. |
| local session 없음 | `ACTIVE` | SessionMirror과 VehicleContext를 복구하되 ContextBinding은 자동 생성하지 않는다. |
| local session 없음 | `CLOSED` | 중복 방지에 필요한 최소 terminal mirror만 복구할 수 있다. |

Backend `CLOSED`를 적용할 때 Jetson은 ContextBinding, ZoneVisit, ParkingEpisode, BlockingRelation을 각각 강제 종료하고, `OPEN` Incident를 `SESSION_EXITED`로 RESOLVE하며, 진행 중 MoveVerificationAttempt를 `RESOLVED / SESSION_EXITED`로 완료한다.

이 종료 전파는 Backend event 업무 상태를 복사한 것이 아니라, authoritative parent scope인 ParkingSession이 종료됐기 때문에 Jetson의 하위 lifetime scope를 정리하는 것이다.

Backend는 이미 `CLOSED`인 session이라도 그 session이 열려 있을 때 Jetson이 OPEN했고 아직 최종 적용되지 않은 aggregate의 terminal RESOLVE를 멱등적으로 받아들여야 한다. 이 전이는 session을 다시 활성화하거나 새 업무를 시작하는 요청이 아니라 기존 edge aggregate를 닫는 최종 revision이다. 이를 거부하면 Jetson의 terminal 확인과 retention이 영구히 완료될 수 없다.

### VehicleContext와 ContextBinding

Backend의 `contextVersion`이 Jetson보다 높으면 `vehicleId`, `isElectric`, `isDisabledVehicle` 등 authoritative context를 갱신한다. Context 정정은 관련 규칙의 재평가를 유발할 수 있지만 Incident를 기계적으로 RESOLVE하지 않는다.

Backend는 `physicalVehicleId`나 camera 관측 연속성을 보유하지 않는다. Local ContextBinding이 없으면 Backend session과 현재 보이는 차량을 위치·시간만으로 자동 연결하지 않는다. 신뢰 가능한 재매칭 전까지 다음 상태를 분리한다.

```text
ParkingSessionMirror = ACTIVE
VehicleContext = RECOVERED
ContextBinding = UNBOUND
Physical observation = UNKNOWN 또는 UNMATCHED
```

### ParkingEpisode

- Backend applied revision이 낮으면 PARKED·UNPARKED immutable transition을 순서대로 재전송한다.
- Backend에 PARKED revision이 있지만 local episode가 없는 재해 복구에서는 공개된 PARKED 사실을 durable suspended state로 복구하고 observation을 UNKNOWN으로 둔다.
- 복구된 episode를 현재 PhysicalVehicle에 자동 연결하지 않는다.
- Backend의 terminal UNPARKED revision으로 terminal mirror·tombstone을 복구할 수는 있지만, Backend 상태만으로 새로운 물리 이동 시각을 추측하지 않는다.
- Backend ParkingSession `CLOSED`는 열린 episode의 강제 종료 근거이지만, Backend event 업무 상태는 episode 종료 근거가 아니다.

### Incident

- Backend `appliedEdgeRevision` < Jetson `publicationRevision`: local immutable OPEN·RESOLVE transition을 재전송한다.
- Revision과 hash가 같음: delivery와 terminal confirmation을 교정한다.
- Backend에 OPEN revision이 있지만 local Incident가 없음: 검증 가능한 recovery snapshot으로 `OPEN + ObservationState.UNKNOWN`을 복구한다.
- Backend에 RESOLVE revision이 있지만 local tombstone이 없음: final revision·hash·correlation을 포함한 최소 tombstone을 복구한다.
- Backend `businessStatus=RESOLVED`이지만 최종 applied edge transition이 OPEN: Jetson Incident를 RESOLVE하지 않는다.
- Backend ParkingSession `CLOSED`: parent scope 권한에 따라 local Incident를 `SESSION_EXITED`로 강제 RESOLVE한다.

Reconciliation으로 복구한 OPEN Incident는 rule observation을 복구한 것이 아니므로, 새로운 신뢰 가능한 관측 전까지 RESOLVE·clear timer를 진행하지 않는다.

### MoveVerificationAttempt

- Backend가 유효한 pending command를 보유하고 Jetson에 attempt가 없으면 같은 `requestId`, `verificationAttempt`, command identity로 재전달한다.
- Jetson이 terminal result를 보유하고 Backend가 미적용했으면 같은 result revision·Idempotency-Key로 재전송한다.
- Backend의 `RENOTIFIED`, `NEED_ADMIN`, `COMPLETED` 등 업무 상태를 Jetson result로 복사하지 않는다.
- Jetson result는 `RESOLVED`, `STILL_ACTIVE`, `UNKNOWN`을 구분하고 Backend는 이 결과를 근거로 후속 업무를 결정한다.
- 복구 중의 프로세스 중단 구간은 이동·미이동 관측으로 간주하지 않는다.

### Evidence와 Backend correlation

- Incident OPEN 적용 후 반환한 `eventId`는 Incident correlation으로 복구할 수 있어야 한다.
- Backend에 동일 checksum의 evidence ACK가 있으면 local delivery를 확인할 수 있다.
- Backend에 `eventId`가 있어도 local evidence 파일이 없다면 이미지를 재생성하지 않는다.
- Incident가 RESOLVED되어도 미전송 OPEN evidence를 취소하지 않는다.
- 복구 불가능한 evidence 실패는 성공 ACK로 바꾸지 않는다. Backend 또는 계약된 운영 권한자가 `EVIDENCE_UNAVAILABLE`을 확인했을 때만 parent retention blocker를 해제하고 실패 metadata는 보존한다.

## 충돌 및 장애 처리

### 같은 revision, 다른 hash

다음을 금지한다.

- 한쪽의 payload로 자동 덮어쓰기
- 새 publication revision을 임의로 생성해 우회하기
- 새 Idempotency-Key로 같은 사실을 다시 전송하기
- tombstone·payload·evidence 삭제

해당 aggregate를 `RECONCILIATION_CONFLICT`로 격리하고 양쪽의 payload hash·Idempotency-Key·적용 시각·correlation을 보존한다.

### Backend 연결 불가

- active scope를 유지한다.
- 미완료 outbox와 `PUBLICATION_APPLIED`·`AUTHORITATIVE_PARENT_CLOSED` 확인이 필요한 tombstone의 compaction·purge를 금지한다.
- 공개된 적 없는 `LOCAL_ONLY` tombstone은 local child·replay·stale-input 조건을 충족하면 Backend 연결과 무관하게 정리할 수 있다.
- UNKNOWN을 Incident RESOLVE, UNPARKED, EXIT로 변환하지 않는다.
- 연결 회복 후 immutable transition으로 reconciliation·재전송한다.

### `NOT_FOUND`

Backend `NOT_FOUND`는 도메인 종료 사실이 아니다. 잘못된 ID, 다른 device 소유, Backend retention·유실, contract 불일치, 미적용 local publication을 구분할 수 없으므로 자동 RESOLVE·EXIT·purge하지 않는다.

### Clock skew

`serverTime`은 clock health를 확인하는 근거이다. Backend 시각으로 기존 `occurredAt`을 덮어쓰지 않는다. 시각 차이가 심각하면 새로운 시간 기반 확정을 보류할 수 있지만 기존 active scope나 OPEN Incident를 종료하지 않는다.

### 느린 Reconciliation 응답

Manifest 생성 후 local aggregate revision이 증가했다면 이전 snapshot으로 최신 상태를 덮어쓰지 않는다. 현재 local revision과 다시 비교하고 필요하면 다음 reconciliation으로 넘긴다.

## Disaster recovery 한계

Backend의 applied-edge snapshot으로 다음을 복구할 수 있다.

- ParkingSessionMirror와 VehicleContext
- Backend에 공개된 ParkingEpisode의 최종 applied state
- Backend에 공개된 Incident의 OPEN·RESOLVE revision
- Backend correlation IDs
- 적용된 MoveVerificationResult
- delivery 확인에 필요한 revision·hash·Idempotency 결과

Backend만으로는 다음을 복구할 수 없다.

- ByteTrack `trackSegmentId`
- 현재 보이는 차량의 `physicalVehicleId`
- 여러 TrackSegment가 같은 물리 차량이라는 동일성 근거
- `sessionId ↔ physicalVehicleId` ContextBinding
- 현재 bbox·ZonePresence·Blocking geometry
- 중단 구간의 정지·점유 시간
- Backend에 공개되지 않은 candidate state
- 유실된 local image file

Local state 전체가 유실된 재해 복구 직후에는 다음을 적용한다.

```text
공개 상태 = Backend applied-edge snapshot으로 최소 복구
관측 상태 = UNKNOWN
ContextBinding = UNBOUND
TrackSegment = 새로 생성
중단 시간 = timer에 미포함
```

Backend session이 ACTIVE라고 해서 가장 가까운 차량에 자동 binding하지 않는다. 신뢰 가능한 재매칭이 없다면 session-scoped 새 publication을 보류하고 reconciliation 대상으로 남겨둔다.

## Retention contract 교환

Backend는 Reconciliation snapshot에서 다음 보존 보장을 versioned contract로 공개한다.

```text
contractVersion
effectiveAt
backendIdempotencyWindow
backendAppliedEdgeWindow
commandReplayWindow
reconciliationOverlapWindow
```

필요하면 evidence 보존 및 Backend applied-edge snapshot 보존 기간도 별도 계약으로 제공한다.

Backend는 idempotency window 동안 Idempotency-Key·payload hash 처리 결과를, applied-edge window 동안 aggregate별 applied revision·hash·correlation을, command replay window 동안 command identity를 조회 가능하게 보존한다.

각 window의 기준 시각은 [Jetson 상태 보존 및 Retention 계약](./04-durable-state-and-retention-contract.md#retention-계약-변수)을 따르며, Backend contract는 기준 시각 또는 계산된 `retainUntil`을 함께 식별할 수 있어야 한다.

지원하는 offline retry와 reconciliation을 끝까지 멱등적으로 보장하려면 다음 하한 관계가 필요하다.

```text
backendIdempotencyWindow
>= supportedOfflineRetryWindow

backendAppliedEdgeWindow
>= supportedOfflineRetryWindow + reconciliationOverlapWindow
```

Jetson은 다음을 보장한다.

- delivery receipt는 Backend idempotency 보장 기간보다 먼저 삭제하지 않는다.
- published scope tombstone은 delivery receipt보다 먼저 삭제하지 않는다.
- processed command identity는 command replay 보장 기간보다 먼저 삭제하지 않는다.
- 공개된 terminal full payload는 Backend final revision·hash 확인 및 reconciliation overlap 경과 전에 축약하지 않는다.
- 유효한 retention contract를 확인하지 못했으면 관련 공개 terminal record의 compaction·purge를 보류한다.

Contract가 변경되어도 기존 record의 보존 시간을 소급해 줄이지 않는다.

```text
새 contract의 기간이 길어짐
→ 기존 record의 retainUntil 연장 가능

새 contract의 기간이 짧아짐
→ 새 record부터 적용
→ 기존 record는 이전 retainUntil 유지
```

## Reconciliation을 이용한 terminal 확인

Reconciliation은 공개 scope의 `PUBLICATION_APPLIED` 확인과 Backend 선종료 child의 `AUTHORITATIVE_PARENT_CLOSED` 확인을 제공한다. 공개되지 않은 candidate·ZoneVisit·BlockingRelation 같은 `LOCAL_ONLY` scope에는 존재하지 않는 Backend revision을 요구하지 않는다.

### 공개 scope

```text
local lifecycle = TERMINATED
AND Backend application confirmation의 revision = local final publication revision
AND Backend application confirmation의 hash = local final transition hash
AND 미적용·DEAD_LETTER publication 없음
```

Direct transition response와 reconciliation snapshot은 같은 revision·hash·correlation을 확인하는 대체 가능한 `BackendApplicationConfirmation` 근거다. Jetson의 `SnapshotApplicationAck`는 이 근거가 아니다.

### Authoritative parent 종료 child

Session `CLOSED` 때문에 별도 UNPARKED를 만들지 않고 끝난 ParkingEpisode처럼 직접 terminal publication이 없는 child는 다음으로 확인한다.

```text
authoritative parent closure confirmed
AND local child termination cause = that parent
AND child가 생성한 다른 publication은 모두 적용됨
AND active child·evidence·command reference 없음
```

### Local-only scope

공개 revision이 없는 scope는 local 종료, child 정리, stale-input·replay 안전 구간을 근거로 compaction한다. Reconciliation은 이 scope의 물리 사실을 만들어내거나 확인하지 않는다.

Full record의 tombstone 축약과 tombstone의 최종 purge는 [Jetson 상태 보존 및 Retention 계약](./04-durable-state-and-retention-contract.md#compaction과-purge-조건)의 서로 다른 단계다. 공개 전이는 Backend 적용 확인 없이 시간이 오래 지났다는 이유로 어느 단계도 건너뛰지 않는다.

## 팀 합의가 필요한 값

다음은 도메인 의미가 아니라 배포·운영 계약 값이므로 Jetson·Backend·운영 담당자의 합의가 필요하다.

- Backend idempotency 보장 기간
- 지원하는 최대 offline retry 기간
- Backend command replay 보장 기간
- reconciliation overlap 기간
- applied-edge recovery snapshot 보존 기간
- Clock skew 경고·시간 기반 판정 보류 기준
- reconciliation·retention contract version 명칭과 호환 정책
