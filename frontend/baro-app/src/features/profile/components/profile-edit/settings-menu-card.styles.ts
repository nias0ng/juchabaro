import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  card: {
    width: '100%',
    backgroundColor: Palette.white,
    borderRadius: Radius.xl,
    paddingHorizontal: Spacing.md + 2,
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.05,
    shadowRadius: 10,
    elevation: 2,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: Spacing.base,
  },
  rowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: Palette.gray100,
  },
  label: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: Palette.gray975,
  },
  labelDisabled: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
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
