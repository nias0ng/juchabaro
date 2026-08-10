import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
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
    ...Shadows.card,
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
    gap: Spacing.base,
  },
  historyItem: {
    gap: Spacing.base,
  },
  itemDivider: {
    height: 1,
    marginLeft: 40 + Spacing.base,
    backgroundColor: Palette.gray100,
  },
});
