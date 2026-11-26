import { StyleSheet } from 'react-native';

import { FontWeight, Radius, Spacing, type ColorTokens } from '@/styles';

export const createStyles = (t: ColorTokens) =>
  StyleSheet.create({
    row: {
      flexDirection: 'row',
      gap: Spacing.sm,
    },
    rowWrap: {
      flexWrap: 'wrap',
    },
    pill: {
      backgroundColor: t.background.raised,
      borderRadius: Radius.full,
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.sm + 1,
    },
    pillSelected: {
      backgroundColor: t.fill.inverse.strong,
    },
    pillText: {
      fontSize: 12.5,
      fontWeight: FontWeight.medium,
      color: t.text.weak,
    },
    pillTextSelected: {
      color: t.text.inverse,
    },
  });
