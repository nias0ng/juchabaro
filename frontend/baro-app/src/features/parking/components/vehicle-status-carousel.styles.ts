import { StyleSheet } from 'react-native';

import { Palette, Radius, Shadows } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    backgroundColor: Palette.gray25,
    borderRadius: Radius.xxl + 2,
    ...Shadows.card,
  },
  scroll: {
    width: '100%',
    borderRadius: Radius.xxl + 2,
  },
  page: {
    width: '100%',
  },
});
