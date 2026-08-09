import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 24,
    gap: Spacing.xxs,
  },
  label: {
    fontSize: 13,
    fontWeight: FontWeight.medium,
    color: Palette.gray600,
  },
  value: {
    fontSize: 18,
    lineHeight: 22,
    fontWeight: FontWeight.bold,
  },
  valueLow: {
    color: Palette.teal600,
  },
  valueMedium: {
    color: Palette.amber500,
  },
  valueHigh: {
    color: Palette.red500,
  },
  countGroup: {
    flexDirection: 'row',
    alignItems: 'baseline',
  },
  unit: {
    fontSize: 13,
    fontWeight: FontWeight.semibold,
    color: Palette.gray600,
  },
});
