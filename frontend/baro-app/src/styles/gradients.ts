import type { LinearGradientProps } from 'expo-linear-gradient';

export const Gradients = {
  avatar: ['#6fcfc4', '#8b7ff0'],
} as const satisfies Record<string, LinearGradientProps['colors']>;
