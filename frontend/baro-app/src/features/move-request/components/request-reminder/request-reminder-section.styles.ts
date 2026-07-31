import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    gap: Spacing.base,
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
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
  description: {
    fontSize: 12.5,
    color: '#7b8091',
    textAlign: 'center',
    lineHeight: 20,
  },
});
