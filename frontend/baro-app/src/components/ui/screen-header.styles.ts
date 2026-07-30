import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    paddingTop: Spacing.lg,
    paddingBottom: Spacing.md,
  },
  title: {
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  right: {
    marginLeft: 'auto',
  },
});
