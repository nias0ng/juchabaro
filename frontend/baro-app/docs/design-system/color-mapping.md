# 색상 매핑 표

범위: `src/features/move-request` 전체와 공용 컴포넌트 7개. 지금 쓰이는 색 참조 하나하나를 새 토큰으로 옮기는 기준이다.

- 대비는 WCAG 2.1 공식으로 계산했다. 기준: 본문 글자 4.5, 아이콘 3.
- "배경"은 그 색이 실제로 놓이는 면 중 대비가 가장 낮게 나오는 것이다.
- 상태: **승인됨** (2026-11-26, 1절 A~N 전부 새 값으로)

## 1. 확인 필요 — 라이트 화면에서 색이 달라지는 행

<!-- 견본: 왼쪽이 지금, 오른쪽이 새 값 -->

| # | 토큰 | 지금 → 새 값 | 견본 | 대비 (지금 → 새 값) | 이유 | 쓰이는 곳 |
|---|---|---|---|---|---|---|
| A | `text.weaker` | `#9599a7`, `#7b8091`, `#b6bac7` → `#666b79` | <span style="background:#9599a7">　　</span> <span style="background:#666b79">　　</span> | 흰 배경 2.84 / 3.93 / 1.94 → 5.32, 옅은 배경 → 4.95 | AA 미달 | 타임라인 설명, 카드 보조 글자, 날짜, 입력창 안내 문구 등 약 45곳 |
| B | `text.error` | `#d4553a`, `#c8492e`, `#d84a36`, `#e5484d` → `#c2412b` | <span style="background:#d4553a">　　</span> <span style="background:#c2412b">　　</span> | 옅은 주황 배경 3.72 → 4.70 | AA 미달 + 4개 값 합치기 | 기한 초과 글자, 경고 문구, 필수 표시 |
| C | `text.warning` | `#d4553a`(배지·타임라인 글자) → `#a35b3d` | <span style="background:#d4553a">　　</span> <span style="background:#a35b3d">　　</span> | 옅은 주황 배경 3.72 → 4.66 | AA 미달. `#a35b3d`는 재알림 안내문에 이미 쓰이는 값 | 대기·재알림·관리자 이관 배지, 재알림 타임라인 글자 |
| D | `text.success` | `#1e8d80`, `#00a38b`, `#2fae9e` → `#177568` | <span style="background:#1e8d80">　　</span> <span style="background:#177568">　　</span> | 옅은 청록 배경 3.52 → 4.81 | AA 미달 + 합치기 | 완료 배지, 응답 완료 글자 |
| E | `text.info` | `#3f7bd6` → `#2a5fb3` | <span style="background:#3f7bd6">　　</span> <span style="background:#2a5fb3">　　</span> | 옅은 파랑 배경 3.31 → 4.90 | AA 미달 | 종료 배지, 헤더 오른쪽 상태 |
| F | `text.brand` | `#5c4fe0`, `#7a6ff0` → `#5144d3` | <span style="background:#5c4fe0">　　</span> <span style="background:#7a6ff0">　　</span> <span style="background:#5144d3">　　</span> | `#7a6ff0` 흰 배경 3.92 → 6.74 | 합치기 (브랜드 기본색으로). `#7a6ff0`은 AA 미달 | 응답 배지, 타임라인 마지막 단계 글자, 링크 글자 |
| G | `fill.error.strong` | `#e5493d`, `#e5484d`, `#d4553a`(점) → `#d63a40` | <span style="background:#e5484d">　　</span> <span style="background:#d63a40">　　</span> | 위에 놓인 흰 글자 3.91 → 4.63 | AA 미달 (하단 탭 알림 배지의 흰 숫자) | 타임라인 점, 하단 탭 배지 |
| H | `icon.weak` | `#9ca3af` → `#878d9b` | <span style="background:#9ca3af">　　</span> <span style="background:#878d9b">　　</span> | 2.54 → 3.33 | 아이콘 기준(3) 미달 | 하단 탭 비활성 아이콘 |
| I | `fill.brand.weak` | `#ede9fd`, `#eae8fb`, `#e3dfff`, `#dcd7fb`(배지 배경) → `#ede9fd` | <span style="background:#dcd7fb">　　</span> <span style="background:#ede9fd">　　</span> | — | 4개 값 합치기 | 응답 배지, 이력 카드 배지, 링 바탕선 |
| J | `fill.neutral.weak` | `#f5f4fb`, `#f2f0fa`, `#f0f0f3` → `#f0f0f3` | <span style="background:#f5f4fb">　　</span> <span style="background:#f0f0f3">　　</span> | — | 합치기 (거의 구분 안 됨) | 칩 배경, 진행 막대 바탕 |
| K | `fill.neutral.strong` | `#c9c4e8` → `#d1d2dc` | <span style="background:#c9c4e8">　　</span> <span style="background:#d1d2dc">　　</span> | — | 합치기 (보랏빛 회색 → 팔레트 회색) | 진행 카드의 지나지 않은 단계 |
| L | `stroke.weak` | `#e2e0ec`, `#f3f4f6` → `#e1e1e8` | <span style="background:#e2e0ec">　　</span> <span style="background:#e1e1e8">　　</span> | — | 합치기 (구분 안 됨) | 타임라인 선, 대기 점, 하단 탭 윗선 |
| M | `fill.error.weak` / `fill.warning.weak` | `#fff0eb`, `#f6dcd0`, `#ffdccd` → `#fff2ef` | <span style="background:#f6dcd0">　　</span> <span style="background:#fff2ef">　　</span> | — | 합치기. 링 바탕선(`#f6dcd0`, `#ffdccd`)은 눈에 띄게 옅어진다 | 대기 배지 배경, 기한 초과·재알림 링 바탕선 |
| N | `text.strong` | `#3d4250`, `#474554` → `#14161c` / `text.weak` | <span style="background:#3d4250">　　</span> <span style="background:#14161c">　　</span> | — | 합치기. 입력한 글자(`#3d4250`)는 `text.strong`, 시간 안내(`#474554`)는 `text.weak` | 사유 입력창, 시간 버튼 안내 |

### A행에 대해 미리 알릴 점

AA를 맞추면 `text.weak`(`#60646c`, 5.94)와 `text.weaker`(`#666b79`, 5.32)의 차이가 거의 없어진다. 지금 화면은 보조 글자를 3단계(진함 / 중간 / 옅음)로 나눠 쓰는데, 옅은 단계가 기준을 못 넘기 때문이다. 선택지는 둘이다.

- **바꾼다 (권장)**: 위계는 색 대신 글자 크기와 굵기에 맡긴다. 대비 검사를 예외 없이 통과한다.
- **유지한다**: `text.weaker`를 `#9599a7` 그대로 두고 대비 검사의 알려진 예외로 적는다. 화면은 안 바뀌지만 11~12.5px 글자가 2.84:1로 남는다.

## 2. 값이 그대로인 행

| 토큰 | 값 (팔레트) | 지금 쓰이는 형태 |
|---|---|---|
| `text.strong` | `#14161c` (gray975) | `color: Palette.gray975` |
| `text.weak` | `#60646c` (gray600) | `Palette.gray600`, `#5c6070`(구분 안 됨) |
| `text.inverse` | `#ffffff` (white) | 진한 버튼·배지 위 `color: Palette.white` |
| `text.brand` | `#5144d3` (violet600) | `Palette.violet600` |
| `fill.brand.strong` | `#5144d3` (violet600) | 링 진행선 `#5c4fe0`(F행과 같이 합침), 타임라인 점 `#7a6ff0` → 진행 중 점은 `fill.brand.strong` |
| `fill.success.strong` | `#2fae9e` (emerald500) | 타임라인 기본 점, 선택된 구역 테두리 |
| `fill.success.weak` | `#dff3ef` (teal100) | 완료 배지 배경, `#e1f8f5`(구분 안 됨) |
| `fill.warning.strong` | `#ff8f6b` (orange400) | 재알림 타임라인 점 |
| `fill.info.weak` | `#d5e6ff` (sky100) | 종료 배지 배경 |
| `fill.inverse.strong` | `#14161c` (gray975) | 진한 버튼, 선택된 탭 `backgroundColor: Palette.gray975` |
| `stroke.strong` | `#d1d2dc` (gray300) | 사진 추가 칸 테두리 |
| `stroke.brand` | `#dcd7fb` (lavender100) | 목록 카드 테두리 |
| `stroke.error` | `#ff8f6b` (orange400) | 번호판 오류 테두리, 재알림 안내 테두리 |
| `stroke.success` | `#2fae9e` (emerald500) | 선택된 구역 테두리 |
| `background.neutral` | `#ffffff` (white) | 화면 바탕 |
| `background.weak` | `#f7f6fb` (lilac25) | 화면 바탕 `Palette.gray50`(`#f8f8fa`, 구분 안 됨), 그라데이션 끝 색 |
| `background.raised` | `#ffffff` (white) | 카드 `backgroundColor: Palette.white` |
| `shadow` | `#14161c` (gray975) | `shadowColor: Palette.gray975`, `rgba(20,22,28,0.18)` |
| `gradient.brand` | `#eae7fb → #f7f6fb → #f7f6fb` | 목록·전송·대기·완료 화면 배경 (`#ede9fd`, `#f0edfb` 시작색 합침) |
| `gradient.error` | `#ffe9e2 → #f7f6fb → #f7f6fb` | 기한 초과 화면 배경 |
| `gradient.warning` | `#fbe0dc → #f7f6fb → #f7f6fb` | 재알림 화면 배경 |
| `gradient.accent` | `#6fcfc4 → #8b7ff0` | 완료 체크 배지 (기존 `Gradients.avatar`와 같은 값) |
| `overlay.scrim` | `rgba(20, 22, 28, 0.5)` | 구역 선택 모달 뒤 막 |
| `overlay.scrimStrong` | `rgba(20, 22, 28, 0.65)` | 사진 삭제 버튼 바탕 |
| `overlay.onMediaFill` | `rgba(255, 255, 255, 0.16)` | 사진 위 버튼 바탕 |
| `overlay.onMediaCaption` | `rgba(27, 27, 35, 0.68)` | 사진 위 설명 바탕 |
| `overlay.onMediaText` | `#ffffff` | 사진 위 글자 (모드와 무관하게 흰색) |
| `overlay.onMediaShadow` | `rgba(0, 0, 0, 0.6)` | 사진 위 글자 그림자 |
| `overlay.mediaBackdrop` | `#000000` | 사진 뒤 바탕 |
| `overlay.glass` | `rgba(255, 255, 255, 0.85)` | 전송 완료 화면의 반투명 카드 |

## 3. 다크 값

역할마다 라이트와 같은 대비 수준을 갖도록 정했다. 괄호는 가장 불리한 배경 위 대비.

| 토큰 | 다크 값 | 비고 |
|---|---|---|
| `background.neutral` / `weak` / `raised` | `#000000` / `#14161c` / `#212225` | 높이가 올라갈수록 밝아진다. 기존 `Colors.dark.background` / `surface`와 같은 값 |
| `text.strong` / `weak` / `weaker` | `#ffffff` (15.91) / `#b6bac7` (7.6 이상) / `#979ba8` (5.73) | |
| `text.inverse` | `#1b1b23` | 밝은 면 위 글자 |
| `text.brand` / `error` / `warning` / `success` / `info` | `#c3bcff` (7.33) / `#ff8f6b` (6.75) / `#f5a97f` (7.52) / `#6fcfc4` (7.21) / `#8ab6f7` (6.48) | 각 톤의 `fill.*.weak` 위 기준 |
| `icon.weak` | `#7b8091` (4.04) | |
| `fill.brand.strong` / `weak` | `#c3bcff` / `#302d55` | |
| `fill.error.strong` / `weak` | `#ff6369` / `#3a1f1a` | |
| `fill.warning.strong` / `weak` | `#ff8f6b` / `#3a2418` | |
| `fill.success.strong` / `weak` | `#2fae9e` / `#143530` | |
| `fill.info.weak` | `#1b2f4d` | |
| `fill.neutral.strong` / `weak` | `#3a3d43` / `#2e3135` | |
| `fill.inverse.strong` | `#f0f0f3` | 진한 버튼이 다크에서는 밝은 버튼이 된다 |
| `stroke.weak` / `strong` / `brand` / `error` / `success` | `#2e3135` / `#3a3d43` / `#302d55` / `#a83f31` / `#2fae9e` | |
| `shadow` | `#000000` | |
| `gradient.brand` / `error` / `warning` | `#231f45` / `#3a1f1a` / `#3a2418` → `#14161c` → `#14161c` | |
| `gradient.accent`, `overlay.*` | 라이트와 같음 | |

## 4. 토큰으로 옮기지 않는 것

- 구역 선택 모달의 주차 도면 범례 4색(`Palette.violet300`, `gray100`, `teal100`, `sky100`): 주차 도면의 칸 색과 짝을 이루는 값이다. 도면이 범위 밖이므로 처리 방법은 작성 화면을 옮길 때 `features/parking`의 기존 상수를 확인해 정한다.
