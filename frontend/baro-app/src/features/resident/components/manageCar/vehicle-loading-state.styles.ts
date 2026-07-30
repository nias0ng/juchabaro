import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.md,
    paddingVertical: Spacing.xxl,
  },
  text: {
    fontSize: 13,
    color: Palette.gray500,
  },
});
