import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm + 2,
    backgroundColor: Palette.white,
    borderRadius: Radius.input,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.base + 1,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.05,
    shadowRadius: 9,
    elevation: 2,
  },
  radioOuter: {
    width: 14,
    height: 14,
    borderRadius: 7,
    borderWidth: 2,
    borderColor: Palette.emerald500,
  },
  zoneText: {
    flex: 1,
    fontSize: 13.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  zoneTextPlaceholder: {
    fontWeight: FontWeight.regular,
    color: Palette.gray400,
  },
  selectText: {
    fontSize: 12.5,
    color: Palette.violet500,
  },
});
