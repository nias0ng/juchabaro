import { StyleSheet } from 'react-native';

import { ControlHeight, FontWeight, Palette, Radius, Shadows, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.lg,
    paddingHorizontal: Spacing.md + 2,
    minHeight: ControlHeight.md,
    paddingVertical: Spacing.base + 2,
    ...Shadows.card,
  },
  rowPressed: {
    backgroundColor: Palette.gray50,
  },
  leading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
  },
  label: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: Palette.gray975,
  },
  labelDisabled: {
    color: Palette.gray500,
  },
  chevron: {
    fontSize: 16,
    lineHeight: 18,
    color: Palette.gray400,
  },
  badge: {
    fontSize: 10.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray500,
    backgroundColor: Palette.gray100,
    borderRadius: Radius.full,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
  },
});
