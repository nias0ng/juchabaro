import { StyleSheet } from 'react-native';

import { Palette } from '@/styles';

export const styles = StyleSheet.create({
  outer: {
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
    alignItems: 'center',
    justifyContent: 'center',
  },
  check: {
    color: Palette.white,
  },
});
