import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  outer: {
    width: 150,
    height: 150,
    borderRadius: 75,
    alignItems: 'center',
    justifyContent: 'center',
  },
  inner: {
    width: 124,
    height: 124,
    borderRadius: 62,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 12,
    elevation: 3,
  },
  time: {
    fontSize: 26,
    fontWeight: FontWeight.semibold,
    color: '#c8492e',
  },
  caption: {
    fontSize: 9.5,
    color: '#9599a7',
  },
});
