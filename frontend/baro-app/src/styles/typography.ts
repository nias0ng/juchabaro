import { Platform, type TextStyle } from 'react-native';

export const Fonts = Platform.select({
  ios: {
    sans: 'system-ui',
    serif: 'ui-serif',
    rounded: 'ui-rounded',
    mono: 'ui-monospace',
  },
  android: {
    sans: 'sans-serif',
    serif: 'serif',
    rounded: 'sans-serif',
    mono: 'monospace',
  },
  web: {
    sans: 'var(--font-sans)',
    serif: 'var(--font-serif)',
    rounded: 'var(--font-rounded)',
    mono: 'var(--font-mono)',
  },
  default: {
    sans: 'System',
    serif: 'serif',
    rounded: 'System',
    mono: 'monospace',
  },
});

export const FontSize = {
  xs: 11,
  sm: 12,
  md: 14,
  base: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
  display: 48,
} as const;

export const LineHeight = {
  xs: 16,
  sm: 20,
  md: 24,
  lg: 30,
  xl: 32,
  xxl: 44,
  display: 52,
} as const;

export const FontWeight = {
  regular: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
} as const satisfies Record<string, NonNullable<TextStyle['fontWeight']>>;

/**
 * 자주 사용하는 텍스트 조합입니다.
 * 색상은 테마에 따라 달라지므로 각 컴포넌트에서 별도로 지정합니다.
 */
export const Typography = {
  caption: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.xs,
    lineHeight: LineHeight.xs,
    fontWeight: FontWeight.medium,
  },
  small: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.md,
    lineHeight: LineHeight.sm,
    fontWeight: FontWeight.medium,
  },
  smallBold: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.md,
    lineHeight: LineHeight.sm,
    fontWeight: FontWeight.bold,
  },
  body: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.base,
    lineHeight: LineHeight.md,
    fontWeight: FontWeight.medium,
  },
  title: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.display,
    lineHeight: LineHeight.display,
    fontWeight: FontWeight.semibold,
  },
  subtitle: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.xxl,
    lineHeight: LineHeight.xxl,
    fontWeight: FontWeight.semibold,
  },
  link: {
    fontFamily: Fonts.sans,
    fontSize: FontSize.md,
    lineHeight: LineHeight.lg,
    fontWeight: FontWeight.medium,
  },
  code: {
    fontFamily: Fonts.mono,
    fontSize: FontSize.sm,
    lineHeight: LineHeight.sm,
    fontWeight: FontWeight.medium,
  },
} as const satisfies Record<string, TextStyle>;
