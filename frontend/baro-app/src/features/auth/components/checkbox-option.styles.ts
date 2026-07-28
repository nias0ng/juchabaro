import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  box: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: Palette.gray300,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  boxChecked: {
    backgroundColor: Palette.gray950,
    borderColor: Palette.gray950,
  },
  checkIcon: {
    width: 12,
    height: 12,
  },
  label: {
    fontSize: 14,
    fontWeight: FontWeight.medium,
    color: Palette.gray400,
  },
  labelChecked: {
    color: Palette.gray975,
  },
});
