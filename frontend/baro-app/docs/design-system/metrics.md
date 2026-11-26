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
