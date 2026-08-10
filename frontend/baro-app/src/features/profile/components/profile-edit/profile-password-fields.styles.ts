import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    gap: Spacing.xs,
    paddingTop: Spacing.sm,
  },
  title: {
    fontSize: 15,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  description: {
    fontSize: 11.5,
    color: Palette.gray500,
  },
});
