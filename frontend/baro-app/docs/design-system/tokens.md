# 색상 토큰

정의: `src/styles/color-tokens.ts` · 팔레트: `src/styles/colors.ts` · 근거: [color-mapping.md](color-mapping.md) · 측정: [metrics.md](metrics.md)

## 이름 규칙

색 이름은 색상명이 아니라 **어디에 어떻게 쓰는지**로 짓는다.

```
요소 . 톤 . 강조
```

| 자리 | 값 | 뜻 |
|---|---|---|
| 요소 | `text` `icon` `stroke` `fill` `background` | 색이 칠해지는 대상. `fill`은 버튼·배지·점 같은 요소 자체의 면, `background`는 화면·카드 같은 바탕 |
| 톤 | (중립은 생략) `brand` `error` `warning` `success` `info` `inverse` | 색이 전하는 의미 |
| 강조 | `strong` `weak` `weaker` | 눈에 띄는 정도 |

예: `t.text.weak`(보조 글자), `t.fill.error.strong`(오류를 뜻하는 진한 면), `t.stroke.brand`(브랜드 색 테두리).

규칙 밖의 묶음은 넷이다.

| 묶음 | 용도 |
|---|---|
| `background.raised` | 카드처럼 떠 있는 면. 다크에서는 그림자가 보이지 않으므로 바탕보다 밝은 면으로 높이를 나타낸다 |
| `gradient.*` | 화면 배경 그라데이션 |
| `overlay.*` | 반투명 막과 사진 위 요소. 사진 위 값은 모드와 무관하다 |
| `parkingMap.*` | 주차 도면 범례. 도면의 칸 색과 짝이라 모드와 무관하다 |

## 층 구조

```
Palette (원시 값)            violet600, gray550, orange700 …
   ↓ 가리킨다
ColorTokens (용도 기반)      text.brand, text.weaker, text.error …   라이트 / 다크 두 벌
   ↓ createStyles(t)
컴포넌트 스타일
```

용도 기반 토큰은 모두 팔레트 단계를 가리킨다. 색상 값을 직접 적는 곳은 팔레트와 `overlay`뿐이다.

## 토큰 표

### text / icon

| 토큰 | 라이트 | 다크 | 쓰는 곳 |
|---|---|---|---|
| `text.strong` | `#14161c` gray975 | `#ffffff` white | 제목, 본문 |
| `text.weak` | `#60646c` gray600 | `#b6bac7` gray400 | 보조 설명 |
| `text.weaker` | `#666b79` gray550 | `#979ba8` gray425 | 날짜, 안내 문구, 입력창 안내 |
| `text.inverse` | `#ffffff` white | `#1b1b23` gray950 | `fill.*.strong` 위 글자 |
| `text.brand` | `#5144d3` violet600 | `#c3bcff` violet300 | 링크, 강조 값 |
| `text.error` | `#c2412b` orange700 | `#ff8f6b` orange400 | 기한 초과, 오류 |
| `text.warning` | `#a35b3d` orange800 | `#f5a97f` peach300 | 대기, 재알림 |
| `text.success` | `#177568` teal700 | `#6fcfc4` mint300 | 완료 |
| `text.info` | `#2a5fb3` blue700 | `#8ab6f7` blue300 | 종료, 안내 |
| `icon.weak` | `#878d9b` gray450 | `#7b8091` gray500 | 비활성 아이콘 |

### fill / stroke / background

| 토큰 | 라이트 | 다크 |
|---|---|---|
| `fill.brand.strong` / `weak` | `#5144d3` / `#ede9fd` | `#c3bcff` / `#302d55` |
| `fill.error.strong` / `weak` | `#d63a40` / `#fff2ef` | `#ff6369` / `#3a1f1a` |
| `fill.warning.strong` / `weak` | `#ff8f6b` / `#fff2ef` | `#ff8f6b` / `#3a2418` |
| `fill.success.strong` / `weak` | `#2fae9e` / `#dff3ef` | `#2fae9e` / `#143530` |
| `fill.info.weak` | `#d5e6ff` | `#1b2f4d` |
| `fill.neutral.strong` / `weak` | `#d1d2dc` / `#f0f0f3` | `#3a3d43` / `#2e3135` |
| `fill.inverse.strong` | `#14161c` | `#f0f0f3` |
| `stroke.weak` / `strong` | `#e1e1e8` / `#d1d2dc` | `#2e3135` / `#3a3d43` |
| `stroke.brand` / `error` / `success` | `#dcd7fb` / `#ff8f6b` / `#2fae9e` | `#302d55` / `#a83f31` / `#2fae9e` |
| `background.neutral` / `weak` / `raised` | `#ffffff` / `#f7f6fb` / `#ffffff` | `#000000` / `#14161c` / `#212225` |

## 대비 기준

글자와 아이콘 토큰은 실제로 놓이는 배경 위에서 WCAG 2.1 AA를 만족한다: 본문 글자 4.5:1, 아이콘 3:1. 라이트와 다크 모두 검사한다.

```powershell
npm run check:contrast
```

검사하는 조합은 `src/styles/contrast.ts`의 `CONTRAST_PAIRS`에 있다. 토큰을 추가하면 그 토큰이 놓이는 배경과의 조합도 함께 추가한다. 테두리는 구분선 용도라 검사하지 않는다.

## 쓰는 법

색을 쓰는 스타일 파일은 토큰을 받는 함수를 내보낸다.

```ts
// request-timeline-card.styles.ts
export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    stepDetail: { fontSize: 11, color: t.text.weaker },
  });

// request-timeline-card.tsx
const styles = useThemedStyles(createStyles);
```

- `createStyles`는 모듈 최상위에 둔다. 모드별로 한 번만 만들어 재사용한다.
- 스타일 밖에서 색이 필요하면(SVG `stroke`, `placeholderTextColor`) `useColorTokens()`를 쓴다.
- 유틸 함수는 색 값을 돌려주지 않는다. `'error'` 같은 톤 이름을 돌려주고 컴포넌트가 토큰으로 푼다.

### 다크 모드는 옮긴 화면에서만 켜진다

```ts
export default withAdaptiveColors(RequestsScreen);
```

이렇게 감싼 화면 안에서만 기기의 다크 모드를 따른다. 공용 컴포넌트(헤더, 배경)는 아직 옮기지 않은 화면에서도 쓰이는데, 그런 화면은 글자색이 라이트로 고정되어 있어 공용 컴포넌트만 어두워지면 글자가 배경에 묻힌다. 그래서 화면 단위로 켠다.

### 린트

`eslint.config.js`가 `src/styles` 밖에서 색상 값 문자열과 `Palette` 가져오기를 막는다. 옮긴 경로(`TOKENIZED_FILES`)는 오류, 나머지는 경고다. 기능을 옮기면 경로를 추가한다.

## 알려진 한계

- **옮긴 범위**: 이동 요청 기능과 공용 컴포넌트 7개뿐이다. 나머지 기능에는 팔레트 직접 사용 315회, 하드코딩 68회가 남아 있다.
- **하단 탭**: 하단 탭은 자기 배경을 스스로 칠하는 독립된 면이라 화면과 상관없이 기기 모드를 따른다. 그래서 아직 옮기지 않은 화면에서는 다크 모드일 때 라이트 화면 아래에 어두운 탭이 놓인다(이전과 같은 동작).
- **주차 도면**: 구역 선택 모달 안의 도면은 다크에서도 라이트 색이다. 칸 색 자체가 정보라 별도 설계가 필요하다.
- **보조 글자 위계**: 대비 기준을 맞추면서 `text.weak`(5.94)와 `text.weaker`(5.32)의 차이가 작아졌다. 위계는 글자 크기와 굵기가 맡는다.
- **간격·글자 크기**: 이동 요청 스타일에는 `fontSize: 12.5`, `Spacing.md + 2` 같은 스케일 밖 값이 남아 있다. 이번 범위가 아니다.
- **기존 `Colors` / `useTheme()`**: 그대로 남아 있다. 모든 기능을 옮긴 뒤에 걷어낸다.
- **CI**: 대비 검사와 린트는 CI에 연결하지 않았다. 로컬에서 돌린다.
