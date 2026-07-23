# 주차바로 입주민 앱

Expo와 React Native로 개발하는 주차바로 입주민용 애플리케이션입니다.

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

## 현재 화면 주소

| 주소 | 파일 | 설명 |
| --- | --- | --- |
| `/` | `src/app/index.tsx` | `/resident`로 이동 |
| `/auth/login` | `src/app/auth/login.tsx` | 로그인 |
| `/auth/signup` | `src/app/auth/signup.tsx` | 회원가입 |
| `/resident` | `src/app/resident/index.tsx` | 입주민 홈 |
| `/resident/notifications` | `src/app/resident/notifications.tsx` | 알림 |
| `/resident/vehicles` | `src/app/resident/vehicles.tsx` | 차량 관리 |
| `/resident/my-page` | `src/app/resident/my-page.tsx` | 마이페이지 |

웹 개발 서버의 기본 주소는 `http://localhost:8081`입니다.

예를 들어 로그인 화면은 다음 주소에서 확인할 수 있습니다.

```text
http://localhost:8081/auth/login
```

## 라우트 확인 방법

Expo Router에서는 `src/app` 아래 파일 경로가 그대로 화면 주소가 됩니다.

```text
src/app/resident/vehicles.tsx
→ /resident/vehicles
```

실행 중인 전체 라우트는 브라우저에서 다음 주소를 열어 확인할 수 있습니다.

```text
http://localhost:8081/_sitemap
```

`Unmatched Route`가 나오면 먼저 `_sitemap`에서 원하는 주소가 생성됐는지 확인합니다.

## 코드 검사

TypeScript 오류를 확인합니다.

```powershell
npm.cmd run typecheck
```

정상이라면 오류 없이 명령이 종료됩니다.

## 폴더 역할

```text
src/
├─ app/          화면과 라우팅
├─ components/   공통 UI 컴포넌트
├─ constants/    색상과 공통 상수
└─ hooks/        공통 React 훅
```

`api`, `store`, `types`, `utils` 폴더는 실제로 필요한 기능을 구현할 때 추가합니다.
