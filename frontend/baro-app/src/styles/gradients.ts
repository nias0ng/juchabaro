import type { LinearGradientProps } from 'expo-linear-gradient';

export const Gradients = {
  avatar: ['#6fcfc4', '#8b7ff0'],
  responseComplete: ['#ddf3f0', '#eae7fb', '#f7f6fb'],
  vehicleShortcut: ['#8b7ff0', '#6fcfc4'],
} as const satisfies Record<string, LinearGradientProps['colors']>;
