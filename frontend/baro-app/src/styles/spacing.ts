/**
 * 4px 기반 간격 체계입니다.
 * margin, padding, gap에는 임의 숫자 대신 이 값을 우선 사용하세요.
 */
export const Spacing = {
  none: 0,
  xxs: 2,
  xs: 4,
  sm: 8,
  base: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
  xxxl: 64,
} as const;

export const Radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  full: 999,
  /** 폼 인풋 필드 전용 (18~20px 사이 값을 20으로 통일) */
  input: 20,
} as const;
