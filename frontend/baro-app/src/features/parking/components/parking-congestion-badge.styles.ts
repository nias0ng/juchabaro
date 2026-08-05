import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  prefix: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  pill: {
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
