import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  title: {
    fontSize: 22,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
    letterSpacing: -0.4,
  },
  description: {
    fontSize: 12.5,
    color: Palette.gray500,
  },
});
