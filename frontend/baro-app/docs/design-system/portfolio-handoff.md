# 포트폴리오 케이스 스터디 인계

작성: 2026-11-26 · 브랜치 `refactor/fe/usage-based-color-tokens` (기준 `master` bfb7e41)

이 문서는 다른 세션(다른 계정)이 이어서 **포트폴리오용 디자인 시스템 케이스 스터디**를 만들 수 있도록, 지금까지 한 일과 정한 방향을 정리한 것이다. 새 세션은 이 문서를 먼저 읽고, 아래 "읽을 파일"을 순서대로 본다.

## 목표

프론트엔드 개발자 포트폴리오에 "디자인 시스템" 꼭지를 하나 싣는다. 이 프로젝트(주차바로)에서 쓴 디자인 토큰과 디자인 시스템을 정리하고 개선한 과정을 보여준다.

참고한 글: Adham Dannaway, "My Figma design system" (`https://www.adhamdannaway.com/portfolio/figma-design-system`)

## 정한 방향

### 레퍼런스에서 가져올 것과 버릴 것

레퍼런스는 디자이너의 글이라 "시스템이 얼마나 정돈되고 예쁜가"가 중심이다. 프론트엔드 지원자가 같은 구성으로 쓰면 "토큰을 정리했다"로만 읽힌다.

- **가져온다 (형식)**
  - 결정 하나에 그림 하나를 붙이는 구성
  - 실제 화면에 토큰 이름을 화살표로 붙인 주석 그림 (레퍼런스의 프로필 메뉴 그림처럼)
  - 라이트/다크 나란히 비교
  - 색 이름 규칙을 도식으로 보여주기 (`element.tone.emphasis.state` 그림)
- **가져온다 (내용)**
  - 용도 기반 색 이름 규칙
  - 라이트/다크에서 대비를 일정하게 유지하는 원칙, WCAG AA
  - 다크 모드에서는 그림자 대신 밝은 면으로 높이를 표현
- **버린다**
  - 투명 색상 기반 팔레트, 상태 오버레이(hover/press layer)
  - 값만 나열하는 토큰 표 위주의 구성

### 이야기 흐름

핵심 메시지: **"문제를 직접 찾아서, 범위를 판단하고, 재발을 막았다"**

| 보는 사람 | 보는 것 | 포폴에 둘 것 |
|---|---|---|
| 채용담당자 | 첫 화면의 한 줄 요약, 숫자, 전후 그림 한 장 | 맨 위에 요약 한 줄 + 핵심 숫자 + 다크 모드 전후 그림 |
| 현직 개발자 | 왜 그렇게 정했는지, 코드 증거 | 원인 분석, 범위 판단 이유, 재발 방지 장치, 코드·diff 링크 |

추천 순서 (작성자 제안, 바꿔도 된다):

1. **요약**: 한 줄 + 숫자 3~4개 + 전후 그림
2. **프로젝트 중 기여**: RN 앱 토큰을 Vue 관리자 웹으로 옮기고 상태색을 확장한 일 (아래 "기여 범위" 참고)
3. **문제 발견**: 의미 토큰이 있는데도 화면 대부분이 팔레트를 직접 쓰고 있었다. 원인은 고정 스타일 파일(`StyleSheet.create`)이 테마 훅을 쓸 수 없는 구조. 결과로 다크 모드 미동작, 같은 역할의 색이 여러 값으로 흩어짐, 대비 미달
4. **이름 규칙**: `요소.톤.강조` 도식 + 토큰 표
5. **대비**: 옛 값 24개 조합 미달 → 0. 색 견본 전후 비교
6. **구조**: `createStyles(t)` + `useThemedStyles`, 화면 단위 다크 모드(`withAdaptiveColors`)를 둔 이유
7. **범위 판단**: 앱 전체(파일 118개)가 아니라 색 참조가 가장 몰린 이동 요청 기능 하나만 완전히 옮긴 이유
8. **재발 방지**: 린트 규칙, 대비 자동 검사
9. **한계와 다음 단계**: 솔직하게 (아래 "알려진 한계")

### 감점 피하기

- **기여 범위를 나눠 적는다.** 면접에서 바로 확인되는 부분이다.
- **시점을 밝힌다.** 이번 개선은 프로젝트 종료 후의 작업이다. "종료 후 회고에서 발견해 개선"이라고 쓴다. 프로젝트 중에 한 것처럼 쓰지 않는다.
- **이유 없는 토큰 표를 피한다.**
- **"전부 바꿨다"고 자랑하지 않는다.** 범위를 어떻게 끊었는지가 더 높게 평가된다.

## 기여 범위 (사실 확인용)

`git log` 기준이다. 커밋만으로는 누가 결정했는지까지 알 수 없으니, 글로 쓸 때는 본인 기억과 맞춰 확인한다.

같은 사람: "Song Gayeon" = "송가연" = "Gayeon". 팀원: chaewon = 김채원.

| 영역 | 커밋 | 내용 |
|---|---|---|
| `baro-app/src/styles` (앱 토큰 기초) | chaewon 13, 김채원 1, 본인 4 | 초기 토큰 정리(2026-07-29)는 팀원. 본인은 "주차 도면 전체 보기용 칸 배경 색상 토큰 추가" 등 |
| `admin-web/src/styles` | 본인 3 / 3 | "admin-web 공통 스타일과 레이아웃 컴포넌트 추가"(2026-08-02), "사건 상태 배지 정리"(2026-08-05) |
| `baro-app/src/components/ui` | chaewon 24, 본인 11, 김채원 2 | 본인: Figma 기반 MainIcon / BottomNavBar / BackButton, Screen 슬롯, ScreenHeader·그라데이션 통일, ToggleSwitch 정리, 공통 컴포넌트 설계 문서 |
| 이번 개선 (이 브랜치) | 본인 | 아래 전부 |

### 프로젝트 중 admin-web에서 한 일 (포폴 2절 재료)

- RN 앱의 TS 토큰(`colors.ts` 등)을 Vue의 CSS 변수(`src/styles/tokens.css`의 `--color-*`, `--spacing-*` 등)로 옮겨 두 플랫폼의 톤을 맞춤
- 관리자 대시보드용 확장 토큰 `--panel-*`을 **oklch**로 새로 정의: success / warning / info / danger와 각각의 `-soft`, `-foreground`, 사이드바 그라데이션, 카드·팝업 그림자. 라이트/다크 모두
- `StatusTag` 컴포넌트가 `tone` prop을 `--panel-*` 토큰으로 매핑
- 한계(그대로 둠): 두 프론트가 값을 손으로 복사해 맞추는 구조라 이름이 어긋난 곳이 있다 (`--space-*` vs `--spacing-*`, 폰트 Spline Sans vs Pretendard)

## 이번 개선에서 한 일

| 항목 | 내용 |
|---|---|
| 토큰 | `src/styles/color-tokens.ts`. 용도 기반, 라이트/다크 두 벌, 모두 팔레트 단계를 가리킴 |
| 대비 검사 | `src/styles/contrast.ts`, `npm run check:contrast`. 39개 조합, 라이트/다크 |
| 구조 | `createStyles(t)` + `useThemedStyles` / `useColorTokens`, 화면 단위 `withAdaptiveColors` (`src/hooks/`) |
| 적용 | 이동 요청 기능 전체(파일 74개) + 공용 컴포넌트 7개 |
| 유틸 | 타임라인 유틸이 색 값 대신 톤(`'error'` 등)을 반환 |
| 린트 | `eslint.config.js`. 옮긴 경로는 오류, 나머지 경고. 적용되지 않던 `eslint.config.ts`를 합쳐 제거 |
| 미리보기 | 개발 전용 `/dev/design-system` 화면. 토큰 견본 + 컴포넌트. 포폴 그림의 원본 |
| 테스트 | Node 내장 러너, 18개 (`npm run test:unit`) |

### 핵심 숫자

| 항목 | 전 | 후 |
|---|---|---|
| 이동 요청: 팔레트 직접 사용 | 130회 | 0 |
| 이동 요청: 색상 값 하드코딩 | 86회 | 0 |
| 앱 전체: 팔레트 직접 사용 | 463회 | 315회 |
| 앱 전체: 하드코딩 | 159회 | 68회 |
| 대비 미달 (라이트, 옛 값) | 24 / 37개 조합 | 0 / 39 |
| 의미 토큰 사용 (작업 전) | 앱 전체 26회 vs 팔레트 직접 463회 | — |
| 다크 모드 | 대부분 화면이 라이트 고정 | 이동 요청 화면 5개 지원 |

가장 강한 한 줄 후보: "의미 토큰 26회 vs 팔레트 직접 사용 463회 — 다크 모드가 동작하지 않던 원인을 찾아 구조로 해결"

### 대표 사례 (글에 쓰기 좋은 것)

- **보조 글자색 `#9599a7`**: 16곳 하드코딩, 흰 배경 대비 2.84:1 → `text.weaker` `#666b79` 5.32:1
- **같은 역할, 네 가지 값**: 오류 글자색이 `#d4553a`, `#c8492e`, `#d84a36`, `#e5484d`로 흩어져 있던 것 → `text.error` 하나
- **"경고"와 "오류"의 구분**: 대기·재알림 배지가 기한 초과와 같은 주황을 쓰던 것 → `text.warning`으로 분리
- **유틸이 색을 반환**: 타임라인 유틸이 `dotColor: '#e5493d'`를 돌려주던 것 → `tone: 'error'`를 돌려주고 컴포넌트가 테마로 해석
- **문서 규칙이 동작하지 않던 것**: `eslint.config.ts`의 규칙이 실제로는 적용되지 않고 있었음(`.js`가 우선)

## 읽을 파일 (순서대로)

모든 경로는 `frontend/baro-app` 기준.

1. 이 문서
2. `docs/design-system/tokens.md`: 토큰 체계 설명서
3. `docs/design-system/metrics.md`: 전후 수치와 측정 명령, 확인하지 못한 것
4. `docs/design-system/color-mapping.md`: 옛 값 → 토큰, 바뀐 색과 이유 (사용자 승인 기록)
5. `docs/superpowers/specs/2026-11-26-usage-based-color-tokens-design.md`: 설계 문서 (검토한 대안과 선택 이유)
6. `docs/design-system/screenshots/`: `before-light/dark.png`, `after-light/dark.png` (미리보기 화면, 폭 500px)

admin-web 쪽: `frontend/baro-web/admin-web/src/styles/tokens.css`, `src/components/ui/StatusTag.vue`

## 남은 일

### 포폴 작업 (다음 세션의 본 작업)

- [ ] 포폴 페이지 형식 정하기 (2026-11-26: 미정. 형식과 무관한 마크다운 초안과 그림을 먼저 만들었다. PPT도 후보)
- [x] 위 "이야기 흐름" 순서로 초안 작성 → [`portfolio/case-study.md`](portfolio/case-study.md)
- [x] 그림 만들기 → `portfolio/figures/*.png`. 원본은 `portfolio/figures/src/*.html`, 다시 만들기는 `bash portfolio/figures/render.sh`
  - 토큰 이름 주석 그림 (`annotated-components.png`), 라이트/다크 나란히 (`light-dark-pair.png`)
  - 다크 모드 전후 (`dark-mode-before-after.png`)
  - 대비 전후 색 견본 (`contrast-before-after.png`)
  - 이름 규칙 도식 (`naming-rule.png`), 구조 도식 (`structure.png`)
- [x] 기여 범위 서술을 사용자에게 확인받기 (2026-11-26 "맞음")
- [ ] 초안 문장 검토 (사용자). 특히 프로젝트 기간 "2026년 7~8월"은 커밋 날짜로 적은 것
- [x] 정한 형식으로 옮기기 → PPT (2026-11-26). 사용자의 `주차바로 템플릿.pptx`(7장)를 채운 [`portfolio/deck/주차바로-포트폴리오.pptx`](portfolio/deck/주차바로-포트폴리오.pptx). 다시 만들기: `python portfolio/deck/build_deck.py <템플릿.pptx> <출력.pptx> gradient`
  - 색: 템플릿의 코랄 테마를 앱 브랜드 보라로 바꿨다 (2026-11-26 사용자 선택: 표지 "B. 앱 아이콘 그라데이션" 민트 #6fcfc4 → 보라 #8b7ff0). 빌드할 때 세 번째 인자 `gradient`를 준다. 다른 시안은 `violet`(단색 #5144d3), `deep`(#231f45)
  - 구성: 개요 → POINT 01 관리자 웹 사건 처리 → 02 관리자 웹 테이블 공용화 → 03 테마를 받는 스타일 구조 → 04 용도 기반 색 토큰 → 회고 → 성과·링크
  - 관리자 웹은 커밋 기준 본인이 대부분(화면·composable·공용 컴포넌트). 이동 요청 기능은 팀원이 주로 만들었으므로 덱에서도 "옮겼다"로만 쓴다
  - 관리자 웹 공용화 수치: 세 화면(`ParkingEventListView`, `HistoryView`, `ParkingZoneManagementView`) 2,006 → 1,220줄 (b700eea~1 → d117449). 로직이 composable로 옮겨간 것이지 전체 코드가 준 것은 아니다
- [ ] 덱에 없는 것: 수상 이력, 시연 영상, 공개 저장소 링크(GitLab은 SSAFY 내부). 있으면 성과 장에 추가
- [ ] 관리자 웹 주소(i15e202.p.ssafy.io)가 지금도 열리는지 확인

그림 메모:
- 주석·라이트/다크 그림은 미리보기 화면을 2배 해상도(폭 500px)로 다시 찍어 잘라 썼다 (`figures/src/assets/`).
- 다크 전후 그림은 기존 `screenshots/before-dark.png`, `after-dark.png`(1배)를 잘라 썼다. 작업 전 화면에서 안 보이는 제목은 미리보기 화면의 섹션 제목이다(테마를 따르는 글자만 흰색으로 바뀐 것).
- 관리자 웹 `StatusTag`는 본인이 만들고(2026-08-02) 팀원이 톤을 추가했다(2026-08-07). 글에 그렇게 적었다.

### 코드 쪽 (선택)

- [ ] 원격 push 여부 결정 (지금은 로컬 브랜치만. 팀 GitLab이라 사용자가 정한다). 포폴에 diff 링크를 걸려면 필요
- [ ] 하단 탭 비활성 라벨 색 확인: 라벨 `#666b79`, 아이콘 `#878d9b`로 나뉘었다. 라벨이 글자라 4.5 기준을 맞추느라 나눴는데, 사용자 확인을 받지 않았다
- [ ] 실제 이동 요청 화면 5개를 서버에 붙여 라이트/다크로 확인 (로그인·서버 필요해서 못 함)

## 알려진 한계 (포폴 "다음 단계"에 쓸 것)

- 옮긴 범위는 이동 요청 기능과 공용 컴포넌트 7개뿐. 나머지에 팔레트 직접 사용 315회, 하드코딩 68회
- 린트·테스트·대비 검사가 CI에 연결되지 않음 (Jenkins는 typecheck만, Node 20이라 새 스크립트가 돌지 않음)
- 두 프론트의 토큰을 손으로 복사해 맞추는 구조 (원본 하나에서 생성하는 파이프라인이 다음 단계)
- 주차 도면은 다크에서도 라이트
- 보조 글자 `text.weak`(5.94)와 `text.weaker`(5.32)의 차이가 작아짐. 위계를 글자 크기·굵기가 맡음
- 간격·글자 크기에 스케일 밖 값(`12.5`, `Spacing.md + 2`)이 남음
- 웹에서만 확인, Android/iOS 기기 미확인

## 다시 실행하는 법

```powershell
git switch refactor/fe/usage-based-color-tokens
```

```powershell
cd frontend/baro-app; npm ci
```

```powershell
npm run typecheck; npm run test:unit; npm run check:contrast; npx eslint .
```

```powershell
npm run count:colors
```

미리보기 화면: `npm run web` 후 `http://localhost:8081/dev/design-system`. 화면 저장은 개발 서버를 띄운 상태에서 `bash scripts/capture-preview.sh after 8081` (Windows Chrome 경로 고정).

`test:unit`, `check:contrast`는 Node 22.15 이상이 필요하다 (작업 환경은 Node 24).

## 사용자 선호 (이 세션에서 확인된 것)

- 대화는 한국어로
- 색처럼 화면이 바뀌는 결정은 견본을 나란히 보여주고 사용자가 고르게 함 (이번 매핑 표 A~N은 모두 승인됨)
- 원격 push, MR 생성은 사용자가 결정
