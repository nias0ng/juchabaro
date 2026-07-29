import type { ViewStyle } from 'react-native';

import { Palette } from './colors';

export const Shadows = {
  control: {
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 1,
  },
  dashboardCard: {
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
} as const satisfies Record<string, ViewStyle>;
