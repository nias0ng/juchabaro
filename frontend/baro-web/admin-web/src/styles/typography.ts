/**
 * 웹 전용 폰트 스택. 실제 값은 tokens.css의 --font-* 변수에 정의한다.
 */
export const Fonts = {
  sans: 'var(--font-sans)',
  mono: 'var(--font-mono)',
} as const;

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
} as const;

/**
 * 자주 사용하는 텍스트 조합입니다. 색상은 테마에 따라 달라지므로 각 컴포넌트에서 별도로 지정합니다.
 */
export const Typography = {
  caption: { fontSize: FontSize.xs, lineHeight: LineHeight.xs, fontWeight: FontWeight.medium },
  small: { fontSize: FontSize.md, lineHeight: LineHeight.sm, fontWeight: FontWeight.medium },
  smallBold: { fontSize: FontSize.md, lineHeight: LineHeight.sm, fontWeight: FontWeight.bold },
  body: { fontSize: FontSize.base, lineHeight: LineHeight.md, fontWeight: FontWeight.medium },
  title: { fontSize: FontSize.display, lineHeight: LineHeight.display, fontWeight: FontWeight.semibold },
  subtitle: { fontSize: FontSize.xxl, lineHeight: LineHeight.xxl, fontWeight: FontWeight.semibold },
  link: { fontSize: FontSize.md, lineHeight: LineHeight.lg, fontWeight: FontWeight.medium },
  code: { fontSize: FontSize.sm, lineHeight: LineHeight.sm, fontWeight: FontWeight.medium },
} as const;
