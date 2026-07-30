import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: 26,
    paddingHorizontal: Spacing.md + 2,
    paddingVertical: Spacing.base + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.06,
    shadowRadius: 13,
    elevation: 2,
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
    fontSize: 12.5,
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
