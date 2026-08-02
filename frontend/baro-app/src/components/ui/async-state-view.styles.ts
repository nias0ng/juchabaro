import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
  },
  fill: {
    flex: 1,
  },
  text: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
});
