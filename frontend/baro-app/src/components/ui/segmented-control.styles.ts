import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: Spacing.sm,
  },
  rowWrap: {
    flexWrap: 'wrap',
  },
  pill: {
    backgroundColor: Palette.white,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.sm + 1,
  },
  pillSelected: {
    backgroundColor: Palette.gray975,
  },
  pillText: {
    fontSize: 12.5,
    fontWeight: FontWeight.medium,
    color: Palette.gray600,
  },
  pillTextSelected: {
    color: Palette.white,
  },
});
