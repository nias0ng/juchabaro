import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.xs,
    borderRadius: Radius.lg,
    borderWidth: 1,
    borderColor: Palette.gray300,
    borderStyle: 'dashed',
    paddingVertical: Spacing.base,
  },
  pressed: {
    backgroundColor: Palette.gray100,
  },
  plus: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray600,
  },
  label: {
    fontSize: 13,
    fontWeight: FontWeight.medium,
    color: Palette.gray600,
  },
});
