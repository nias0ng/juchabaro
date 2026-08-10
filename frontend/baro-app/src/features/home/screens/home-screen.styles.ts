import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  gradient: {
    flex: 1,
  },
  content: {
    paddingTop: Spacing.xl,
    paddingBottom: Spacing.base,
    gap: Spacing.md,
  },
  greeting: {
    marginTop: Spacing.sm,
    marginBottom: Spacing.sm,
    fontSize: 26,
    lineHeight: 32.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.6,
  },
});
