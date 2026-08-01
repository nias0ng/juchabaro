import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

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
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
});
