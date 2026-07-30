import { StyleSheet } from 'react-native';

import { Palette } from '@/styles';

export const styles = StyleSheet.create({
  badge: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: Palette.white,
    alignItems: 'center',
    justifyContent: 'center',
  },
  icon: {
    fontSize: 22,
    color: Palette.gray975,
  },
});
