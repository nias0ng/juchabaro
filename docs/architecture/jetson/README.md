# Jetson 도메인 설계 문서

> 상태: Draft · 관련 이슈: S15P11E202-461 · 범위: Jetson target domain contract

이 문서 묶음은 카메라와 tracker의 불완전한 관측을 Jetson이 어떤 시간적 도메인 사실로 해석하고, 그 사실을 Backend가 사용할 수 있는 전이로 어떻게 표현할지를 정의한다.

## 설계 기준

1. Jetson은 단일 frame의 탐지 결과가 아니라 시간에 걸쳐 확인된 사실을 만든다.
2. domain state, observation state, delivery state를 분리한다.
3. 관측 소실은 차량·구역 방문·주차·사건의 종료가 아니다.
4. 차량 이동은 주차 episode를 끝내지만 Incident 해소를 직접 의미하지 않는다.
5. Incident는 이동 뒤 규칙을 다시 평가하고, 위반 술어의 불성립이 확인될 때만 해소한다.
6. 공개 전이와 outbox 기록은 하나의 영속 transaction으로 확정한다.
7. Jetson의 현장 판정과 Backend의 업무 처리·관리자 판단을 구분한다.
8. 보존 기간과 저장량은 8GB 통합 메모리·64GB SD의 상한 안에서 제한한다.

## 대상 장치 가정

현재 설계가 대상으로 하는 기본 배포는 다음과 같다.

- CPU와 GPU가 8GB 메모리를 공유하는 Jetson 한 대
- 64GB SD 저장장치
- 카메라 한 대와 사각지대가 없는 모형 주차 구역
- fine-tuned YOLOv8n, batch 1, 단일 inference pipeline
- LED 두 개와 speaker 한 개

입력 해상도, inference FPS, TensorRT precision과 evidence 발생량은 구현·실측으로 확정한다. 카메라 추가, 다중 Jetson, 장치 교체 복구는 이 문서의 대상이 아니다.

## 문서 구성

| 순서 | 문서 | 단일 책임 |
|---|---|---|
| 1 | [도메인 목적 및 출력 계약](./01-domain-purpose-and-output-contract.md) | Jetson이 만드는 사실과 외부 handoff의 의미 |
| 2 | [Scope 수명주기 계약](./02-scope-lifecycle-contract.md) | 각 scope의 상태·식별자·전이 조건 |
| 3 | [Scope 전파 및 종료 계약](./03-scope-propagation-contract.md) | 한 scope의 변화가 다른 scope에 미치는 영향 |
| 4 | [상태 보존 및 Retention 계약](./04-durable-state-and-retention-contract.md) | 동일 장치 재시작, outbox, evidence와 저장 상한 |
| 5 | [운영 진단 질문 및 이벤트 계약](./05-operational-diagnostics-contract.md) | 현장 오판의 원인을 재구성하는 비영속 관측 경계 |

정의의 정본은 한 문서에만 둔다. `01`은 handoff 의미, `02`는 상태 전이, `03`은 전파, `04`는 영속성과 보존, `05`는 비영속 운영 진단을 담당하며 다른 문서의 정의를 반복하지 않는다.

## 결정 수준

| 표시 | 의미 |
|---|---|
| `[결정]` | 이번 Jetson 도메인 설계에서 채택한 기준 |
| `[제안값]` | 장치 실측이나 팀 합의 뒤 조정할 수 있는 초기값 |
| `[후속 계약]` | Jetson 도메인 이후 Backend·Frontend·배포 계약에서 확정할 항목 |

문서 전체 상태는 Backend API와 운영 기준이 합의될 때까지 `Draft`다. `[결정]`은 Draft 안에서도 구현이 따라야 할 Jetson 내부 결정을 뜻한다.

## 문서 경계

이 문서 묶음은 다음을 다룬다.

- 물리 차량, 구역 방문, 주차, 차단 관계와 Incident lifecycle
- `UNKNOWN`과 신뢰 가능한 차량 부재의 구분
- 입차 문맥과 물리 차량의 비동기 연결
- PARKED·UNPARKED·Incident·EXIT·이동 확인 결과의 의미
- 동일 Jetson·동일 저장장치에서의 재시작 복구
- transactional outbox와 제한된 evidence 보존
- 저장공간 pressure에서의 degraded 동작

다음은 후속 계약으로 남긴다.

- endpoint, HTTP method, DTO와 인증 방식
- Backend 업무 상태와 Frontend read model의 구체적인 mapping
- 법령 기반 EV 허용 시간의 실제 값과 출처
- DB schema, repository·service interface와 migration
- TensorRT 변환, 서비스 기동과 성능 튜닝 절차

다음은 현재 범위에서 제외한다.

- 다른 Jetson으로의 device replacement
- stale backup과 Backend snapshot을 이용한 상태 역복구
- 양방향 manifest/snapshot reconciliation
- 장치 간 writer fencing과 retention window 협상
- 원본 CCTV 영상의 장기 저장

## 관련 계약

공유 식별자의 의미는 [식별자 수명 및 매핑 계약](../identifier-contract.md)을 따른다. API·JSON 필드와 현재 코드가 이 목표 의미와 다른 경우 후속 연동 계약에서 migration과 compatibility를 명시한다.
