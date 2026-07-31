import { StyleSheet } from 'react-native';

import { Palette } from '@/styles';

export const styles = StyleSheet.create({
  outer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: Palette.gray975,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.08,
    shadowRadius: 15,
    elevation: 4,
  },
  inner: {
    width: 26,
    height: 26,
    borderRadius: 13,
    alignItems: 'center',
    justifyContent: 'center',
  },
  check: {
    fontSize: 13,
    color: Palette.white,
  },
});
