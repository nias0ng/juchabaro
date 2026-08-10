import { StyleSheet } from 'react-native';

import { Palette, Radius } from '@/styles';

export const styles = StyleSheet.create({
  track: {
    width: 52,
    height: 27,
    borderRadius: Radius.full,
    justifyContent: 'center',
    paddingHorizontal: 3,
    backgroundColor: Palette.gray200,
  },
  trackOn: {
    backgroundColor: Palette.violet500,
  },
  trackOnDisabled: {
    backgroundColor: '#c9c4e8',
  },
  thumbAlignStart: {
    alignItems: 'flex-start',
  },
  thumbAlignEnd: {
    alignItems: 'flex-end',
  },
  thumb: {
    width: 21,
    height: 21,
    borderRadius: 10.5,
    backgroundColor: Palette.white,
  },
});
