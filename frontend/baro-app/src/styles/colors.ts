/**
 * 앱 전체에서 사용하는 원시 색상 팔레트입니다.
 * 화면에서는 가능한 한 Colors의 의미 기반 색상을 사용하세요.
 */
export const Palette = {
  white: '#ffffff',
  black: '#000000',

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
  orange400: '#ff8f6b',
  orange600: '#d4553a',
} as const;

/**
 * 테마에 따라 달라지는 의미 기반 색상입니다.
 * 컴포넌트는 구체적인 색상명보다 text, background, primary 같은 역할을 참조합니다.
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
  },
} as const;

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;
