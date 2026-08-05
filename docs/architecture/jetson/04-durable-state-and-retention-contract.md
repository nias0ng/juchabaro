# Jetson 상태 보존 및 Retention 계약

> 상태: Draft · 관련 이슈: S15P11E202-461 · 책임: 동일 장치의 영속 상태, 재시작, outbox, evidence와 저장 상한

이 문서는 같은 Jetson과 같은 SD카드에서 process crash, 전원 장애와 네트워크 단절이 발생해도 이미 확정한 상태와 미전송 handoff를 다시 이어가는 최소 계약을 정의한다.

## 1. 범위

이 문서가 보장하는 것은 다음과 같다.

- 접수를 성공으로 응답한 command·entry input의 재시작 후 중복 억제
- PARKED·UNPARKED·Incident·EXIT 등 확정 상태의 복구
- 공개 전이와 outbox의 원자적 기록
- 동일 payload·revision·Idempotency-Key 재전송
- evidence file spool의 일관성
- 64GB SD를 소진하지 않는 제한된 retention과 degraded 동작

다음은 보장하지 않는다.

- 다른 Jetson 또는 다른 SD카드로의 상태 복구
- Backend snapshot에서 live PhysicalVehicle·ParkingEpisode·Incident 재생성
- raw frame, bbox, TrackSegment 복구
- Backend 업무 상태 reconciliation
- 세부 DDL·index·migration evolution의 최종 형태

`[결정]` 구현은 SQLite WAL 기반의 하나의 local transactional store,
재구성 가능한 in-memory cache와 제한된 evidence file spool로 구성한다.
durable domain·workflow state, dedup, outbox와 evidence metadata는 SQLite에
두고 image binary만 file spool에 둔다.

## 2. 저장 등급

| 등급 | 대상 | 장애 뒤 의미 |
|---|---|---|
| Ephemeral | raw frame, bbox, TrackSegment, 반복 frame signal | 복구하지 않고 새 관측으로 생성 |
| Checkpointed | PhysicalVehicle 관측 연결, ZoneVisit·ParkingEpisode trusted timer, motion anchor | 마지막 안전한 하한부터 재개 |
| Immediately durable | entry input과 dedup key, ContextBinding, ParkingSessionMirror, PARKED·UNPARKED, Incident Candidate·OPEN·RESOLVE, EXIT, verification command/result, outbox, evidence metadata | 성공 응답 또는 공개 전이 전에 commit |

`[제안값]` dirty checkpoint는 최대 10초마다 하나의 batch transaction으로 기록한다. crash로 잃은 최대 10초의 trusted time은 추정 보충하지 않는다. 확정이 조금 늦어질 수는 있지만 거짓 확정을 만들지 않는다.

## 3. 최소 영속 record

### 3.1 Active snapshot

현재 판단을 재개하는 데 필요한 값만 저장한다.

```text
scope type·ID
domain state
domain key와 필요한 parent/context reference
observation state와 last reliable time
trusted accumulator와 적용된 scalar 설정값
recordVersion
publicationRevision
```

### 3.2 Outbox

```text
deliveryId
aggregate type·ID
publicationRevision
transition type
immutable serialized payload
payload hash
Idempotency-Key
delivery state
attempt count / nextAttemptAt / last error
```

serializer·hash algorithm·wire schema는 `[후속 계약]`에서 고정한다. Jetson은 한 번 저장한 payload bytes를 retry 때 다시 생성하지 않는다.

### 3.3 Receipt와 tombstone

전체 lifecycle archive 대신 다음 최소 사실을 보존한다.

```text
scope 또는 dedup identity
final state·reason·occurredAt
final publicationRevision와 payload hash
Backend correlation·confirmedAt, 존재하는 경우
expiresAt
```

### 3.4 Evidence metadata

```text
evidenceId
incidentId / publicationRevision
capturedAt / imageType
final path / byteSize / checksum
state / last error
Backend ACK, 존재하는 경우
retention disposition
```

범용 relation graph, 모든 내부 transition의 immutable event log와 전체 payload archive는 필수 저장 구조가 아니다. 실제 조회에 필요한 foreign key와 index만 둔다. cache와 index는 store에서 재구성할 수 있어야 하며 authoritative state가 아니다.

## 4. Consistency boundary

### 4.1 공개 전이

다음은 한 transaction으로 commit한다.

```text
domain snapshot 또는 terminal tombstone
+ recordVersion
+ publicationRevision
+ immutable outbox row
```

장애가 어느 시점에 발생해도 “state만 바뀌고 outbox가 없음” 또는 “outbox만 있고 state가 없음”을 허용하지 않는다.

### 4.2 아직 publication할 수 없는 전이

ContextBinding 전 PARKED처럼 외부 correlation이 부족한 상태는 다음만 commit한다.

```text
domain snapshot
+ original occurredAt
+ pending handoff marker
```

authoritative active binding 또는 late historical correlation receipt가 생기면 누락된 전이를 시간·aggregate 순서대로 immutable outbox로 만드는 transaction을 실행한다. publication을 만들기 전에 임의 sessionId를 채우지 않는다.

pending handoff marker는 domain scope가 아니라 publication eligibility workflow다. 상태는 `WAITING_CORRELATION → MATERIALIZED | EXPIRED`로 충분하다. `EXPIRED / UNBOUND_CONTEXT_EXPIRED`는 ParkingEpisode나 Incident를 다시 종료하는 reason이 아니라 외부 publication을 만들 수 없었다는 disposition이다.

### 4.3 Incident Candidate와 evidence

Candidate 생성 transaction에서 `incidentId`와 Candidate snapshot을 함께 저장한다. Candidate evidence는 같은 ID를 사용하며 OPEN transaction에서 publication revision에 귀속한다. OPEN 전 evidence 상태와 incidentId는 local-only이고 외부에 공개하지 않는다.

Evidence binary는 임시 `.part` 파일에 쓰고 size·checksum을 확인한 뒤 file fsync-equivalent, final path atomic rename, parent-directory fsync-equivalent 순서로 내구성을 확보한다. 그 뒤에만 `READY` metadata를 commit한다. local store도 power-loss durable commit mode를 사용해야 한다.

rename 뒤 metadata commit 전에 죽으면 metadata 없는 final orphan이 생길 수 있다. restart spool scan은 orphan `.part`와 metadata 없는 final file을 모두 격리·정리한다. 반대로 READY metadata가 있는데 파일이 없거나 checksum이 다르면 `FAILED / LOST_OR_CORRUPTED`로 바꾼다. 이미 OPEN publication revision에 귀속된 evidence에만 `EvidenceUnavailable` outbox를 만들며, pre-OPEN failure는 local metadata로 남겼다가 Incident가 OPEN될 때 귀속·공개하거나 Candidate 취소와 함께 정리한다.

### 4.4 입력 접수

Jetson inbound boundary는 domain state를 바꾸는 `EntryDecision`, `EntryReviewResolution`, `SessionContextUpdate`, `MoveVerificationCommand`를 다음 값과 함께 durable하게 저장한 뒤에만 성공 응답한다. ZoneDefinitionSnapshot은 active scope가 없는 통제된 기동에서 별도 atomic 설정 배포로 적용한다.

```text
input identity와 revision 또는 attempt
payload hash
immutable request 또는 필요한 command snapshot
initial workflow state
```

동일 identity와 같은 payload retry는 기존 결과를 반환한다. 동일 identity의 다른 payload는 계약 오류다.

## 5. Transactional outbox

### 5.1 상태

```text
PENDING → IN_FLIGHT → DELIVERED
IN_FLIGHT → RETRY_WAIT → IN_FLIGHT
IN_FLIGHT → FAILED_TERMINAL
FAILED_TERMINAL → RETRY_WAIT  [explicit intervention only]
```

- `DELIVERED`는 `[후속 계약]`에서 정한 Backend 적용 확인을 받았다는 뜻이다.
- `FAILED_TERMINAL`은 인증·schema·payload처럼 retry로 회복되지 않는 오류에만 사용한다. domain transition을 취소하지 않으며 health와 운영 대상이다.
- persisted IN_FLIGHT는 restart 때 RETRY_WAIT로 돌려 같은 payload를 다시 보낼 수 있다.
- FAILED_TERMINAL에서 RETRY_WAIT로 돌아가는 전이는 인증·Backend schema 복구 같은 명시적 운영 조치 뒤에만 허용하며 payload는 바꾸지 않는다.
- FAILED_TERMINAL은 같은 aggregate의 뒤 revision도 계속 차단한다. 개별 revision을 local에서 건너뛰거나 waive하는 상태는 현재 계약에 두지 않는다.

### 5.2 순서와 동시성

- aggregate·destination·publicationRevision당 outbox row는 하나다.
- 같은 aggregate에서는 가장 낮은 미확인 revision만 claim할 수 있다.
- revision gap이 있으면 뒤 revision 전송을 보류한다.
- camera/inference loop와 publisher를 분리한다.
- `[제안값]` publisher concurrency는 1로 시작한다.

### 5.3 Retry

`[제안값]` retry 가능한 네트워크·5xx 오류는 1초부터 시작하는 exponential backoff와 jitter를 사용하고 최대 간격을 5분으로 제한한다. 횟수만으로 FAILED_TERMINAL로 바꾸지 않는다. 24시간 연속 실패하면 health 경고를 올리고, 7일 offline SLO를 넘으면 CRITICAL 운영 상태로 보고하되 quota가 남아 있는 동안 동일 payload retry를 계속한다. 인증·schema·payload처럼 반복해도 회복되지 않는 오류만 FAILED_TERMINAL로 격리한다.

ACK를 받은 뒤 DELIVERED commit 전에 process가 죽을 수 있으므로 Backend는 같은 Idempotency-Key와 payload의 retry를 멱등 처리해야 한다. 정확한 보장 기간은 `[후속 계약]`이다.

Backend application confirmation은 최소한 다음을 반환하거나 같은 publication identity로 조회할 수 있어야 한다.

```text
aggregate ID / publicationRevision
payload hash
APPLIED | ALREADY_APPLIED | CONFLICT
Backend correlation
confirmedAt
```

같은 revision의 다른 hash는 자동 덮어쓰기나 새 revision 생성 없이 FAILED_TERMINAL로 격리한다. 7일 offline SLO를 넘긴 미확인 publication도 local에서 삭제하거나 payload를 바꾸지 않는다. 동일 identity 재전송과 application status 조회 중 무엇을 사용할지, Backend uniqueness·조회 보존 기간은 `[후속 계약]`에서 함께 정한다.

이 후속 계약이 확정되기 전에는 7일 retry를 배포 완료 보장이 아니라 용량·운영 설계 목표로 취급한다.

## 6. 동일 장치 재시작

재시작은 다음 순서를 따른다.

1. local store를 열고 migration과 빠른 integrity check를 수행한다.
2. active snapshot, dedup record, 미완료 outbox와 evidence metadata를 복구한다.
3. persisted IN_FLIGHT를 RETRY_WAIT로 되돌린다.
4. domain state는 유지하고 관측 기반 scope의 observation을 UNKNOWN으로 시작한다.
5. trusted timer를 마지막 checkpoint 하한부터 재개하고 downtime을 더하지 않는다.
6. READY evidence의 파일 존재와 checksum을 확인하고 orphan `.part`와 metadata 없는 final file을 정리한다.
7. 통제된 배포가 versioned config로 주입한 장치별 mutable data cap과
   `EVIDENCE_SPOOL_CAP_BYTES`를 읽고 hard cap 이하인지 검증한 뒤 현재
   filesystem·영역 사용량과 watermark를 다시 계산해 필요한 DRAIN을 적용한다.
   runtime은 현재 free space를 설치 baseline으로 삼아 cap을 재산출하지 않는다.
8. outbox publisher를 시작한다.
9. store가 정상이라면 camera·model을 기동하고 첫 정상 전체 관측 뒤 재식별·규칙 재평가를 시작한다. DRAIN에서는 기존 PhysicalVehicle과 scope만 관측·종료하는 drain-only mode로 시작하며 새 scope·Candidate는 만들지 않는다.

TrackSegment와 raw frame은 복구하지 않는다. 복구된 OPEN Incident를 새 incidentId로 만들거나 PARKED 차량이 이동했다고 추정하지 않는다.

현재 `GeometricEntityResolver`의 bbox·velocity history는 process 안에서만 유지되고
durable PhysicalVehicle snapshot에는 재식별 anchor가 없다. 따라서 process restart
뒤 기존 ACTIVE 차량이 있는 동안에는 새 segment를 새 PhysicalVehicle로 만들지
않고 `UNKNOWN / REIDENTIFICATION_UNCERTAIN` barrier를 적용한다. detection이 남아
있으면 부재 timer도 멈추며, 정상 전체 영역이 빈 trusted sample에서만 기존 차량의
absence confirmation을 재개한다. 9번의 즉시 재식별을 완성하려면 별도 저장소 ADR로
정규화 geometry anchor, 관측 시각, schema version과 개인정보·retention 경계를
정한 뒤 `RestartAwareEntityResolver`에 주입해야 한다. Zone·Parking·Incident나
session 상태로 이 근거를 대체하지 않는다.

store integrity가 실패하거나 writable하지 않으면 새 durable transition을 확정하거나 ACK가 필요한 delivery를 진행하지 않는다. health는 `NOT_READY / STORAGE_FAILURE`로 표시하고 진단만 수행한다.

## 7. Retention

### 7.1 기본 원칙

1. cache eviction은 domain transition이 아니다.
2. ACTIVE·OPEN·PARKED를 age만으로 종료하지 않는다.
3. publication 적용 여부와 evidence 보존 여부를 구분한다.
4. 원본 CCTV 영상은 저장하지 않는다.
5. 저장공간을 지키기 위해 evidence binary를 줄일 수 있지만 손실 사실을 숨기지 않는다.
6. outbox를 무한히 늘리지 않는다. quota에 가까워지면 신규 durable work를 중지한다.

### 7.2 초기 보존값

다음은 pilot 실측 전 `[제안값]`이다.

| 대상 | 초기 보존 |
|---|---|
| 공개되지 않은 terminal Candidate | child·publication이 없으면 종료 후 1시간 |
| ACTIVE·OPEN·PARKED snapshot | 실제 lifecycle 종료까지; hot cache에서는 내릴 수 있음 |
| Backend 적용 확인된 DELIVERED outbox payload | aggregate가 active여도 confirmation 24시간 뒤 delivery receipt로 축약 |
| delivery receipt | confirmedAt부터 14일 |
| 공개된 terminal snapshot·tombstone | 적용 미확인 중에는 age purge 금지; confirmed 시점부터 14일 |
| local-only terminal tombstone | terminal 시점부터 14일 |
| FAILED_TERMINAL payload | age만으로 축약·waive 금지; 명시적 운영 복구 뒤 같은 payload를 retry할 때까지 보존 |
| correlation을 기다리는 terminal handoff marker | local terminal 또는 entry/review terminal 중 늦은 시점부터 최대 7일, 이후 marker를 `EXPIRED / UNBOUND_CONTEXT_EXPIRED` 처리 |
| processed entry/command dedup | workflow가 active인 동안 보존; terminal result 또는 마지막 accepted retry 중 늦은 시점부터 7일 |
| ACK된 evidence binary | 정상 시 최대 24시간, WARN 이상에서는 즉시 정리 가능 |
| 미ACK evidence binary | best effort, 최대 7일 또는 evidence quota·filesystem floor 도달 전까지 |
| evidence metadata | 관련 EvidenceArtifact·EvidenceUnavailable이 모두 confirmed된 시점부터 14일; 미확인·FAILED_TERMINAL publication은 purge를 막고 Incident tombstone이 더 길면 그 기간에 맞춤 |
| 지원 offline retry | 7일 |
| service log | 최대 7일이면서 log quota 이내 |

미ACK evidence가 7일 또는 storage pressure로 제거되면 다음을 보존한다.

```text
state = EVICTED
reason = RETENTION_EXPIRED 또는 STORAGE_PRESSURE
checksum / byteSize / capturedAt
incidentId / publicationRevision
evictedAt
```

이를 업로드 성공으로 기록하지 않는다. 삭제 전에는 진행 중 upload lease가 끝났는지 확인하고 metadata의 `EVICTION_PENDING/EVICTED` 전이를 durable workflow로 남긴다. 외부 publication revision에 귀속된 evidence에만 `EvidenceUnavailable` outbox를 만들며, crash가 발생하면 restart가 미완료 eviction을 계속한다.

미전송 outbox는 age만으로 조용히 삭제하지 않는다. offline retry 7일은 용량 설계와 운영 개입의 SLO다. quota에 도달하면 DRAIN으로 전환해 신규 durable 입력을 막고 기존 delivery와 정리를 우선한다.

## 8. 64GB SD 초기 예산

64GB 표기 용량 전체를 애플리케이션이 사용할 수 있다고 가정하지 않는다. JetPack·OS·runtime·model을 설치한 실제 filesystem을 기준으로 계산한다.

`[제안값]` 애플리케이션 가변 데이터의 최대 hard cap은 12GiB다. 실제 cap은 설치 직후 여유 공간과 30% 보호 floor를 함께 사용해 더 작아질 수 있다.

| 영역 | 최대 Hard cap | 비고 |
|---|---:|---|
| state DB, WAL, outbox, receipt·tombstone | 2GiB | 1.75GiB부터 신규 durable work 제한 |
| evidence spool | 8GiB | ACK된 파일부터 정리 |
| service log | 512MiB | rotation 필수 |
| temp·`.part` | 512MiB | restart 때 orphan 정리 |
| app safety reserve | 1GiB | transaction·checkpoint 여유 |

통제된 배포는 다음 식으로 장치별 mutable data cap과 evidence cap을 계산한다.

```text
deploymentBaselineFreeBytes = 설치·model 배포 완료 직후 측정한 root free bytes
deploymentBaselineAppDataBytes = 같은 시점에 이미 존재하는 app mutable bytes
protectedFloorBytes = rootTotalBytes × 0.30
effectiveMutableCap = max(0, min(12GiB,
    deploymentBaselineAppDataBytes + deploymentBaselineFreeBytes
    - protectedFloorBytes))
reservedNonEvidence = 2GiB + 512MiB + 512MiB + 1GiB
effectiveEvidenceCap = max(0, min(8GiB,
    effectiveMutableCap - reservedNonEvidence))
```

두 계산 결과는 DB의 `deployment_metadata`로 복구하지 않고 통제된 배포가
versioned deployment config로 주입한다. evidence 결과는 runtime의
`EVIDENCE_SPOOL_CAP_BYTES` 입력이 된다.
OS·runtime·model 설치량이 바뀌는 배포에서만 기존 app data를 포함해 다시
산정한다. runtime은 주입값을 검증·집행할 뿐 현재 free space를 새 설치
baseline으로 삼거나 cap을 임의로 늘리지 않는다. `appDataBytes`는 state 영역,
evidence, log와 temp의 실제 합이며 1GiB safety reserve는 사용량이 아니다.

정상 배포 승인 시 현재 watermark가 NORMAL이어야 한다. 즉 root free space가
42% 이상이고 각 실제 영역이 quota의 70% 미만이며
`appDataBytes < min(11GiB, effectiveMutableCap - 1GiB)`여야 한다.
`effectiveMutableCap ≤ reservedNonEvidence`인 장치도 승인하지 않는다.
evidence는 pilot의
최대 일일 발생량을 사용해 다음 조건도 만족해야 한다.

```text
baselineEvidenceBytes + pilotPeakDailyArtifactBytes × 7 + maxNextEvidenceSetBytes
≤ effectiveEvidenceCap × 0.85
```

`maxNextEvidenceSetBytes`는 한 Incident OPEN transaction이 예약할 수 있는 전체
evidence 합이다. 현재 최대 두 장과 artifact당 2MiB hard limit을 적용하면
4MiB다.

따라서 표의 8GiB evidence와 12GiB app cap은 항상 확보되는 할당량이 아니라
장치가 충분히 비어 있을 때의 상한이다.

### 8.1 Evidence 크기

`[제안값]` 기본 evidence는 다음으로 제한한다.

- Incident OPEN당 still image 1장, 규칙상 필요한 경우 최대 2장
- 최대 1280×720 JPEG
- 목표 512KiB 이하, artifact hard limit 2MiB
- video와 durable ring buffer 없음
- retry 때 새 이미지를 만들지 않음

hard limit을 만족하지 못하면 binary를 계속 쓰지 않고 `FAILED / RESOURCE_LIMIT` metadata를 남긴다.

RESOURCE_LIMIT 또는 storage eviction은 외부 Incident revision에 이미 귀속된 경우에만 같은 evidence identity의 `EvidenceUnavailable` publication을 만들며 upload 성공으로 취급하지 않는다. pre-OPEN artifact는 Incident OPEN 전까지 외부에 노출하지 않는다.

## 9. Storage watermark와 degraded 동작

하나라도 조건을 만족하면 더 높은 단계로 전환한다. percentage는 현재 root filesystem의 실제 total/free byte를 기준으로 한다.

| 단계 | 조건 `[제안값]` | 동작 |
|---|---|---|
| `NORMAL` | free space ≥ 40%, 각 영역 < 70% quota | 모든 기능 수행 |
| `WARN` | free space < 40% 또는 실제 영역 ≥ 70% quota | ACK evidence와 orphan·expired temp 정리, log rotate, upload 우선, health 경고 |
| `CRITICAL` | free space < 35% 또는 실제 영역 ≥ 85% quota | 새 binary evidence capture 전체 중지, RESOURCE_PRESSURE metadata·domain/outbox 기록 유지 |
| `DRAIN` | free space < 30% 또는 DB+WAL+outbox+receipt ≥ 1.75GiB 또는 app data ≥ `min(11GiB, effectiveMutableCap - 1GiB)` | readiness false, 새 durable scope·Candidate·evidence와 새 업무를 만드는 inbound·non-terminal publication 중지; 기존 scope의 terminal 전이·publication, delivery·정리·health 우선 |

30% filesystem floor를 침범하면서 신규 데이터를 계속 받지 않는다. evidence를 먼저 축소하고 마지막에 admission을 중지한다. DRAIN에서는 camera·inference를 drain-only mode로 유지하고 usable write reserve 안에서 기존 scope의 bounded checkpoint, RESOLVE·UNPARKED·EXIT와 그 outbox를 우선 기록한다. 기존 scope를 terminal로 만드는 authoritative inbound와 이미 접수한 identity의 멱등 retry만 reserve 안에서 허용한다.

drain-only mode는 기존 confirmed scope의 terminal-progress 경로만 관측한다. 예를 들어 PARKED→MOVE_PENDING→ENDED, OPEN→CLEAR_PENDING→RESOLVED, INSIDE→EXITING→ENDED는 reserve 안에서 진행할 수 있다. 반대로 STOP_PENDING→PARKED, CANDIDATE→OPEN처럼 새 durable 사실·publication을 확장하는 경로는 현재 state와 trusted timer 하한을 유지하고 observation을 `UNKNOWN / RESOURCE_PRESSURE`로 둔다. 복구 뒤 정상 sample부터 재개하며 DRAIN 시간을 소급 누적하지 않는다.

```text
usableWriteReserve = max(0, min(
    currentRootFreeBytes - protectedFloorBytes,
    effectiveMutableCap - appDataBytes,
    2GiB - stateRegionBytes))
```

1GiB app safety reserve는 목표 상한이고 state 영역이 1.75GiB에서 DRAIN에 들어오면 실제 reserve는 최대 256MiB다. 다음 최악 크기 write가 usableWriteReserve를 넘으면 해당 전이를 메모리에서만 만들지 않고 observation·readiness를 UNKNOWN/NOT_READY로 둔다.

disk 상태는 `[제안값]` 30초마다 그리고 모든 DB·evidence·temp·log write 전에 `현재 사용량 + 예약한 다음 write 상한`으로 검사한다. 5분 연속으로 다음을 만족하면 한 단계씩 복귀한다.

- DRAIN 해제: free ≥ 32%, DB 영역 < 1.5GiB, app data < `min(10GiB, effectiveMutableCap - 2GiB)`
- CRITICAL 해제: free ≥ 37%, 실제 영역 < 80% quota
- WARN 해제: free ≥ 42%, 실제 영역 < 65% quota

prospective check를 구현하려면 저장소 ADR에서 `maxSerializedOutboxPayloadBytes`, `maxDbTransactionAndWalGrowthBytes`, WAL checkpoint·rotation 상한, `maxTempWriteBytes`, `maxLogWriteBytes`를 반드시 정해야 한다. 하나의 in-process quota governor가 모든 app writer의 byte budget을 atomic reservation·settlement로 직렬화하고 commit 직전 root free space를 다시 검사해야 한다. evidence의 현재 artifact 상한은 2MiB, evidence set 상한은 4MiB다. 이 값과 실제 schema가 확정되기 전에는 reserve 검증을 완료한 것으로 보지 않는다.

## 10. Runtime 자원 경계

현재 8GB 통합 메모리 장치에서는 다음을 기본으로 한다.

- camera 1대
- YOLOv8n, batch 1
- model/inference owner 1개
- API worker 1개
- frame queue 최대 2장
- evidence encoder concurrency 1
- raw frame과 반복 bbox 비영속
- LED·speaker는 event-driven projection

입력 해상도, TensorRT FP16 여부와 목표 FPS는 실측 전 `[제안값]`이다. 같은 process 또는 장치에서 model worker를 복제하지 않는다. queue가 가득 차면 가장 오래된 ephemeral frame을 drop하고 counter를 올리며 queue를 확장하지 않는다.

## 11. Health와 검증 기준

health는 최소한 다음을 구분한다.

```text
store writable / integrity
filesystem free bytes와 watermark
camera heartbeat
model loaded
last valid inference time
oldest pending outbox age와 개수
evidence spool bytes
active UNKNOWN count와 최장 지속 시간
MemAvailable과 swap 증감
thermal throttle count
frame drop counter
```

구현 완료 판단에는 최소한 다음 검증이 필요하다.

1. domain state와 outbox commit 사이 강제 종료 후 복구
2. ACK 직전·직후 강제 종료와 중복 retry
3. PARKED·OPEN 상태 재시작 후 identity 재연결
4. camera 장애 중 trusted timer 미누적
5. evidence `.part`와 orphan file 복구
6. WARN·CRITICAL·DRAIN watermark 강제 도달과 복귀
7. `baselineDbRegionBytes + sevenDayPeakGrowthBytes + maxDbTransactionAndWalGrowthBytes < 1.5GiB`인지 7일 offline 모사로 확인
8. model/engine hash, input size, precision과 camera 수를 고정한 실제 Jetson 24시간 soak test
9. `[제안값]` OOM 0회, 지속 swap 증가 없음, thermal throttle 0회, soak 전체 sample의 `min(MemAvailable) ≥ 1GiB`
10. `baselineEvidenceBytes + pilotPeakDailyArtifactBytes × 7 + maxNextEvidenceSetBytes ≤ effectiveEvidenceCap × 0.85`

이 측정 전까지 8GB 적합성은 설계 가정이며 검증 완료로 표시하지 않는다.

24시간 soak는 자원 적합성 검증이지 탐지 정확도 검증이 아니다. 배포 전에는 model·dataset version을 고정하고 별도 labeled scenario에서 차량 미탐지로 인한 거짓 `NOT_PRESENT_CONFIRMED`와 주차·Incident 판정 품질을 검증해야 하며 합격 metric은 모델 평가 계약에서 정한다.

## 12. 보존 불변조건

1. 공개 전이와 outbox는 한 transaction이다.
2. 성공 응답은 durable acceptance 뒤에만 반환한다.
3. retry payload·revision·Idempotency-Key는 immutable이다.
4. 같은 aggregate의 뒤 revision을 앞 revision보다 먼저 보내지 않는다.
5. restart와 downtime은 새 domain 사실이나 trusted time이 아니다.
6. raw frame과 반복 signal을 durable store에 쓰지 않는다.
7. evidence eviction은 Incident RESOLVE나 delivery 성공을 만들지 않는다.
8. storage pressure에서는 evidence capture 중지 후 admission DRAIN 순서로 축소한다.
9. device replacement와 Backend snapshot 복구를 이 계약에 암묵적으로 포함하지 않는다.
