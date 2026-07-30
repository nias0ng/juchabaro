import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  mainCard: {
    gap: Spacing.base + 1,
    backgroundColor: Palette.gray50,
    paddingTop: Spacing.lg + 4,
    paddingBottom: Spacing.lg,
    paddingHorizontal: Spacing.md + 4,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.07,
    shadowRadius: 10,
    elevation: 4,
  },
  summary: {
    gap: Spacing.xs,
  },
  summaryTitle: {
    fontSize: 19,
    lineHeight: 24.7,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  summaryReason: {
    fontSize: 12.5,
    lineHeight: 21.25,
    color: Palette.gray500,
  },
});
