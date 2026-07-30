import type { LinearGradientProps } from 'expo-linear-gradient';

import { Palette } from './colors';

export const Gradients = {
  avatar: ['#6fcfc4', '#8b7ff0'],
  authWelcome: [Palette.lavender100, Palette.mint100],
  signupCompleteBackground: ['#eae7fb', '#f7f6fb'],
  signupHouseholdCard: [Palette.lavender100, Palette.sky100],
  signupCompleteIcon: ['#8b7ff0', '#6fcfc4'],
  homeBackground: ['#ddf3f0', '#eae7fb', '#f7f6fb'],
} as const satisfies Record<string, LinearGradientProps['colors']>;
