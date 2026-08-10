import { StyleSheet } from 'react-native';

import { FontWeight, Palette } from '@/styles';

export const styles = StyleSheet.create({
  wrapper: {
    width: 150,
    height: 150,
    alignItems: 'center',
    justifyContent: 'center',
  },
  spinner: {
    position: 'absolute',
    width: 150,
    height: 150,
  },
  dial: {
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
