import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    paddingVertical: Spacing.base + 1,
  },
  rowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: Palette.gray100,
  },
  textGroup: {
    gap: 2,
  },
  label: {
    fontSize: 14,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  subtitle: {
    fontSize: 11.5,
    color: Palette.gray400,
  },
});
