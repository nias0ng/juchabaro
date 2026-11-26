# 용도 기반 색상 토큰 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 색상 의미 토큰을 `요소.톤.강조` 규칙으로 재정의하고, 이동 요청 기능과 그 화면이 쓰는 공용 컴포넌트 7개를 새 토큰으로 옮겨 다크 모드가 동작하게 하며, 린트와 대비 검사로 재발을 막는다.

**Architecture:** `src/styles/color-tokens.ts`에 라이트/다크 토큰 객체를 두고, `*.styles.ts`는 `createStyles(t)` 함수를 내보낸다. 컴포넌트는 `useThemedStyles(createStyles)`로 현재 모드의 스타일을 받는다. 기존 `Palette` / `Colors` / `useTheme()`은 그대로 둔다.

**Tech Stack:** Expo SDK 54, React Native 0.81, TypeScript 5.9, ESLint 9 (`eslint-config-expo`), Node 24 내장 테스트 러너(`node --test`)와 TypeScript 직접 실행.

**Spec:** `docs/superpowers/specs/2026-11-26-usage-based-color-tokens-design.md`

모든 경로는 `frontend/baro-app` 기준이다.

## Global Constraints

- 새 의존성을 추가하지 않는다 (`package.json`의 `dependencies` / `devDependencies` 변경 금지. `scripts`만 추가).
- `Palette`, `Colors`, `ThemeColor`, `Gradients`, `useTheme()`의 기존 키와 값은 지우거나 바꾸지 않는다. `Palette`에는 단계 추가만 한다.
- 새 의미 토큰은 모두 `Palette` 단계를 가리킨다. 색상 값 문자열은 `src/styles/colors.ts`(팔레트)와 `overlay.*` 정의에만 적는다.
- 글자·아이콘 토큰은 쓰이는 배경 위에서 WCAG AA: 본문 4.5:1, 큰 글자·아이콘·테두리 3:1. 라이트와 다크 모두.
- 라이트 모드에서 색이 달라지는 곳은 Task 2의 매핑 표에서 사용자가 승인한 행뿐이다.
- 범위 밖 파일의 색 관련 코드는 바꾸지 않는다: `features/move-request`와 공용 컴포넌트 7개(`screen-header`, `segmented-control`, `gradient-screen-background`, `info-row-card`, `form-section-label`, `async-state-view`, `bottom-nav-bar`)만 옮긴다. `features/parking`은 건드리지 않는다.
- `Jenkinsfile`, `Jenkinsfile.cd`는 건드리지 않는다.
- 파일명 `kebab-case`, 공통 훅·유틸은 named export, 기능 밖 import는 `@/` 별칭 (`AGENTS.md`).
- 커밋 메시지는 `refactor(fe): ...` / `chore(fe): ...` / `docs(fe): ...` 형식, 한국어. push와 MR 생성은 하지 않는다.
- 각 Task 끝에서 `npm run typecheck`가 통과해야 한다.

## Review Focus

1. **다크 모드에서 공용 컴포넌트를 쓰는 다른 기능 화면** — 헤더 제목이 흰색으로 바뀌었는데 화면 배경이 라이트로 고정된 곳이 없어야 한다. (Task 6에서 사용처 목록과 확인)
2. **앱 실행 중 기기 테마 전환** — 화면을 다시 열지 않아도 스타일이 새 모드로 바뀌어야 한다. (Task 4 테스트)
3. **배포 빌드에서 미리보기 경로 접근** — `/dev/design-system`으로 들어와도 내용이 보이지 않고 홈으로 간다. (Task 5)
4. **웹 첫 렌더** — hydration 전에는 라이트, 후에 기기 테마. 기존 `use-color-scheme.web.ts` 동작과 같아야 한다. (Task 4)
5. **톤이 없는 타임라인 단계** — `tone`이 없는 단계는 지금과 같은 기본 색(초록 점, 진한 글자)으로 보여야 한다. (Task 7 테스트)

---

### Task 1: 기준선 측정과 실행 환경

**Files:**
- Create: `scripts/register-ts.mjs`, `scripts/count-color-usage.mjs`, `docs/design-system/metrics.md`
- Modify: `package.json` (`scripts`만)

**Interfaces:**
- Produces: `npm run count:colors [-- <경로>]` — `theme.*` / `Palette.*` / 색상 값 문자열의 출현 횟수와 줄 수를 `src/styles` 제외하고 출력. `npm run test:unit` — `node --import ./scripts/register-ts.mjs --test "scripts/**/*.test.ts" "src/**/*.test.ts"`.

- [ ] **Step 1:** `master`에서 브랜치 `refactor/fe/usage-based-color-tokens`를 만든다. `npm ci` 실행.
- [ ] **Step 2:** `npm run typecheck`, `npm run lint` 결과(오류·경고 개수)를 `docs/design-system/metrics.md`의 "작업 전" 절에 적는다.
- [ ] **Step 3:** `npx eslint --print-config src/app/_layout.tsx`로 `no-console` 규칙이 켜져 있는지 확인해 어느 설정 파일이 적용되는지 `metrics.md`에 적는다.
- [ ] **Step 4:** `scripts/register-ts.mjs` 작성. `node:module`의 `registerHooks`로 resolve 훅을 등록한다: `@/`로 시작하면 `src/`로 바꾸고, 확장자 없는 상대 경로는 `.ts` → `.tsx` → `/index.ts` 순으로 존재하는 파일을 고른다. 확인: `node --import ./scripts/register-ts.mjs -e "import('./src/styles/colors.ts').then(m=>console.log(m.Palette.violet600))"` → `#5144d3`.
- [ ] **Step 5:** `scripts/count-color-usage.mjs` 작성. 색상 값 패턴은 따옴표·백틱 안의 `#` + 3/4/6/8자리 hex와 `rgb(`/`rgba(`/`hsl(`/`hsla(`. 주석 줄은 제외. 출력은 종류별 `출현 횟수 / 줄 수 / 파일 수`.
- [ ] **Step 6:** `npm run count:colors`와 `npm run count:colors -- src/features/move-request` 결과를 `metrics.md` "작업 전"에 명령과 함께 적는다. 기대: `Palette` 463 / move-request 124, `theme.*` 26 / 3.
- [ ] **Step 7:** Commit `chore(fe): 색상 사용 측정 스크립트와 기준선 기록`

### Task 2: 매핑 표 작성과 사용자 검토 (정지 지점)

**Files:**
- Create: `docs/design-system/color-mapping.md`

**Interfaces:**
- Produces: 승인된 매핑 표. 이후 모든 Task의 "어떤 값을 어떤 토큰으로"는 이 표를 따른다.

- [ ] **Step 1:** 범위(이동 요청 + 공용 컴포넌트 7개)의 모든 색 참조를 모은다. 각 행: `지금 값(또는 Palette 키)` / `쓰인 CSS 속성과 횟수` / `옮길 토큰` / `라이트 새 값` / `다크 값` / `값 변화 여부` / `놓이는 배경 위 대비`.
- [ ] **Step 2:** 스펙의 "토큰 초안"과 "값을 정하는 기준" 1~5를 적용해 표를 채운다. 어느 톤에도 맞지 않는 색(예: 완료 배지의 파랑, 응답 배지의 청록)은 `info` / `success` 중 의미가 맞는 쪽에 넣고 근거를 한 줄 적는다.
- [ ] **Step 3:** 라이트 값이 달라지는 행만 따로 모아 "확인 필요" 절로 올린다. 행마다 옛 색·새 색 견본(`<span style="background:...">`)과 달라지는 이유(합치기 / AA 조정)를 적는다.
- [ ] **Step 4:** **멈추고 사용자에게 `color-mapping.md`를 보여준다.** 행마다 승인 / 지금 값 유지를 받는다. "유지"인 AA 미달 행은 표에 `예외`로 표시하고 사유를 적는다.
- [ ] **Step 5:** Commit `docs(fe): 색상 매핑 표 추가`

### Task 3: 토큰 정의와 대비 검사

**Files:**
- Create: `src/styles/color-tokens.ts`, `src/styles/contrast.ts`, `src/styles/contrast.test.ts`, `scripts/check-contrast.ts`
- Modify: `src/styles/colors.ts` (팔레트 단계 추가만), `src/styles/index.ts`, `package.json` (`scripts`)

**Interfaces:**
- Consumes: Task 2의 승인된 표.
- Produces:
  - `export type ColorTokens` — 키: `text { strong, weak, weaker, inverse, brand, error, success, info, warning? }`, `icon { strong, weak, brand, error, inverse }`, `stroke { weak, strong, brand, error }`, `fill { brand: { strong, weak }, error: { strong, weak }, success: { strong, weak }, info: { weak }, neutral: { strong, weak } }`, `background { neutral, weak, raised }`, `gradient { brand, success, error, warning }` (각각 `readonly [string, string, ...string[]]`), `overlay { scrim, onPhoto }`, `shadow`. 매핑 표에서 쓰이지 않은 키는 만들지 않고, 표에만 있는 키는 추가한다.
  - `export const Tokens: { light: ColorTokens; dark: ColorTokens }`
  - `contrastRatio(fg: string, bg: string): number` (6자리 hex 입력)
  - `type ContrastPair = { fg: (t: ColorTokens) => string; bg: (t: ColorTokens) => string; min: 4.5 | 3; name: string }`
  - `CONTRAST_PAIRS: ContrastPair[]`, `KNOWN_EXCEPTIONS: { name: string; mode: 'light' | 'dark'; reason: string }[]`
  - `checkContrast(tokens: ColorTokens, mode: 'light' | 'dark'): { name: string; ratio: number; min: number; excepted: boolean }[]` — 기준 미달인 쌍만 반환.
  - `npm run check:contrast`

- [ ] **Step 1: 실패하는 테스트 작성** (`src/styles/contrast.test.ts`, `node:test` + `node:assert/strict`)

```ts
test('contrastRatio는 WCAG 공식 값을 낸다', () => {
  assert.equal(contrastRatio('#000000', '#ffffff').toFixed(2), '21.00');
  assert.equal(contrastRatio('#9599a7', '#ffffff').toFixed(2), '2.84');
  assert.equal(contrastRatio('#60646c', '#ffffff').toFixed(2), '5.94');
});
test('라이트 토큰은 예외를 빼면 AA 미달이 없다', () => {
  assert.deepEqual(checkContrast(Tokens.light, 'light').filter((f) => !f.excepted), []);
});
test('다크 토큰은 예외를 빼면 AA 미달이 없다', () => {
  assert.deepEqual(checkContrast(Tokens.dark, 'dark').filter((f) => !f.excepted), []);
});
test('라이트와 다크는 같은 키를 갖는다', () => {
  assert.deepEqual(keyPaths(Tokens.light), keyPaths(Tokens.dark));
});
test('옛 보조 글자색은 검사에 걸린다', () => {
  const old = { ...Tokens.light, text: { ...Tokens.light.text, weaker: '#9599a7' } };
  assert.ok(checkContrast(old, 'light').some((f) => f.name.startsWith('text.weaker')));
});
```

- [ ] **Step 2:** `npm run test:unit` → 모듈 없음으로 FAIL 확인.
- [ ] **Step 3:** `colors.ts`의 `Palette`에 매핑 표가 요구하는 단계를 추가한다(라이트 신규 값, 다크용 값). 기존 `Colors.dark`에 직접 적힌 값은 그대로 둔다.
- [ ] **Step 4:** `color-tokens.ts` 작성. `satisfies ColorTokens`로 두 벌의 모양을 강제한다. `index.ts`에 export 추가.
- [ ] **Step 5:** `contrast.ts` 작성. `CONTRAST_PAIRS`는 매핑 표의 "놓이는 배경" 열에서 만든다: 모든 `text.*` × `background.neutral` / `background.weak` / `background.raised`, 배지의 `text.<톤>` × `fill.<톤>.weak`, `text.inverse` × `fill.*.strong`, `icon.*` × 놓이는 배경(기준 3), `stroke.strong` × `background.*`(기준 3).
- [ ] **Step 6:** `npm run test:unit` → PASS. 미달이 있으면 팔레트 값을 조정하되 라이트 값이 Task 2 승인과 달라지면 사용자에게 다시 확인한다.
- [ ] **Step 7:** `scripts/check-contrast.ts` — 라이트/다크 결과 표를 출력하고 예외 아닌 미달이 있으면 `process.exit(1)`. `package.json`에 `"check:contrast": "node --import ./scripts/register-ts.mjs scripts/check-contrast.ts"`.
- [ ] **Step 8:** 옛 값(`#9599a7`, `Palette.gray500`, `Palette.orange600`, `Palette.blue600` on `sky100`)으로 같은 검사를 돌린 출력을 `docs/design-system/metrics.md` "작업 전 대비"에 붙인다.
- [ ] **Step 9:** `npm run typecheck` 통과 확인. Commit `refactor(fe): 용도 기반 색상 토큰과 대비 검사 추가`

### Task 4: 토큰 훅

**Files:**
- Create: `src/hooks/use-color-tokens.ts`, `src/hooks/use-themed-styles.ts`, `src/hooks/themed-styles-cache.ts`, `src/hooks/themed-styles-cache.test.ts`

**Interfaces:**
- Consumes: `Tokens`, `ColorTokens`.
- Produces:
  - `useColorTokens(): ColorTokens` — `@/hooks/use-color-scheme`의 결과가 `'dark'`면 `Tokens.dark`, 아니면 `Tokens.light`.
  - `getThemedStyles<T>(create: (t: ColorTokens) => T, tokens: ColorTokens): T` — `(create, tokens)` 쌍마다 한 번만 `create`를 부른다 (`WeakMap<create, WeakMap<tokens, T>>`). React·RN을 import하지 않는 순수 함수.
  - `useThemedStyles<T>(create: (t: ColorTokens) => T): T` — `getThemedStyles(create, useColorTokens())`.
  - 규약: `createStyles`는 모듈 최상위에 정의한다(컴포넌트 안에서 만들면 캐시가 듣지 않는다).

- [ ] **Step 1: 실패하는 테스트 작성** (`themed-styles-cache.test.ts`)

```ts
test('같은 create와 같은 토큰이면 한 번만 만든다', () => {
  let calls = 0;
  const create = (t: ColorTokens) => { calls += 1; return { c: t.text.strong }; };
  const a = getThemedStyles(create, Tokens.light);
  const b = getThemedStyles(create, Tokens.light);
  assert.equal(a, b);
  assert.equal(calls, 1);
});
test('토큰이 바뀌면 그 모드의 값을 돌려준다', () => {
  const create = (t: ColorTokens) => ({ c: t.text.strong });
  assert.equal(getThemedStyles(create, Tokens.light).c, Tokens.light.text.strong);
  assert.equal(getThemedStyles(create, Tokens.dark).c, Tokens.dark.text.strong);
});
```

- [ ] **Step 2:** `npm run test:unit` → FAIL 확인.
- [ ] **Step 3:** 세 파일 구현.
- [ ] **Step 4:** `npm run test:unit` PASS, `npm run typecheck` 통과.
- [ ] **Step 5:** Commit `refactor(fe): 테마 토큰을 받는 스타일 훅 추가`

### Task 5: 미리보기 화면과 "작업 전" 화면 저장

**Files:**
- Create: `src/app/dev/design-system.tsx`, `src/features/design-system/screens/design-system-screen.tsx`, `src/features/design-system/screens/design-system-screen.styles.ts`, `src/features/design-system/fixtures/move-request-fixtures.ts`, `docs/design-system/screenshots/`

**Interfaces:**
- Consumes: `useThemedStyles`, `useColorTokens`, `Tokens`.
- Produces: 경로 `/dev/design-system`. 위에서부터 (1) 토큰 견본: 그룹별로 이름·값·색 칩, (2) 공용 컴포넌트 7개, (3) 이동 요청 컴포넌트: `RequestTimelineCard`(기본 / 재알림 / 기한 초과 / 대기 단계 포함), `RequestStatusBadge` 전 상태, `RequestProgressCard`, `RequestListCard`, `RequestStatCardRow`.

- [ ] **Step 1:** 라우트 파일은 화면을 다시 내보내기만 한다. 화면 컴포넌트 첫 줄에서 `if (!__DEV__) return <Redirect href="/" />;`.
- [ ] **Step 2:** 고정 데이터는 각 컴포넌트의 props 타입에 맞춰 `move-request-fixtures.ts`에 둔다. API 호출과 훅 의존 없이 props만으로 그려지는 컴포넌트만 싣는다.
- [ ] **Step 3:** 이 화면 자체의 스타일은 처음부터 `createStyles(t)`로 작성한다.
- [ ] **Step 4:** 개발 서버(웹)로 `/dev/design-system`을 연다. 모바일 폭(375)에서 라이트/다크 각각 전체 화면을 `docs/design-system/screenshots/before-light.png`, `before-dark.png`로 저장한다. 이 시점의 다크 화면은 컴포넌트가 라이트로 남아 있는 것이 정상이다.
- [ ] **Step 5:** `npx expo export --platform web` 결과물에서 `/dev/design-system`으로 들어가면 홈으로 이동하는지 확인한다. 확인 못 하면 사유를 `metrics.md`에 적는다.
- [ ] **Step 6:** `npm run typecheck` 통과. Commit `chore(fe): 개발 전용 디자인 시스템 미리보기 화면 추가`

### Task 6: 공용 컴포넌트 7개 이전

**Files:**
- Modify: `src/components/ui/{screen-header,segmented-control,info-row-card,form-section-label,async-state-view,bottom-nav-bar}.styles.ts`와 각 `.tsx`, `src/components/ui/gradient-screen-background.tsx`, `src/components/ui/bottom-nav-bar-icons.ts`(색 상수가 있으면)

**Interfaces:**
- Consumes: `useThemedStyles`, `useColorTokens`, 매핑 표.
- Produces: 각 `.styles.ts`는 `export const createStyles = (t: ColorTokens) => StyleSheet.create({...})`. 컴포넌트의 props는 바꾸지 않는다. `GradientScreenBackground`는 기본 그라데이션을 `t.gradient.brand`에서 가져온다.

- [ ] **Step 1:** 일곱 컴포넌트의 사용처를 `grep`으로 뽑아 `docs/design-system/metrics.md`에 "공용 컴포넌트 사용 화면" 목록으로 적는다.
- [ ] **Step 2:** 컴포넌트를 하나씩 옮긴다. 색 속성만 토큰으로 바꾸고 다른 속성은 건드리지 않는다. SVG `color`/`stroke` prop과 `INACTIVE_COLOR` 같은 상수도 토큰에서 가져온다.
- [ ] **Step 3:** `npm run count:colors -- src/components/ui`에서 일곱 컴포넌트 파일의 `Palette`와 색상 값이 0인지 확인한다.
- [ ] **Step 4:** 미리보기 화면에서 라이트가 `before-light.png`와 같은지(승인된 변경 제외), 다크가 어두운 테마로 읽히는지 확인한다.
- [ ] **Step 5:** Step 1 목록의 화면 중 이동 요청이 아닌 것들을 다크 모드로 연다. 글자가 배경과 겹쳐 안 보이는 곳이 있으면, 그 화면을 고치지 말고 해당 공용 컴포넌트에서 문제 되는 속성을 사용자에게 보고하고 멈춘다. 서버가 없어 열 수 없는 화면은 목록에 "확인 못 함"으로 적는다.
- [ ] **Step 6:** `npm run typecheck`. Commit `refactor(fe): 공용 컴포넌트 색상을 용도 기반 토큰으로 이전`

### Task 7: 타임라인 유틸을 톤 기반으로

**Files:**
- Modify: `src/features/move-request/utils/move-request.ts`, `src/features/move-request/components/request-timeline-card.tsx`, `request-timeline-card.styles.ts`
- Create: `src/features/move-request/utils/move-request-timeline.test.ts`

**Interfaces:**
- Produces:
  - `export type TimelineTone = 'brand' | 'warning' | 'error';`
  - `RequestTimelineStep = { label: string; detail: string; tone?: TimelineTone; isFinal?: boolean }` — `dotColor`, `labelColor` 제거.
  - 옛 색 → 톤: `dotColor '#7a6ff0'` → `brand`; `('#ff8f6b', '#d4553a')` → `warning`; `('#e5493d', '#c8492e')`와 `('#d4553a', '#c8492e')` → `error`. 매핑 표에서 사용자가 둘을 구분하기로 했으면 그 결정을 따른다.
  - 카드의 색 결정: `tone`이 있으면 점은 `fill.<톤>.strong`, 글자는 `text.<톤>`(brand는 `text.brand`). 없으면 점 `fill.success.strong`, 글자 `text.strong`. `isFinal`이고 톤이 없으면 brand와 같다.

- [ ] **Step 1: 실패하는 테스트 작성** — 타임라인을 만드는 export 함수들에 대해 (입력은 `MoveRequestDetail` 최소 고정값)

```ts
test('타임라인 단계에 색상 값이 들어가지 않는다', () => {
  for (const step of allTimelines.flat()) {
    assert.equal('dotColor' in step, false);
    assert.equal('labelColor' in step, false);
    assert.ok(step.tone === undefined || ['brand', 'warning', 'error'].includes(step.tone));
  }
});
test('기한 초과 단계는 error 톤이다', () => { /* 해당 단계의 tone === 'error' */ });
test('톤이 없는 단계는 tone이 undefined다', () => { /* '요청 접수' 단계 */ });
```

- [ ] **Step 2:** `npm run test:unit` → FAIL.
- [ ] **Step 3:** 유틸과 카드, 카드 스타일을 바꾼다.
- [ ] **Step 4:** `npm run test:unit` PASS, `npm run typecheck`, 미리보기에서 타임라인 네 가지 모양을 라이트/다크로 확인.
- [ ] **Step 5:** Commit `refactor(fe): 타임라인 단계가 색상 값 대신 톤을 반환하도록 변경`

### Task 8: 이동 요청 — 목록·이력·공통 조각

**Files:**
- Modify: `src/features/move-request/components/{history,requests-list}/*`, `request-check-badge.*`, `request-stat-card-row.*`, `request-header-right.*`, `request-detail-body.*`, `screens/{requests-screen,request-history-screen}.*`

**Interfaces:**
- Consumes: Task 3·4, 매핑 표. 형태는 Task 6과 같다(`createStyles` + `useThemedStyles`).

- [ ] **Step 1:** 색을 쓰는 `.styles.ts`를 `createStyles(t)`로 바꾸고 컴포넌트에서 훅으로 받는다. 색을 쓰지 않는 스타일 파일은 그대로 둔다.
- [ ] **Step 2:** `.tsx` 안의 그라데이션 상수와 색 prop을 토큰으로 바꾼다.
- [ ] **Step 3:** `npm run count:colors -- <위 경로들>` → `Palette` 0, 색상 값 0.
- [ ] **Step 4:** `npm run typecheck`, 미리보기 라이트/다크 확인. Commit `refactor(fe): 이동 요청 목록·이력 색상을 토큰으로 이전`

### Task 9: 이동 요청 — 작성·전송

**Files:**
- Modify: `src/features/move-request/components/request-compose/*`, `screens/{request-compose-screen,request-sent-screen}.*`

- [ ] **Step 1:** Task 8과 같은 방식. `rgba()` 값은 `t.overlay.*`, `t.shadow`로 옮긴다. `placeholderTextColor`도 토큰(`t.text.weaker`)에서 가져온다.
- [ ] **Step 2:** 구역 선택 모달 안의 `ParkingSpotMap` / `ParkingLegend`는 건드리지 않는다. 모달 틀(막, 면, 제목)만 옮긴다.
- [ ] **Step 3:** `npm run count:colors -- src/features/move-request/components/request-compose` → 0 / 0. `npm run typecheck`. Commit `refactor(fe): 이동 요청 작성·전송 화면 색상을 토큰으로 이전`

### Task 10: 이동 요청 — 상세와 상태별 구역

**Files:**
- Modify: `src/features/move-request/components/{request-detail,request-waiting,request-overdue,request-reminder,request-completed}/*`, `screens/request-detail-screen.*`

- [ ] **Step 1:** Task 8과 같은 방식. `request-detail-screen.tsx`의 `WAITING_` / `COMPLETED_` / `OVERDUE_` / `REMINDER_GRADIENT`는 `t.gradient.brand` / `success` 또는 `brand` / `error` / `warning`으로 매핑 표에 따라 바꾼다. SVG 링의 `stroke`도 토큰.
- [ ] **Step 2:** `npm run count:colors -- src/features/move-request` → `Palette` 0, 색상 값 0.
- [ ] **Step 3:** `npm run typecheck`, `npm run test:unit`, `npm run check:contrast`.
- [ ] **Step 4:** 서버 접속이 되면 실제 화면 5개를 라이트/다크로 연다. 안 되면 `metrics.md`에 "실제 화면 확인 못 함: 서버 접속 불가"로 적는다.
- [ ] **Step 5:** Commit `refactor(fe): 이동 요청 상세 화면 색상을 토큰으로 이전`

### Task 11: 린트 규칙

**Files:**
- Modify: Task 1 Step 3에서 적용 중으로 확인된 ESLint 설정 파일
- Delete: 적용되지 않는 쪽 설정 파일 (그쪽에만 있는 규칙을 먼저 옮긴 뒤)

**Interfaces:**
- Produces: 규칙 두 개, 범위 세 단계.
  - `no-restricted-syntax`: 선택자 `Literal[value=/^(#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|(rgb|hsl)a?\(.*\))$/]`와 같은 패턴의 `TemplateElement`. 메시지: `색상 값 대신 src/styles의 토큰을 사용하세요 (useThemedStyles).`
  - `no-restricted-imports`: `{ paths: [{ name: '@/styles', importNames: ['Palette'], message: 'Palette 대신 용도 기반 토큰(ColorTokens)을 사용하세요.' }] }`
  - `src/styles/**`, `scripts/**`, `**/*.test.ts`: 규칙 없음. `src/features/move-request/**`, `src/features/design-system/**`, 공용 컴포넌트 7개 파일: `error`. 그 밖의 `src/**`: `warn`.

- [ ] **Step 1:** 적용되지 않는 설정 파일의 `no-console`, `@typescript-eslint/no-explicit-any` 경고와 `.expo/*` ignore를 적용되는 파일로 옮기고 그 파일을 삭제한다. `npm run lint`에 새 **오류**가 생기지 않는지 확인한다.
- [ ] **Step 2:** 규칙이 듣는지 확인: `src/features/move-request/components/request-timeline-card.styles.ts`에 임시로 `color: '#9599a7'`을 넣고 `npm run lint` → 오류. 되돌린다.
- [ ] **Step 3:** 규칙 추가 후 `npm run lint` → 오류 0. 경고 개수를 `metrics.md`에 "남은 부채"로 적는다.
- [ ] **Step 4:** `AGENTS.md` "스타일 작성" 절의 예시를 새 방식(`createStyles`, `t.text.weak`)으로 고치고, 린트가 강제한다는 한 줄을 더한다.
- [ ] **Step 5:** Commit `chore(fe): 색상 값 하드코딩과 Palette 직접 사용을 막는 린트 규칙 추가`

### Task 12: 증거 정리

**Files:**
- Create: `docs/design-system/tokens.md`, `docs/design-system/screenshots/after-{light,dark}.png`
- Modify: `docs/design-system/metrics.md`

- [ ] **Step 1:** `npm run count:colors`, `npm run count:colors -- src/features/move-request`, `npm run check:contrast` 출력을 `metrics.md` "작업 후"에 적고 전후 비교 표를 만든다.
- [ ] **Step 2:** 미리보기 화면을 Task 5와 같은 폭·방법으로 찍어 `after-light.png`, `after-dark.png`로 저장한다.
- [ ] **Step 3:** `tokens.md` 작성: 이름 규칙, 토큰 표(라이트/다크 값과 가리키는 팔레트 단계), 스타일 파일 작성법 한 예, 알려진 한계(주차 도면, 옮기지 않은 기능, 스케일 밖 간격·글자 크기, 대비 예외).
- [ ] **Step 4:** 범위 밖 변경이 없는지 확인: `git diff master --stat -- src`에서 `src/styles`, `src/hooks`, `src/app/dev`, `src/features/design-system`, `src/features/move-request`, 공용 컴포넌트 7개 외의 파일이 없어야 한다.
- [ ] **Step 5:** `npm run typecheck && npm run lint && npm run test:unit && npm run check:contrast` 모두 통과 확인.
- [ ] **Step 6:** Commit `docs(fe): 디자인 토큰 문서와 전후 측정 결과 추가`
