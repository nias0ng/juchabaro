import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  content: {
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
  saveButton: {
    marginTop: Spacing.sm,
  },
});
