import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.sm,
    paddingVertical: Spacing.xxl,
  },
  icon: {
    fontSize: 28,
  },
  heading: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  message: {
    fontSize: 12,
    color: Palette.gray500,
    textAlign: 'center',
    paddingBottom: Spacing.sm,
  },
});
