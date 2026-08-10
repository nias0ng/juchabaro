import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  container: {
    paddingTop: Spacing.lg,
    paddingBottom: Spacing.md,
  },
  title: {
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  titleWithBack: {
    fontSize: 19,
    marginTop: -2,
  },
  titleWithoutBack: {
    fontSize: 21,
  },
  right: {
    marginLeft: 'auto',
  },
});
