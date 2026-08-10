/**
 * 색상 팔레트 (frontend/baro-app/src/styles/colors.ts와 동일한 값을 사용해 톤을 맞춘다)
 */
export const Palette = {
  white: '#ffffff',
  white72: 'rgba(255, 255, 255, 0.72)',
  white80: 'rgba(255, 255, 255, 0.8)',
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
  coral500: '#ff6b57',
  orange50: '#fff2ef',
  orange400: '#ff8f6b',
  orange600: '#d4553a',

  mint100: '#c9ece7',
  emerald500: '#2fae9e',
  lavender100: '#dcd7fb',
  peach100: '#ffdccd',
  sky100: '#d5e6ff',
  blue500: '#4f8ff0',
  blue600: '#3f7bd6',
  amber50: '#fff4e0',
  amber500: '#f5a524',

  teal100: '#dff3ef',
  teal600: '#1e8d80',

  lilac50: '#eeecf8',
  lilac100: '#e7e5f3',
  lilac200: '#c9c2f0',
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
