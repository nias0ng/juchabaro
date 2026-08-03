export const Breakpoints = {
  compact: 480,
  tablet: 768,
  desktop: 1024,
} as const;

export const ContentWidth = {
  compact: 480,
  default: 800,
  wide: 1120,
} as const;

export const ControlHeight = {
  sm: 40,
  md: 48,
  lg: 56,
} as const;

export const MaxContentWidth = ContentWidth.wide;
