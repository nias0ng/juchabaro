# 글로벌 공통 컴포넌트 선(先)구축 — MainIcon / BackButton / BottomNavBar

## 배경

프론트엔드 개발자 2명(나, 팀원 chaewon)이 각자 브랜치에서 작업 중이며, 곧 `develop`으로 중간 merge를 진행할 예정이다. merge 전에 Figma "최종 정리" 파일의 3개 프레임(Z-01. MainIcon, Z-02. BottomNavBar, Z-03. BackButton)을 `src/components/ui`에 컴포넌트 파일로 미리 만들어둔다.

**중요한 제약**: 이번 작업은 컴포넌트 파일 생성까지만 한다. 기존 화면(`AuthHeader`, `VehicleHeader`, `resident/_layout.tsx`의 `Tabs`)에 새 컴포넌트를 연결하는 작업은 하지 않는다. 실제 연동은 merge 이후 별도 작업으로 진행한다.

### 현재 상태 조사 결과

- `src/components/ui`가 이미 공유 컴포넌트 폴더로 정착되어 있고(`AGENTS.md`에 명시), `index.ts`로 배럴 export한다.
- `BottomNavBar`, `BackButton`에 해당하는 공유 컴포넌트는 아직 없다.
  - 하단 탭바는 Expo Router `<Tabs>`(`src/app/resident/_layout.tsx`)가 담당하며, 아이콘은 feature-local `src/features/resident/components/tab-bar-icon.tsx`가 그린다(홈/알림/내정보 line icon path 보유).
  - 뒤로가기 버튼은 `AuthHeader`(`features/auth/components`)와 `VehicleHeader`(`features/resident/components/manageCar`) 두 곳에 각각 인라인으로 존재하며 스타일이 미묘하게 다르다.
  - 팀원의 `origin/feature/fe/326-auto-process` 브랜치는 `AuthHeader`를 `src/components/ui/screen-header.tsx`(`ScreenHeader`)로 이미 승격시켜 놓은 상태 — 같은 문제를 독립적으로 풀고 있었고, 이 차이는 merge 시 조율이 필요하다(이번 작업 범위 밖, 참고만 함).
- 아이콘은 아이콘 라이브러리 없이 `react-native-svg`의 `Svg`/`Path`로 직접 구현하는 것이 기존 관례다(`tab-bar-icon.tsx`, `bell-icon.tsx`).
- `assets/images/`가 이미 존재하며 래스터 이미지(스플래시, 인증 일러스트) 저장 위치로 쓰이고 있다.

### Figma 원본 확인 결과

| 프레임 | node-id | 크기 | 내용 |
|---|---|---|---|
| Z-01. MainIcon | 2023:2 | 96×96 | 흰 라운드 사각형 + 그림자 위에 그라데이션 자동차 로고. **래스터 PNG**(벡터 아님) |
| Z-02. BottomNavBar | 2087:2 | 390×72 | 4탭: 홈/요청/알림/내정보. 라벨이 현재 앱 구현과 동일. 홈·알림·내정보는 단색 line icon(SVG), **요청 탭만 컬러 아이콘**(용량 58KB로 유독 큼 → 래스터 취급) |
| Z-03. BackButton | 2161:9 | 48×48 | chevron(‹) line icon, 단색 SVG |

MainIcon과 BottomNavBar의 "요청" 아이콘은 실제 이미지 파일을 다운로드해 `assets/images/`에 저장해야 한다. 나머지 아이콘(홈/알림/내정보/back chevron)은 기존 관례대로 SVG path를 코드로 재현한다.

## 범위

**포함**
- `MainIcon`, `BackButton`, `BottomNavBar` 3개 컴포넌트 파일 생성 (`src/components/ui`)
- 내부 공용 아이콘 렌더 헬퍼 `IconGlyph` 생성 (비export, 두 컴포넌트가 공유)
- `Screen`에 `header`/`bottomBar` slot prop 추가
- 필요한 이미지 에셋 다운로드 및 저장
- `index.ts` 배럴 export 갱신
- typecheck + 임시 프리뷰 라우트를 통한 육안 검증

**제외 (병합 이후 별도 작업)**
- `AuthHeader`/`VehicleHeader`/`ScreenHeader`를 `BackButton`으로 교체
- `resident/_layout.tsx`의 `Tabs`를 `BottomNavBar`로 교체(커스텀 `tabBar` 연결)
- `tab-bar-icon.tsx`의 중복 제거/삭제
- 실제 화면에 `Screen`의 `header`/`bottomBar` slot 사용

## 파일 구조

```
src/components/ui/
├─ main-icon.tsx
├─ main-icon.styles.ts
├─ back-button.tsx
├─ back-button.styles.ts
├─ bottom-nav-bar.tsx
├─ bottom-nav-bar.styles.ts
├─ icon-glyph.tsx          # 비export 내부 헬퍼
├─ screen.tsx               # header/bottomBar prop 추가 (기존 파일 수정)
└─ index.ts                 # 3개 컴포넌트 export 추가 (기존 파일 수정)

assets/images/
├─ main-icon.png
└─ nav-icon-request.png
```

## 컴포넌트 설계

### `IconGlyph` (내부 헬퍼, 비export)

```ts
type IconGlyphProps = {
  d: string;
  size?: number;        // default 24
  color: string;
  strokeWidth?: number;  // default 2
};
```
`<Svg viewBox="0 0 {size} {size}" fill="none"><Path d={d} stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" /></Svg>` 보일러플레이트를 한 곳에 모은다. `BackButton`과 `BottomNavBar`(홈/알림/내정보)가 공유한다.

### `MainIcon`

```ts
type MainIconProps = { size?: number };  // default 96, 1:1 비율 고정
```
`assets/images/main-icon.png`을 `<Image>`로 렌더링, `width/height`를 `size`로 계산. 둥근 모서리·그림자는 이미지 자체에 포함되어 있으므로 별도 스타일 불필요(Figma 원본이 이미 합성된 결과물).

### `BackButton`

```ts
type BackButtonProps = {
  onPress: () => void;
  color?: string;   // default: theme.text
  size?: number;     // 아이콘 크기, default 24. 터치 영역은 Figma 그대로 48 고정
};
```
`Pressable`(48×48, `accessibilityRole="button"`) 안에 `IconGlyph`로 chevron 렌더링. 네비게이션 로직(`router.back()` 등)은 포함하지 않고 `onPress`로 위임 — 공통 컴포넌트에 라우팅을 넣지 않는다는 기존 규칙 준수.

### `BottomNavBar`

```ts
type NavIconKey = 'home' | 'request' | 'bell' | 'user';
type NavItem = { key: string; label: string; icon: NavIconKey; badge?: boolean };
type BottomNavBarProps = {
  items?: NavItem[];   // 기본값: Figma의 홈/요청/알림/내정보 4탭 프리셋
  activeKey: string;
  onPressItem: (key: string) => void;
};
```
홈/알림/내정보는 `IconGlyph` + `tab-bar-icon.tsx`와 동일한 path 상수(이 파일에 새로 정의, 아래 "중복 처리" 참고)로 렌더링. "요청"은 `assets/images/nav-icon-request.png`를 `<Image>`로 렌더링. `내정보`의 `badge`가 true면 Figma의 `notification-dot`(우상단 빨간 점)을 표시.

지금은 어떤 네비게이터에도 연결하지 않는 순수 프레젠테이션 컴포넌트로만 만든다.

## `Screen` 확장

```ts
type ScreenProps = {
  ...기존,
  header?: ReactNode;     // SafeAreaView 내부, 스크롤 콘텐츠 위에 고정
  bottomBar?: ReactNode;   // SafeAreaView 내부, 스크롤 콘텐츠 아래에 고정
};
```
`Screen`은 `BackButton`/`BottomNavBar`를 알 필요 없이 `ReactNode` slot만 노출한다. 병합 후 실제 연동 시 `<Screen header={<...}>` 형태로 바로 조립할 수 있게 API만 준비해두고, 지금은 어떤 화면에도 slot을 채우지 않는다.

## 중복 코드 처리 방침

`tab-bar-icon.tsx`(홈/알림/내정보 path)와 새 `bottom-nav-bar.tsx`는 당분간 동일한 path 문자열을 각자 보유한다(의도적 임시 중복). `tab-bar-icon.tsx`를 고쳐서 지금 바로 합치지 않는 이유:
- 이번 작업 범위(3개 신규 파일 생성)를 벗어난 기존 파일 수정이 되어 "연동은 병합 후"라는 전제와 어긋난다.
- 팀원의 326 브랜치가 `_layout.tsx`/`bell-icon.tsx` 근처를 이미 건드리고 있어 병합 충돌 표면을 늘린다.
- `tab-bar-icon.tsx`는 병합 후 `BottomNavBar` 연동 시 통째로 대체·삭제될 예정이라, 지금 합쳐도 어차피 며칠 뒤 사라진다.

## 에셋 처리

Figma MCP `download_assets`로 받은 임시 URL(약 7일 후 만료)에서 다음을 다운로드해 커밋한다:
- `main-icon.png` (Z-01 raw image)
- `nav-icon-request.png` (Z-02 "요청" 탭 svgAsset — 58KB, 컬러 아이콘)

나머지(홈/알림/내정보/back chevron) SVG는 path 데이터를 코드로 직접 옮긴다(이미지 저장 없음).

## 검증 계획

- `npm.cmd run typecheck` 실행, 통과 확인.
- 3개 컴포넌트를 한 화면에 모아 렌더링하는 임시 프리뷰 라우트를 만들어 Figma 스크린샷과 육안 비교한 뒤, 확인이 끝나면 해당 임시 라우트 파일을 삭제한다(커밋에 남기지 않음).
- 기존 화면/네비게이션 동작에는 변경이 없으므로(연동 안 함) 회귀 테스트는 불필요.
