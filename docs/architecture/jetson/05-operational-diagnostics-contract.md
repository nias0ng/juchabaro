# Jetson 운영 진단 질문 및 이벤트 계약

> 상태: Draft · 범위: 현장 오판 원인 재구성을 위한 비영속 진단

## 목적과 경계

[결정] 진단 이벤트는 도메인 상태, Backend 공개 전이, evidence 원본의 정본이 아니다. 이미 계산된 입력·후보·판단·거절 근거를 구조화해 남기며, 진단 adapter 장애는 frame 처리나 도메인 결정을 실패시키지 않는다.

[결정] 이미지·crop bytes, 번호판, HTTP payload, API key 같은 민감하거나 큰 값은 기록하지 않는다. 사건을 잇는 데 필요한 식별자와 scalar 지표만 기록한다.

## 반드시 답할 질문

| 축 | 운영 질문 | 진단 이벤트 | 필요한 상관·판단 필드 |
|---|---|---|---|
| 탐지 | 해당 frame에서 YOLO는 차량 후보를 몇 개 냈고, 어떤 class·confidence 후보가 tracking에서 탈락했는가? 추론 시간과 유효 FPS는 얼마인가? | `DETECTION_FRAME_EVALUATED` | `cameraId`, `frameId`, 탐지/추적 수, class별 수, confidence 범위, 추론 시간 |
| 동일성 | TrackSegment가 왜 기존 차량에 연결·신규 생성·미해결되었는가? 어느 후보와 점수·간격·기하 지표를 비교했는가? | `IDENTITY_RESOLUTION_EVALUATED` | `trackSegmentId`, `physicalVehicleId`, `outcome`, `reason`, 후보 수, score·margin·gap·IoU·거리·면적비 |
| 입차 매칭 | 입차 결정 시점에 ENTRY_EXIT 폴리곤 안의 후보는 누구였고, overlap·deadline·점유 충돌 중 무엇 때문에 선택 또는 거절됐는가? | `ENTRY_MATCH_EVALUATED` | `entryAttemptId`, 후보 차량 ID, zone ID, overlap, deadline, 선택/거절 이유 |
| 주차 자격 | 왜 이 차량에 주차 판정을 시작했는가? ENTRY_EXIT 제외 조건, stationary 누적, 주차면 배정 후보와 애매성은 무엇이었는가? | `PARKING_ELIGIBILITY_EVALUATED` | 차량 ID, zone visit, stationary 시간, 배정 zone/overlap/margin, 자격 결과·이유 |
| 출차 | 부재 시간만 충족한 것인가, EXIT 방문과 외향 통과도 충족했는가? 어느 조건에서 보류·확정됐는가? | `EXIT_TRAVERSAL_EVALUATED` | 차량 ID, trusted absence, EXIT visit, 기준선 offset/방향, 결과·거절 이유 |
| 사건·구역 | incident의 rule과 scope는 무엇이며 `zoneId`는 어느 판정에서 왔거나 왜 `null`인가? | `INCIDENT_PROJECTION_EVALUATED` | incident/episode/vehicle ID, rule, scope, zone ID와 provenance, 술어 결과 |
| 증거·전송 | 기대 crop 수와 실제 생성 수가 같은가? Incident OPEN 적용 전 업로드했는가? 실패는 재시도 가능한가? | `EVIDENCE_PUBLICATION_EVALUATED` | incident/evidence/delivery ID, 기대/생성 수, crop kind, 선행 전이 상태, HTTP/application 결과, retry 분류 |

## 공통 규칙

1. 이벤트 시각은 timezone-aware `occurredAt`을 사용한다.
2. frame 판단은 `cameraId`와 `frameId`, 도메인 경계는 해당 UUID/ID로 연결한다.
3. 결과만 남기지 않고 후보 수, 적용 임계값, 선택 또는 거절 이유를 함께 남긴다.
4. 매 frame의 정상 반복값은 남기지 않는다. 경계 변화, 미해결, 거절, 실패를 우선 기록한다.
5. 테스트는 로그 문장 전체가 아니라 event type과 구조화 필드를 검증한다.

## 구현 범위와 출력 빈도

[결정] `LoggingDiagnosticsAdapter`는 한 줄 JSON application log를 만들며 위 7개 이벤트를 모두 실제 판단 경계에 연결한다.

- 탐지는 detection/tracking 수·상태·class 구성이 달라질 때와 추론 실패 시 기록한다.
- 동일성은 `CREATED`, `REIDENTIFIED`, `UNRESOLVED` 경계만 기록하고 정상 `CONTINUED`는 생략한다.
- 입차는 pending attempt의 매칭·보류·만료, 주차는 episode 상태 경계에서 기록한다.
- 출차는 부재 확정 뒤 EXIT outward contact를 최종 평가할 때 기록한다.
- Incident는 공개 `OPEN`·`RESOLVE` projection마다 zone provenance를 기록한다.
- Evidence는 capture 요청·완료·실패와 Backend 전송 시도·성공·retry·영구 실패를 기록한다.
- 모든 이벤트는 기존 계산 결과를 투영하며 관측을 위해 도메인 점수나 후보를 다시 결정하지 않는다.

## 비목표

- 이번 단계에서 identity, 입차, 주차, 출차, incident, evidence 알고리즘을 변경하지 않는다.
- 진단 이벤트를 SQLite나 Backend에 영속하지 않는다.
- 로그만으로 누락된 도메인 전이를 사후 생성하거나 보정하지 않는다.
