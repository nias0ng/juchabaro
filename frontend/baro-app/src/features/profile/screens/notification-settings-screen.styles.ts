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
});
