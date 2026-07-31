import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.lg,
  },
  headerAction: {
    fontSize: 12.5,
    fontWeight: FontWeight.medium,
    color: Palette.violet500,
  },
  content: {
    gap: Spacing.base + 2,
    paddingBottom: Spacing.xl,
  },
  mapCard: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xl + 2,
    padding: Spacing.md,
    gap: Spacing.base,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
  },
});
