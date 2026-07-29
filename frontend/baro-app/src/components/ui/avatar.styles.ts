import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Radius } from '@/styles';

export const styles = StyleSheet.create({
  circle: {
    borderRadius: Radius.full,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    fontWeight: FontWeight.bold,
    color: Palette.white,
  },
});
