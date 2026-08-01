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
  sectionHeader: {
    gap: Spacing.xs,
    paddingTop: Spacing.sm,
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  sectionDescription: {
    fontSize: 11.5,
    color: Palette.gray500,
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
  apiNotice: {
    borderRadius: Radius.md,
    backgroundColor: Palette.violet100,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base,
  },
  apiNoticeText: {
    fontSize: 11.5,
    lineHeight: 18,
    color: Palette.violet600,
  },
  saveButton: {
    marginTop: Spacing.sm,
  },
});
