import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingTop: Spacing.lg,
  },
  headerAction: {
    fontSize: 12.5,
    fontWeight: FontWeight.medium,
    color: Palette.violet500,
  },
  headerActionDisabled: {
    color: Palette.gray400,
  },
  content: {
    gap: Spacing.base + 2,
    paddingTop: 20,
    paddingBottom: Spacing.xl,
  },
  mapCard: {
    width: '100%',
    backgroundColor: Palette.white80,
    borderRadius: Radius.xl + 2,
    padding: Spacing.md,
    gap: Spacing.base,
    ...Shadows.card,
  },
  congestionRow: {
    alignSelf: 'flex-end',
  },
});
