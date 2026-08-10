import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  metricLabel: {
    fontSize: 12,
    fontWeight: FontWeight.medium,
    color: Palette.gray600,
  },
  rate: {
    fontSize: 20,
    lineHeight: 24,
    fontWeight: FontWeight.bold,
  },
  pill: {
    minHeight: 24,
    justifyContent: 'center',
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
  },
  pillLow: {
    backgroundColor: Palette.mint100,
  },
  pillMedium: {
    backgroundColor: Palette.amber50,
  },
  pillHigh: {
    backgroundColor: Palette.orange50,
  },
  value: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
  },
  valueLow: {
    color: Palette.emerald500,
  },
  valueMedium: {
    color: Palette.amber500,
  },
  valueHigh: {
    color: Palette.red500,
  },
});
