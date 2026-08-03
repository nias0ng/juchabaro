import type { LinearGradientProps } from 'expo-linear-gradient';

export const Gradients = {
  avatar: ['#6fcfc4', '#8b7ff0'],
  responseComplete: ['#ddf3f0', '#eae7fb', '#f7f6fb'],
  vehicleShortcut: ['rgba(111, 207, 196, 0.28)', 'rgba(139, 127, 240, 0.24)'],
} as const satisfies Record<string, LinearGradientProps['colors']>;
