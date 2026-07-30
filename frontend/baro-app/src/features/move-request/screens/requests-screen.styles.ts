import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  content: {
    flexGrow: 1,
  },
  container: {
    flex: 1,
    gap: Spacing.md,
    paddingTop: Spacing.lg,
    paddingBottom: Spacing.lg,
  },
  title: {
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.4,
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
  },
  emptyText: {
    fontSize: 13.5,
    color: Palette.gray500,
  },
});
