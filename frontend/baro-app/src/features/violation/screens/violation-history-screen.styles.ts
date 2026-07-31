import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.lg,
  },
  content: {
    gap: Spacing.base + 2,
    paddingBottom: Spacing.xl,
  },
  listCard: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: 26,
    padding: Spacing.lg - 4,
    gap: Spacing.md,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
  monthGroup: {
    gap: Spacing.md,
  },
  monthLabel: {
    fontSize: 12,
    fontWeight: FontWeight.bold,
    color: '#9599a7',
  },
  monthItems: {
    gap: Spacing.md,
  },
  emptyText: {
    fontSize: 13,
    color: Palette.gray500,
    textAlign: 'center',
    paddingVertical: Spacing.lg,
  },
});
