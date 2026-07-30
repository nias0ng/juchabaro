import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  ring: {
    width: 170,
    height: 170,
    marginTop: Spacing.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  svg: {
    position: 'absolute',
  },
  dial: {
    width: 142,
    height: 142,
    borderRadius: 71,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  time: {
    fontSize: 32,
    fontWeight: FontWeight.semibold,
    color: Palette.gray975,
    letterSpacing: -0.5,
  },
  caption: {
    fontSize: 10,
    color: '#9599a7',
    letterSpacing: 1,
  },
});
