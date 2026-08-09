import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const VEHICLES_SCREEN_BACKGROUND = '#f7f6fb';

export const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  content: {
    gap: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  countRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  countText: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  primaryLabel: {
    fontSize: 11.5,
    color: Palette.violet500,
  },
  notice: {
    fontSize: 10.5,
    lineHeight: 16.8,
    color: Palette.gray400,
  },
});
