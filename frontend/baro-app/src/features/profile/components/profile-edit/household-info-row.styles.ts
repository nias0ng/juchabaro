import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    gap: Spacing.sm,
  },
  label: {
    fontSize: 12.5,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    backgroundColor: Palette.gray100,
    borderRadius: Radius.input,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
  },
  value: {
    fontSize: 14,
    color: Palette.gray500,
  },
  caption: {
    fontSize: 11.5,
    color: Palette.gray400,
  },
});
