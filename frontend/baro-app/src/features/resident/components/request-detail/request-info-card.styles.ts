import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    gap: Spacing.base,
  },
  violationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: Palette.white,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base + 2,
  },
  violationBadgeText: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.red500,
  },
  infoGrid: {
    flexDirection: 'row',
    gap: Spacing.base,
  },
  infoCard: {
    flex: 1,
    gap: Spacing.xs + 1,
    backgroundColor: Palette.white,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base + 2,
  },
  label: {
    fontSize: 12,
    color: Palette.gray500,
  },
  value: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
});
