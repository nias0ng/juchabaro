# 식별자 수명 및 매핑 계약

이 문서는 Raspberry Pi, Jetson, Backend가 공유하는 식별자의 의미와 수명, 생성 책임, 전달 경로를 고정한다.  
API·JSON에서는 `camelCase` 계약 이름을, 하드웨어 Python 코드에서는 전용 의미 타입을 사용한다.

## 범주별 식별자

| 범주 | 식별자 |
|---|---|
| 기준 정보 | `vehicleId`, `zoneId` |
| 차량 추적 관측 | `trackSegmentId`, `physicalVehicleId` |
| 입차·주차 세션 | `sessionId` |
| 공간·주차 수명주기 | `zoneVisitId`, `parkingEpisodeId` |
| Jetson 사건 | `incidentId` |
| Backend 업무 | `eventId`, `requestId` |

## 시간축

`vehicleId`는 등록 차량, `zoneId`는 주차구역을 가리키는 기준 정보이며 아래 실행 수명주기에 포함되지 않는다.

```text
[기준 정보]

vehicleId  등록 차량 기준 정보
zoneId     주차구역 기준 정보


[시간에 따라 생성·종료되는 식별자]

sessionId            ├──────── ALLOW된 Backend 주차 세션 ─────┤

physicalVehicleId        ├──── Jetson이 같은 실차로 보는 관측 기간 ───┤
trackSegmentId           ├─ ByteTrack 구간 ─┤ ├─ 다음 구간 ──┤

zoneVisitId                  ├─ 공간 관계: 진입 후보 → 구역 내부 → 이탈 확정 ─┤
parkingEpisodeId             ├─ 주차 행위: 정지 후보 → 주차 확정 → 이동 확정 ─┤

incidentId                       ├─ 후보 → OPEN → RESOLVE ──────┤
eventId                              ├─ Backend 사건 처리 ─────┤
requestId                            ├─ 이동 요청 → 완료 ──────┤
```

하나의 `sessionId` 안에서 차량의 재이동과 재주차에 따라 여러 `parkingEpisodeId`가 순차적으로 생성될 수 있다.

`zoneVisitId`는 한 물리 차량이 특정 구역에 진입하기 시작한 시점부터 이탈이 확정될 때까지 이어지는 하나의 공간적 방문을 식별한다.   
같은 차량이 같은 구역을 다시 방문하면 새로운 `zoneVisitId`가 생성된다.

`parkingEpisodeId`는 한 물리 차량이 정지 후보가 된 시점부터 주차 확정과 이후 이동 확정까지 이어지는 하나의 정지·주차 행위를 식별한다.

`ZoneVisit`은 한 물리 차량과 특정 구역 사이의 공간적 관계를 나타내고, `ParkingEpisode`는 차량의 연속된 정지·주차 행위를 나타낸다.  
두 수명주기는 각각 공간 관측과 이동 관측을 기준으로 갱신되며, 위반 규칙을 평가할 때 필요한 조합으로 함께 해석한다.

시간축의 종료는 활성 수명주기의 종료를 의미한다.

## 하드웨어 내부 타입

| 하드웨어 내부 타입 | 기반 타입 |
|---|---|
| `TrackSegmentId` | `int` |
| `PhysicalVehicleId` | `UUID` |
| `ParkingSessionId` | `int` |
| `VehicleId` | `int` |
| `ZoneId` | `int` |
| `ZoneVisitId` | `UUID` |
| `ParkingEpisodeId` | `UUID` |
| `IncidentId` | `UUID` |
| `ParkingEventId` | `int` |
| `MoveRequestId` | `int` |

UUID 기반 식별자는 JSON에서 문자열로 직렬화하고 Backend DB 기반 식별자는 JSON number로 전달한다.

## 정의·생성·전달 위치

| 계약 식별자 | 하드웨어 내부 타입 | 타입 정의 위치 | 값 생성 위치 | 수신·전달 경로 |
|---|---|---|---|---|
| `trackSegmentId` | `TrackSegmentId` | Jetson `tracking/models.py` | Jetson `tracking/adapters/ultralytics_bytetrack.py` | Jetson Tracking 내부 |
| `physicalVehicleId` | `PhysicalVehicleId` | Jetson `tracking/models.py` | Jetson `tracking/entity_resolver.py` | Jetson Tracking → Parking |
| `sessionId` | `ParkingSessionId` | Jetson `tracking/models.py` | Backend `ParkingSession` DB INSERT | Backend 응답 → RPi → Jetson `EntryContext` |
| `vehicleId` | `VehicleId` | Jetson `tracking/models.py` | Backend 차량 등록 DB INSERT | Backend 응답 → RPi → Jetson `EntryContext` |
| `zoneId` | `ZoneId` | Jetson `parking/models.py` | 공유 구역 데이터 제작·배포 | Jetson `ZoneRegistry`, Backend DB |
| `zoneVisitId` | `ZoneVisitId` | Jetson `parking/models.py` | Jetson `parking/zone_visit_tracker.py` | `ZoneVisit` → 규칙 → `IncidentKey` |
| `parkingEpisodeId` | `ParkingEpisodeId` | Jetson `parking/models.py` | Jetson `parking/parking_episode_tracker.py` | `ParkingEpisode` → 규칙 → `IncidentKey` |
| `incidentId` | `IncidentId` | Jetson `parking/models.py` | Jetson `parking/incident_reducer.py` | Jetson Parking → Communication → Backend |
| `eventId` | `ParkingEventId` | Jetson `communication/models.py` | Backend `ParkingEvent` DB INSERT | Backend 사건 응답 → Jetson Communication |
| `requestId` | `MoveRequestId` | Jetson `communication/models.py` | Backend `MoveRequest` DB INSERT | 사건 응답·이동 확인 명령 → Jetson Communication |

Backend는 Jetson의 최초 사건 `OPEN`을 처리하며 `eventId`와 `requestId`를 생성해 함께 반환한다.  
동일한 `incidentId`의 재전송·갱신·해소는 기존 `eventId`와 `requestId`를 유지한다.  
Jetson은 두 ID를 생성하지 않고 Communication DTO로 수신하며, 이동 확인 결과에서 받은 `requestId`를 그대로 반환한다.
