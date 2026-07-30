import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    gap: Spacing.base + 2,
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  textBlock: {
    alignItems: 'center',
    gap: Spacing.sm,
  },
  heading: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    textAlign: 'center',
    lineHeight: 22.4,
  },
  pill: {
    backgroundColor: Palette.white,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 4,
    paddingVertical: Spacing.xs + 1,
  },
  pillText: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: '#d4553a',
  },
});
