/**
 * 색상 팔레트 
 */
export const Palette = {
  white: '#ffffff',
  white72: 'rgba(255, 255, 255, 0.72)',
  white80: 'rgba(255, 255, 255, 0.8)',
  black: '#000000',

  gray25: '#fcfcfc',
  gray50: '#f8f8fa',
  gray100: '#f0f0f3',
  gray200: '#e1e1e8',
  gray300: '#d1d2dc',
  gray400: '#b6bac7',
  gray500: '#7b8091',
  gray600: '#60646c',
  gray700: '#474554',
  gray900: '#212225',
  gray950: '#1b1b23',
  gray975: '#14161c',

  violet50: '#fcf8ff',
  violet100: '#e3dfff',
  violet300: '#c3bcff',
  violet500: '#7a6ff0',
  violet600: '#5144d3',

  red500: '#e5484d',
  coral500: '#ff6b57',
  orange50: '#fff2ef',
  orange400: '#ff8f6b',
  orange600: '#d4553a',

  // 홈 대시보드
  mint100: '#c9ece7',
  emerald500: '#2fae9e',
  lavender100: '#dcd7fb',
  peach100: '#ffdccd',
  sky100: '#d5e6ff',
  blue500: '#4f8ff0',
  blue600: '#3f7bd6',
  amber50: '#fff4e0',
  amber500: '#f5a524',

  // 주차 도면 - 장애인/전기차 구역
  teal100: '#dff3ef',
  teal600: '#1e8d80',

  // 주차 도면 - 빈 장애인 구역
  green100: '#cdf0d8',

  // 주차 도면 - 내 차량 강조. 다른 칸들(sky100/green100/violet300 등)과 같은 밝기대의
  yellow100: '#f6ecc0',
  yellow700: '#8a6100',

  // 주차 도면 - 남의 차(사용중) 칸 글씨
  purple700: '#7a0395',

  // 주차 도면 전체 보기(J-01) - 칸/구분선 배경
  lilac25: '#f7f6fb',
  lilac50: '#eeecf8',
  lilac100: '#e7e5f3',
  lilac200: '#c9c2f0',

  // 용도 기반 토큰(color-tokens.ts)용 추가 단계.
  // 대비 기준(WCAG AA)을 맞추거나 다크 모드 값을 주기 위해 기존 단계 사이에 넣었다.
  // 근거는 docs/design-system/color-mapping.md.
  gray425: '#979ba8',
  gray450: '#878d9b',
  gray550: '#666b79',
  gray750: '#3a3d43',
  gray800: '#2e3135',

  violet75: '#ede9fd',
  violet400: '#8b7ff0',
  violet900: '#302d55',
  violet950: '#231f45',
  lavender50: '#eae7fb',

  red400: '#ff6369',
  red600: '#d63a40',
  rose50: '#fbe0dc',
  peach50: '#ffe9e2',
  peach300: '#f5a97f',
  orange700: '#c2412b',
  orange800: '#a35b3d',
  orange900: '#a83f31',
  orange950: '#3a1f1a',
  brown950: '#3a2418',

  mint300: '#6fcfc4',
  teal700: '#177568',
  teal950: '#143530',

  blue300: '#8ab6f7',
  blue700: '#2a5fb3',
  blue950: '#1b2f4d',
} as const;

/**
 * 테마 색상
 */
export const Colors = {
  light: {
    text: Palette.black,
    textSecondary: Palette.gray600,
    placeholder: Palette.gray400,
    background: Palette.white,
    backgroundElement: Palette.gray100,
    backgroundSelected: Palette.gray200,
    surface: Palette.white,
    surfaceMuted: Palette.gray50,
    border: Palette.gray200,
    primary: Palette.violet600,
    primarySoft: Palette.violet100,
    onPrimary: Palette.white,
    danger: Palette.orange600,
    dangerBorder: Palette.orange400,
    dangerSurface: Palette.orange50,
    disabledSurface: Palette.violet100,
    disabledText: Palette.gray400,
  },
  dark: {
    text: Palette.white,
    textSecondary: '#b0b4ba',
    placeholder: '#6b6f78',
    background: Palette.black,
    backgroundElement: Palette.gray900,
    backgroundSelected: '#2e3135',
    surface: Palette.gray900,
    surfaceMuted: '#1f2024',
    border: '#3a3d43',
    primary: Palette.violet300,
    primarySoft: '#302d55',
    onPrimary: Palette.gray950,
    danger: '#ff6369',
    dangerBorder: '#a83f31',
    dangerSurface: '#3a1f1a',
    disabledSurface: '#302d55',
    disabledText: '#6b6f78',
  },
} as const;

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;
