# 주차바로 입주민 앱

Expo와 React Native로 개발한 주차바로 입주민용 애플리케이션입니다. 이중 주차, 위반 주차 등으로 발생하는 이동 요청을 앱에서 주고받고, 우리 세대 차량과 단지 주차 현황을 관리합니다.

## 실행 방법

PowerShell에서 프로젝트 폴더로 이동한 후 실행합니다.

```powershell
cd frontend\baro-app
npm.cmd install
npm.cmd start
```

Expo 개발 서버가 실행되면 다음 키를 사용할 수 있습니다.

- `w`: 웹 브라우저에서 실행
- `a`: Android 에뮬레이터에서 실행
- 휴대폰: Expo Go로 터미널의 QR 코드 스캔

라우트나 파일을 이동한 뒤 화면이 갱신되지 않으면 캐시를 비우고 다시 실행합니다.

```powershell
npm.cmd start -- --clear
```

## 코드 검사

TypeScript 오류를 확인합니다.

```powershell
npm.cmd run typecheck
```

정상이라면 오류 없이 명령이 종료됩니다.

## 폴더 역할

```text
src/
├─ app/             Expo Router 라우트
├─ features/        auth, home, parking, vehicle 등 기능별 코드
├─ components/ui/   여러 기능이 공유하는 UI
├─ providers/       앱 전체 Provider
├─ services/        공통 API 클라이언트와 저장소
├─ hooks/           공통 React 훅
├─ styles/          디자인 토큰
└─ types/           전역 타입 선언
```

기능 전용 `api`, `components`, `hooks`, `screens`, `types`, `utils`는 해당 `features/<기능>` 안에 둡니다.

## 기능 및 화면

아래 화면들은 웹 프리뷰(`npm run web`)에서 캡처한 실제 화면입니다.

### 1. 온보딩 / 인증

비로그인 상태에서 접근할 수 있는 화면입니다.

| 시작 화면 | 로그인 (기본) | 로그인 (오류) |
| --- | --- | --- |
| ![시작 화면](docs/screenshots/00-welcome.png) | ![로그인 기본](docs/screenshots/01-login-empty.png) | ![로그인 오류](docs/screenshots/01-login-error.png) |

회원가입은 계정 → 세대 → 확인 → 완료 4단계로 진행합니다.

| 1단계: 계정 입력 | 2단계: 세대 입력 |
| --- | --- |
| ![회원가입 1단계](docs/screenshots/02-signup-step1-filled.png) | ![회원가입 2단계](docs/screenshots/03-signup-step2-household.png) |

### 2. 홈

로그인 후 첫 화면입니다. 현재 주차 중인 내 차량, 빠른 메뉴(이동 요청/내 차량/방문 등록/위반 이력), 단지 주차 현황 미리보기를 보여줍니다.

![홈 화면](docs/screenshots/04-home.png)

### 3. 차량 관리

세대 차량과 방문 차량을 등록하고 관리합니다.

| 차량 목록 | 세대 차량 등록 | 방문 차량 등록 | 차량 삭제 확인 |
| --- | --- | --- | --- |
| ![차량 목록](docs/screenshots/05-vehicles-list.png) | ![세대 차량 등록](docs/screenshots/06-register-car-household.png) | ![방문 차량 등록](docs/screenshots/25-register-car-visitor.png) | ![차량 삭제 확인](docs/screenshots/26-vehicle-delete-confirm.png) |

### 4. 주차 현황

지하 1~3층 주차 구역을 층별 탭으로 전환해 확인합니다.

| B1 | B2 | B3 |
| --- | --- | --- |
| ![주차 현황 B1](docs/screenshots/07-parking-b1.png) | ![주차 현황 B2](docs/screenshots/23-parking-b2.png) | ![주차 현황 B3](docs/screenshots/24-parking-b3.png) |

### 5. 이동 요청

다른 세대 차량에 이동을 요청하고, 요청 상태를 실시간으로 확인합니다.

**작성 / 목록**

| 요청 작성 | 구역 선택 | 요청 목록 (보낸 요청) | 요청 목록 (받은 요청) |
| --- | --- | --- | --- |
| ![이동 요청 작성](docs/screenshots/15-request-compose.png) | ![구역 선택 모달](docs/screenshots/28-request-compose-zone-picker.png) | ![보낸 요청 목록](docs/screenshots/08-requests-sent.png) | ![받은 요청 목록](docs/screenshots/22-requests-received.png) |

**요청 상세 — 상태별**

요청 상태(대기/초과/이관/완료)와 보는 사람(요청자/받는 사람)에 따라 다른 화면을 보여줍니다.

| 상태 | 받는 사람(recipient) 화면 |
| --- | --- |
| 약속 시간 경과(미이동 확인) | ![미이동 확인](docs/screenshots/16-request-detail-overdue.png) |
| AI 자동 감지 위반(장애인 구역 등) | ![AI 자동 이관](docs/screenshots/17-request-detail-auto-escalation.png) |
| 관리사무소 처리 중(수동 이관) | ![관리사무소 이관](docs/screenshots/18-request-detail-admin-escalation.png) |
| 완료 | ![완료(받는 사람)](docs/screenshots/19-request-detail-completed-recipient.png) |

| 상태 | 요청자(requester) 화면 |
| --- | --- |
| 재알림 발송(관리사무소 이관 대기) | ![재알림(보낸 사람)](docs/screenshots/20-request-detail-reminder-requester.png) |
| 완료 | ![완료(보낸 사람)](docs/screenshots/21-request-detail-completed-requester.png) |

**전송 직후 / 응답 직후**

| 요청 전송 완료 | 응답 전달 완료 |
| --- | --- |
| ![이동 요청 전송 완료](docs/screenshots/33-request-sent.png) | ![응답 전달 완료](docs/screenshots/34-response-complete.png) |

**요청 내역**

보낸 요청과 받은 요청을 날짜순으로 모아 보는 화면입니다.

![요청 내역](docs/screenshots/14-request-history.png)

### 6. 알림

| 알림 목록 | 알림 설정 | 방해 금지 시간 설정 |
| --- | --- | --- |
| ![알림 목록](docs/screenshots/09-notifications.png) | ![알림 설정](docs/screenshots/10-notification-settings.png) | ![방해 금지 시간 모달](docs/screenshots/27-notification-settings-quiet-hours-modal.png) |

### 7. 내 정보

| 마이페이지 | 내 정보 수정 | 위반 이력 |
| --- | --- | --- |
| ![마이페이지](docs/screenshots/11-my-page.png) | ![내 정보 수정](docs/screenshots/12-profile-edit.png) | ![위반 이력](docs/screenshots/13-violation-history.png) |

### 8. 다른 계정으로 본 화면

같은 화면이라도 로그인한 세대에 따라 데이터가 다르게 보입니다. (`test2` 계정 예시)

| 홈 | 차량 목록 | 요청 목록 | 마이페이지 |
| --- | --- | --- | --- |
| ![test2 홈](docs/screenshots/29-test2-home.png) | ![test2 차량 목록](docs/screenshots/30-test2-vehicles.png) | ![test2 요청 목록](docs/screenshots/31-test2-requests.png) | ![test2 마이페이지](docs/screenshots/32-test2-my-page.png) |
