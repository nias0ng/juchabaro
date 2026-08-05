import { StyleSheet } from 'react-native';

import { Palette, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  content: {
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  toggleCard: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: 26,
    paddingHorizontal: Spacing.md + 2,
    paddingVertical: Spacing.xs,
    ...Shadows.card,
  },
  stateContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
    paddingVertical: Spacing.xl * 2,
  },
  stateText: {
    fontSize: 13,
    color: Palette.gray500,
  },
  savingText: {
    textAlign: 'center',
    fontSize: 12,
    color: Palette.gray500,
  },
});
