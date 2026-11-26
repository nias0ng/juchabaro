# 색상 토큰 이전 — 측정 기록

## 작업 전 (2026-11-26, `master` bfb7e41 기준)

### 검증 명령

| 명령 | 결과 |
|---|---|
| `npm run typecheck` | 통과 |
| `npx eslint .` | 오류 0, 경고 2 (`@typescript-eslint/no-require-imports`, 설정 파일 자체) |

### ESLint 설정 파일

`eslint.config.js`와 `eslint.config.ts`가 둘 다 있다. `npx eslint --print-config src/app/_layout.tsx` 결과에 `no-console` 규칙이 없다. 즉 **`eslint.config.js`만 적용되고 있고**, `eslint.config.ts`에 적힌 `no-console` / `@typescript-eslint/no-explicit-any` 경고와 `.expo/*` 제외는 동작하지 않는다.

### 색을 쓰는 방식별 횟수

세는 명령: `npm run count:colors` (`scripts/count-color-usage.mjs`). `src/styles`와 테스트 파일, 주석 줄은 세지 않는다.

`npm run count:colors` (src 전체, 파일 324개)

| 방식 | 출현 횟수 | 줄 수 | 파일 수 |
|---|---|---|---|
| `theme.*` (기존 의미 토큰) | 26 | 26 | 10 |
| `Palette.*` 직접 사용 | 463 | 443 | 118 |
| 색상 값 하드코딩 | 159 | 135 | 63 |

`npm run count:colors -- src/features/move-request` (파일 74개)

| 방식 | 출현 횟수 | 줄 수 | 파일 수 |
|---|---|---|---|
| `theme.*` (기존 의미 토큰) | 3 | 3 | 1 |
| `Palette.*` 직접 사용 | 130 | 124 | 34 |
| 색상 값 하드코딩 | 86 | 75 | 29 |

### 작업 전 대비 (라이트)

새 토큰 구조에 **옮기기 전 값**(`#9599a7`, `#d4553a`, `#1e8d80`, `#3f7bd6`, `#9ca3af`, `#e5484d`)을 넣고 같은 검사를 돌린 결과다. 조합 37개 중 아래가 기준 미달이다.

| 조합 | 대비 | 기준 |
|---|---|---|
| `text.weaker on background.neutral` | 2.84 | 4.5 |
| `text.weaker on background.weak` | 2.64 | 4.5 |
| `text.weaker on background.raised` | 2.84 | 4.5 |
| `text.error on background.neutral` | 4.07 | 4.5 |
| `text.error on background.weak` | 3.78 | 4.5 |
| `text.error on background.raised` | 4.07 | 4.5 |
| `text.warning on background.neutral` | 4.07 | 4.5 |
| `text.warning on background.weak` | 3.78 | 4.5 |
| `text.warning on background.raised` | 4.07 | 4.5 |
| `text.success on background.neutral` | 4.06 | 4.5 |
| `text.success on background.weak` | 3.77 | 4.5 |
| `text.success on background.raised` | 4.06 | 4.5 |
| `text.info on background.neutral` | 4.19 | 4.5 |
| `text.info on background.weak` | 3.89 | 4.5 |
| `text.info on background.raised` | 4.19 | 4.5 |
| `text.error on fill.error.weak` | 3.72 | 4.5 |
| `text.warning on fill.warning.weak` | 3.72 | 4.5 |
| `text.success on fill.success.weak` | 3.52 | 4.5 |
| `text.info on fill.info.weak` | 3.31 | 4.5 |
| `text.weaker on fill.neutral.weak` | 2.50 | 4.5 |
| `text.inverse on fill.error.strong` | 3.91 | 4.5 |
| `icon.weak on background.neutral` | 2.54 | 3 |
| `icon.weak on background.weak` | 2.36 | 3 |
| `icon.weak on background.raised` | 2.54 | 3 |

다크 모드는 작업 전에 해당 화면이 테마를 따르지 않았으므로 비교할 값이 없다.

## 작업 후 (2026-11-26, 브랜치 `refactor/fe/usage-based-color-tokens`)

### 색을 쓰는 방식별 횟수 (출현 횟수)

| 방식 | src 전체: 전 → 후 | 이동 요청: 전 → 후 |
|---|---|---|
| `theme.*` (기존 의미 토큰) | 26 → 21 | 3 → 0 |
| `Palette.*` 직접 사용 | 463 → 315 | 130 → 0 |
| 색상 값 하드코딩 | 159 → 68 | 86 → 0 |

공용 컴포넌트 7개(`screen-header`, `segmented-control`, `gradient-screen-background`, `info-row-card`, `form-section-label`, `async-state-view`, `bottom-nav-bar`)도 세 항목 모두 0이다.

### 대비 검사 (`npm run check:contrast`)

| 모드 | 조합 | 미달: 전 → 후 | 최저 대비 (후) |
|---|---|---|---|
| 라이트 | 39 | 24 → 0 | 3.09 (아이콘, 기준 3) |
| 다크 | 39 | 비교 불가 → 0 | 4.04 (아이콘, 기준 3) |

알려진 예외는 없다.

### 검증 명령

| 명령 | 결과 |
|---|---|
| `npm run typecheck` | 통과 |
| `npm run test:unit` | 18개 통과 |
| `npx eslint .` | 오류 0, 경고 151 |

경고 151개 중 146개가 새 색상 규칙(`no-restricted-syntax`, `no-restricted-imports`)이다. 아직 옮기지 않은 기능에 남은 부채이며, 기능을 옮길 때마다 줄어든다. 나머지 5개는 이번에 되살린 `no-console` 등이다.

### 화면

`scripts/capture-preview.sh <before|after>`로 미리보기 화면(`/dev/design-system`)을 폭 500px로 찍었다.

| | 라이트 | 다크 |
|---|---|---|
| 작업 전 | `screenshots/before-light.png` | `screenshots/before-dark.png` |
| 작업 후 | `screenshots/after-light.png` | `screenshots/after-dark.png` |

작업 전 다크 화면은 배경과 컴포넌트가 라이트로 남고, 새로 만든 미리보기 화면의 제목만 흰색이라 보이지 않는다. 고정 스타일이 기기 모드를 따르지 않던 상태를 그대로 보여준다.

### 확인하지 못한 것

- 실제 이동 요청 화면 5개(목록, 작성, 전송 완료, 상세, 이력)는 열어 보지 못했다. 로그인과 배포 서버가 필요하다. 미리보기 화면의 컴포넌트로만 확인했다.
- 배포 빌드에서 미리보기 경로 차단은 `expo export --platform web` 결과물의 `dev/design-system.html`에 화면 내용이 없는 것으로만 확인했다. 브라우저로 들어가 홈으로 이동하는 것까지는 보지 않았다.
- Android / iOS 기기에서는 확인하지 않았다. 웹에서만 확인했다.

### 공용 컴포넌트를 쓰는 화면

옮긴 공용 컴포넌트 7개는 아래 화면에서도 쓰인다. 이 화면들은 `withAdaptiveColors`로 감싸지 않았으므로 기기가 다크 모드여도 공용 컴포넌트가 라이트 값을 쓴다 (`resolve-color-tokens.test.ts`가 검증).

`app/resident/_layout`, `auth`(login, signup), `notification`(notifications, response-complete), `parking`(parking-floor-overview), `profile`(my-page, notification-settings, profile-edit), `vehicle`(vehicles, register-car 외 3개), `violation`(violation-history)
