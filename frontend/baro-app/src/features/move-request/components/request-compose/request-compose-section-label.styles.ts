import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  label: {
    fontSize: 13,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  suffix: {
    fontWeight: FontWeight.regular,
    color: Palette.gray400,
  },
});
