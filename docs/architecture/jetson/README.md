# Jetson 도메인 설계 문서

> 상태: Draft · 관련 이슈: S15P11E202-461 · 범위: Jetson target domain contract · 비범위: 구현 상세, 테스트 계획, 배포 계획

이 문서 묶음은 카메라와 tracker의 불완전한 관측을 Jetson이 어떤 시간적 도메인 사실로 해석하고, 그 사실을 Backend가 사용할 수 있는 전이로 어떻게 표현할지를 정의한다.

현재 구현을 그대로 설명하는 문서가 아니라, 이후 Jetson 도메인 구현과 Backend 계약이 따라야 할 목표 설계다. 각 문서에서 확인되는 구현 차이는 이 계약을 바꾸는 근거가 아니라 별도로 해소해야 할 차이로 본다.

## 핵심 원칙

1. Jetson은 단일 frame의 탐지 결과가 아니라 시간에 걸쳐 확인된 도메인 사실을 만든다.
2. domain state, observation state, delivery state를 서로 독립적으로 관리한다.
3. 관측 소실은 차량·구역 방문·주차·사건의 종료가 아니다.
4. 차량 이동은 사건 해소의 증거일 수 있지만, 사건 해소 그 자체는 아니다.
5. 한 scope가 다른 scope의 입력이라고 해서 lifecycle 종료가 자동 전파되지는 않는다.
6. 도메인 전이와 외부 전달 상태는 분리하되, 공개 전이와 outbox 기록은 함께 보존한다.
7. Jetson의 현장 판정과 Backend의 업무 처리·관리자 판단을 구분한다.

## 문서 구성

| 순서 | 문서 | 답하는 질문 |
|---|---|---|
| 1 | [Jetson 도메인 목적 및 출력 계약](./01-domain-purpose-and-output-contract.md) | Jetson은 왜 존재하며 무엇을 외부 사실로 만드는가? |
| 2 | [Jetson Scope 수명주기 계약](./02-scope-lifecycle-contract.md) | 각 scope는 언제 생성·활성·종료되는가? |
| 3 | [Jetson Scope 전파 및 종료 계약](./03-scope-propagation-contract.md) | 한 scope의 변화는 다른 scope에 어떤 영향을 미치는가? |
| 4 | [Jetson 상태 보존 및 Retention 계약](./04-durable-state-and-retention-contract.md) | 확정한 상태를 어떻게 보존하고 언제 축약·정리하는가? |
| 5 | [Jetson–Backend 상태 Reconciliation 계약](./05-backend-reconciliation-contract.md) | Jetson과 Backend 상태가 다를 때 누구를 기준으로 어떻게 합의하는가? |

문서는 위 순서로 읽는 것을 권장한다. 앞 문서가 정의한 목적·용어·상태 의미를 뒤 문서가 반복해서 재정의하지 않는다.

## 관련 계약

현재 시스템에서 이미 합의된 식별자의 의미·생성 책임·전달 경로는 [식별자 수명 및 매핑 계약](../identifier-contract.md)을 따른다. 이 목표 설계가 새로 도입하는 context binding·blocking relation·evidence·publication·reconciliation 식별자는 [Scope 수명주기 계약의 목표 식별자 확장](./02-scope-lifecycle-contract.md#목표-식별자-확장)에서 구분한다. 문서가 `Accepted`가 될 때 기존 식별자 계약도 함께 갱신해야 한다.

## 문서 경계

이 문서 묶음은 다음을 다룬다.

- Jetson이 확정하는 도메인 사실과 외부 출력
- scope별 lifecycle과 관측 불확실성
- scope 사이의 재평가·종료 전파
- 장기 실행과 재시작을 위한 논리적 상태 보존
- terminal 상태의 retention과 tombstone
- Jetson과 Backend 사이의 권한·revision·reconciliation

다음 내용은 포함하지 않는다.

- 저장소 제품이나 DB schema 선택
- repository·service의 구체적인 인터페이스
- 클래스별 변경 목록과 구현 순서
- 단위·통합 테스트 계획
- 배포·migration·성능 튜닝 절차

## 문서 상태

각 문서는 다음 상태 중 하나를 사용한다.

| 상태 | 의미 |
|---|---|
| `Draft` | 팀 검토와 외부 계약 합의가 필요한 초안 |
| `Proposed` | 도메인 설계 검토를 마치고 채택을 제안한 상태 |
| `Accepted` | Jetson·Backend 관련 팀이 기준 계약으로 합의한 상태 |

현재 문서 묶음은 `Draft`다. 문서 안에서 기간·임계값·API 명칭처럼 외부 합의가 필요한 값은 원칙과 구분하여 표시한다.
