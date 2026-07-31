import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.lg,
  },
  headerAction: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.violet500,
  },
  content: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  activeField: {
    borderWidth: 1,
    borderColor: Palette.violet500,
  },
  verifiedBadge: {
    backgroundColor: Palette.teal100,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm + 2,
    paddingVertical: Spacing.xs + 1,
  },
  verifiedBadgeText: {
    fontSize: 11,
    fontWeight: FontWeight.bold,
    color: Palette.teal600,
  },
  withdrawLink: {
    alignItems: 'center',
    paddingVertical: Spacing.xs,
  },
  withdrawText: {
    fontSize: 12.5,
    fontWeight: FontWeight.medium,
    color: Palette.gray400,
    textDecorationLine: 'underline',
  },
});
