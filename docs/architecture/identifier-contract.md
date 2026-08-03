# 식별자 수명 및 매핑 계약

> 상태: Draft · 범위: Raspberry Pi–Jetson–Backend 목표 식별자 계약

이 문서는 세 시스템이 생성하거나 사용하는 식별자의 의미, 생성 책임, 유일성 범위, 수명과 전달 경계를 정의한다. API 필드의 의미상 정본 이름은 `camelCase`, 하드웨어 Python 내부 타입은 `PascalCase`로 표기한다. Endpoint·DTO 구조와 전송 스칼라 타입은 후속 API 계약의 범위다.

## 한눈에 보기

### 범주별 식별자

| 범주 | 식별자 |
|---|---|
| 기준 정보 | `vehicleId`, `zoneId` |
| 차량 추적 관측 | `trackSegmentId`, `physicalVehicleId` |
| 입차 시도 | `entryAttemptId` |
| 주차 세션 | `sessionId` |
| 공간·주차 수명주기 | `zoneVisitId`, `parkingEpisodeId` |
| 연결·관계 | `contextBindingId`, `blockingRelationId` |
| 사건·증거 | `incidentId`, `evidenceId` |
| Backend 업무 | `eventId`, `requestId` |

### 대표 활성 수명

아래 도식은 대표적인 정상 흐름에서 scope가 함께 존재하는 구간을 보여준다. 가로 길이는 실제 시간을 뜻하지 않으며 Candidate 취소 같은 단축 경로와 정확한 terminal 조건은 아래 `식별자 의미와 수명` 표가 정본이다.

```text
시간 ─────────────────────────────────────────────────────────────────▶

[기준 정보]
vehicleId             등록 차량 기준 정보
zoneId                배포된 공간 기준 정보

[입차·실차]
entryAttemptId        ├─ 입차 인식·판단 ────────────────┤
sessionId                 ├─ Backend ParkingSession ──────────────────────┤
physicalVehicleId         ├─ 실차 가설 ─ track 연결·재연결 ─ departure ─┤
trackSegmentId A              ├─ 연속 추적 A ─┤
trackSegmentId B                                ├─ 연속 추적 B ─┤
contextBindingId            ├─ 검증된 binding ─ active correlation ───┤

[공간·주차·사건]
zoneVisitId                   ├─ 진입 후보 ─ INSIDE ─ 이탈 ─┤
parkingEpisodeId A              ├─ 정지 후보 ─ PARKED ─ 이동 ─┤
parkingEpisodeId B                                         ├─ 재정지 ─ PARKED ─┤
blockingRelationId                 ├─ 관계 후보 ─ 확정 ─ 해소 ─┤
incidentId                            ├─ Candidate ─ OPEN ─ RESOLVED ─┤
evidenceId                                ├─ capture ─ upload·retry ─ retention ─┤
```

## 공통 불변식

- 식별자의 의미 타입은 값의 일부다. 같은 정수여도 `sessionId`, `eventId`, `requestId`는 서로 비교하거나 변환하지 않는다.
- 수명주기 종료, record 삭제와 식별자 재사용은 별개다. UUID 기반 도메인 식별자는 terminal 이후에도 재사용하지 않으며, 예외적인 로컬·Backend 식별자의 유일성 범위는 아래 표를 따른다.
- `trackSegmentId`는 관측 구현의 로컬 ID이고, `physicalVehicleId`는 Jetson의 실차 가설이며, `vehicleId`는 Backend의 등록 차량 ID다. 세 식별자는 서로 대체하지 않는다.
- Binding과 correlation은 기존 식별자 사이의 관계를 기록할 뿐 식별자의 의미나 값을 바꾸지 않는다.
- 네트워크 retry는 새 도메인 ID, `publicationRevision`, `decisionRevision`, `contextRevision`, `verificationAttempt`를 만들지 않는다.

## 식별자 의미와 수명

| 식별자 | 의미·생성 책임 | 유일성 범위 | 수명과 재사용 규칙 |
|---|---|---|---|
| `vehicleId` | Backend가 생성하는 등록 차량 기준 정보 | Backend `Vehicle` namespace | Backend 기준 정보 수명주기를 따른다. Jetson은 opaque ID로 취급하며 `physicalVehicleId`로 사용하지 않는다. |
| `zoneId` | 공유 ZoneDefinition이 정의하는 주차면·`AISLE`·`ENTRY_EXIT` 공간 | 한 deployment | 해석에는 함께 배포된 `zoneDefinitionVersion`이 필요하다. 같은 deployment에서 다른 물리 공간에 재할당하지 않는다. |
| `trackSegmentId` | ByteTrack이 생성한 한 연속 추적 구간 | 한 tracker process·stream runtime | 구간마다 새 ID를 사용한다. process 재시작을 넘는 저장·외부 correlation에는 사용하지 않는다. |
| `physicalVehicleId` | Jetson이 동일 실차로 판단한 관측 가설 | UUID namespace | 가설 생성부터 후보 취소 또는 physical departure와 child 정리 후 `RETIRED`까지 유효하다. 여러 `trackSegmentId`를 포함할 수 있고 terminal 후 재사용하지 않는다. |
| `entryAttemptId` | Backend 호출 전에 entry capture upstream이 생성하는 한 번의 물리적 입차 인식·판단 시도 | UUID namespace | `ALLOW`, `DENY`, `REVIEW_PENDING`과 그 최종 해소를 같은 ID로 correlation한다. authoritative `sessionId`는 최대 하나다. 같은 입차 시도의 session 교체는 지원하지 않으며, 별도의 실제 입차 시도에만 새 `entryAttemptId`와 `sessionId`를 사용한다. 현재 Raspberry Pi wire `trackingId`는 이 의미의 alias다. |
| `sessionId` | Backend가 생성하는 `ParkingSession` ID | Backend `ParkingSession` namespace | Backend가 수명을 소유하고 Jetson은 mirror·correlation에만 사용한다. 같은 실차가 binding된 동안 여러 `parkingEpisodeId`가 이 session과 연관될 수 있다. |
| `zoneVisitId` | Jetson이 생성하는 한 실차와 한 zone 사이의 연속 방문 | UUID namespace | 진입 후보 생성부터 후보 취소 또는 이탈 확정까지 유효하다. 같은 실차가 같은 zone을 다시 방문하면 새 ID를 사용한다. |
| `parkingEpisodeId` | Jetson이 생성하는 한 실차의 연속 정지·주차 행위 | UUID namespace | 정지 후보 생성부터 후보 취소, 이동 확정 또는 physical exit terminal까지 유효하다. 재정지·재주차에는 새 ID를 사용한다. |
| `contextBindingId` | Jetson이 검증된 `entryAttemptId`·`sessionId`·`physicalVehicleId` 연결에 부여하는 ID | UUID namespace | 결합된 식별자는 생성 후 바꾸지 않는다. active binding 종료와 record 보존·삭제는 별개이며 ID를 재사용하지 않는다. |
| `blockingRelationId` | Jetson이 순서가 있는 (`subjectPhysicalVehicleId`, `victimPhysicalVehicleId`, `egressZoneId`) 방해 관계 Candidate에 부여하는 ID | UUID namespace | Candidate 생성부터 후보 취소, 관계 해소 또는 관련 physical exit terminal까지 유효하다. 이후 새 관계에는 새 ID를 사용한다. |
| `incidentId` | Jetson IncidentReducer가 위반 Candidate에 부여하는 ID | UUID namespace | Candidate 생성 시 발급한다. Candidate 취소로 로컬에서 끝나거나 `OPEN` 뒤 `RESOLVED`까지 유지한다. `OPEN` 전에는 외부에 노출하지 않고 재사용하지 않는다. |
| `evidenceId` | Jetson이 한 논리적 증거 capture 예약에 부여하는 ID | UUID namespace | 생성·업로드·retry에서 같은 ID를 유지한다. 로컬 binary 삭제나 unavailable 결과가 ID 재사용을 허용하지 않는다. |
| `eventId` | Backend가 Incident를 업무 사건으로 투영할 때 생성할 수 있는 ID | Backend `ParkingEvent` namespace | Backend-owned opaque correlation이다. 생성 조건과 업무 수명주기는 후속 API 계약이 정한다. |
| `requestId` | Backend가 이동 요청에 부여하는 ID | Backend `MoveRequest` namespace | Backend-owned opaque correlation이다. 같은 `subjectPhysicalVehicleId`의 여러 Incident가 한 request와 연관될 수 있으므로 `incidentId`와 1:1을 전제하지 않는다. |

`entryAttemptId`는 의미상 정본 이름이다. 현행 `trackingId`와의 wire 호환 mapping은 후속 API 계약에서 명시하며, ByteTrack의 `trackSegmentId`와는 관계가 없다.

`IncidentKey`는 규칙별 중복 Incident 생성을 막는 Jetson-local composite key이며 공개 식별자가 아니다. 외부 correlation에는 공개된 `incidentId`를 사용한다.

## 연결 cardinality

- authoritative `entryAttemptId`와 `sessionId`는 최대 1:1이다. 같은 실제 입차에 다른 ID를 발급해 session을 교체하지 않는다.
- 한 `sessionId`와 한 `physicalVehicleId`에는 각각 active authoritative `ContextBinding`이 최대 하나다. Binding의 상대 식별자를 바꾸지 않는다.
- 한 `zoneVisitId`와 `parkingEpisodeId`는 각각 정확히 한 `physicalVehicleId`에 속한다. 한 `parkingEpisodeId`에 연관되는 authoritative `sessionId`는 최대 하나다.
- 한 `requestId`가 여러 Incident를 묶을 수 있지만 모두 같은 `subjectPhysicalVehicleId`를 가져야 한다. 다른 subject의 이동 확인은 별도 request로 만든다.

## 목표 하드웨어 타입과 책임 경계

아래 경로는 목표 구현의 책임 경계다. 현재 구현 여부를 나타내는 inventory가 아니며, `현재`로 표시한 항목만 현행 호환 이름을 설명한다.

| 계약 식별자 | 목표 내부 타입 | 타입 정의·값 생성 책임 | 전달 범위 |
|---|---|---|---|
| `trackSegmentId` | `TrackSegmentId` (`int`) | Jetson `tracking/models.py`; `tracking/adapters/ultralytics_bytetrack.py` | Jetson Tracking 내부 |
| `physicalVehicleId` | `PhysicalVehicleId` (`UUID`) | Jetson `tracking/models.py`; `tracking/entity_resolver.py` | Jetson Tracking → Parking·Communication → Backend handoff |
| `entryAttemptId` | `EntryAttemptId` (`UUID`) | 목표 domain type; entry capture upstream이 생성. 현재 Raspberry Pi는 `trackingId`라는 이름으로 UUID 생성 | Raspberry Pi·Backend → Jetson 입차 context; Jetson → Backend handoff |
| `sessionId` | `ParkingSessionId` (`int`) | Jetson `tracking/models.py`; Backend `ParkingSession` DB가 생성 | Backend 응답 → Raspberry Pi → Jetson 입차 context |
| `vehicleId` | `VehicleId` (`int`) | Jetson `tracking/models.py`; Backend 차량 등록 DB가 생성 | Backend 응답 → Raspberry Pi → Jetson 입차 context |
| `zoneId` | `ZoneId` (`int`) | Jetson `parking/models.py`; 공유 ZoneDefinition snapshot 제작 과정이 생성 | Jetson `ZoneRegistry`; Backend·Frontend projection |
| `zoneVisitId` | `ZoneVisitId` (`UUID`) | Jetson `parking/models.py`; `parking/zone_visit_tracker.py` | Jetson domain → 규칙·`IncidentKey`; 외부 전달 여부는 후속 API 계약 |
| `parkingEpisodeId` | `ParkingEpisodeId` (`UUID`) | Jetson `parking/models.py`; `parking/parking_episode_tracker.py` | `ParkingEpisode` → 규칙; Jetson → Backend handoff |
| `contextBindingId` | `ContextBindingId` (`UUID`) | 목표 Jetson domain type; `ContextBinding` 생성 시 | Jetson domain 내부; 외부 전달 여부는 후속 API 계약 |
| `blockingRelationId` | `BlockingRelationId` (`UUID`) | 목표 Jetson domain type; `BlockingRelation` Candidate 생성 시 | Jetson domain → `IncidentKey`; 외부 전달 여부는 후속 API 계약 |
| `incidentId` | `IncidentId` (`UUID`) | Jetson `parking/models.py`; `parking/incident_reducer.py`가 Candidate 생성 시 | Jetson Parking → Communication → Backend; `OPEN` 전 외부 미노출 |
| `evidenceId` | `EvidenceId` (`UUID`) | 목표 Jetson communication type; evidence capture 예약 시 | Jetson Evidence → Backend handoff |
| `eventId` | `ParkingEventId` (`int`) | Jetson `communication/models.py`; Backend `ParkingEvent` DB가 생성 | Backend 사건 응답 → Jetson Communication |
| `requestId` | `MoveRequestId` (`int`) | Jetson `communication/models.py`; Backend `MoveRequest` DB가 생성 | Backend 이동 확인 명령 → Jetson Communication·결과 correlation |

UUID 기반 식별자는 JSON에서 UUID 문자열로 직렬화한다. 정수 기반 식별자의 wire 타입은 후속 API 계약에서 정한다. JSON number를 선택하려면 모든 consumer에 대해 JavaScript safe integer 범위(`Number.MAX_SAFE_INTEGER`)를 보장해야 하며, 보장할 수 없다면 decimal string을 사용한다.

Jetson은 `eventId`와 `requestId`를 생성하지 않는다. 수신한 `requestId`는 이동 확인 결과의 correlation에 그대로 사용한다.

## 식별자가 아닌 version·sequence

| 값 | 생성 권위·순서 범위 | 의미 |
|---|---|---|
| `publicationRevision` | Jetson aggregate owner; aggregate별 단조 증가 | 같은 aggregate가 외부에 공개한 전이 순서 |
| `recordVersion` | Jetson local store; record별 단조 증가 | local record의 동시성 제어 version |
| `zoneDefinitionVersion` | ZoneDefinition 배포 주체; deployment별 단조 증가 | 함께 배포된 ZoneDefinition snapshot의 version |
| `decisionRevision` | Backend; `entryAttemptId`별 단조 증가 | 초기 결정과 `REVIEW_PENDING` 해소 순서. 확정된 결정을 다시 쓰는 권한이 아니다. |
| `contextRevision` | Backend; `entryAttemptId`의 authoritative context stream별 단조 증가 | 같은 session/context와, 존재하는 경우 그 immutable binding에 대한 행정 상태·자격·context 갱신 순서. 다른 session이나 physical vehicle로 rebinding하는 권한이 아니다. |
| `verificationAttempt` | Backend command owner; `requestId`별 단조 증가 | 이동 재확인 순번. 이동 확인 command identity는 (`requestId`, `verificationAttempt`)다. |

이 값들은 scope identity를 대체하지 않는다. 동일 요청의 네트워크 retry는 기존 ID와 version·sequence를 그대로 사용한다.
