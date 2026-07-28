import { StyleSheet } from 'react-native';

import { ControlHeight, FontWeight, Radius, Spacing, Typography } from '@/styles';

export const styles = StyleSheet.create({
  base: {
    minWidth: 0,
    borderWidth: 1,
    borderRadius: Radius.full,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  sm: {
    minHeight: ControlHeight.sm,
    paddingHorizontal: Spacing.md,
  },
  md: {
    minHeight: ControlHeight.md,
    paddingHorizontal: Spacing.lg,
  },
  lg: {
    minHeight: ControlHeight.lg,
    paddingHorizontal: Spacing.lg,
  },
  fullWidth: {
    width: '100%',
  },
  label: {
    ...Typography.body,
    fontWeight: FontWeight.bold,
    textAlign: 'center',
  },
  pressed: {
    opacity: 0.78,
  },
  disabled: {
    opacity: 0.45,
  },
});
