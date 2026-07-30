import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  gradient: {
    flex: 1,
  },
  content: {
    paddingBottom: Spacing.lg,
    gap: Spacing.base,
  },
  greeting: {
    marginTop: Spacing.sm,
    fontSize: 26,
    lineHeight: 32.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.6,
  },
});
