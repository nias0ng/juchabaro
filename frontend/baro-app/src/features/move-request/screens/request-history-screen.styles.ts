import { StyleSheet } from 'react-native';

import { Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.lg,
  },
  content: {
    paddingHorizontal: Spacing.lg,
    paddingTop: Spacing.md,
    paddingBottom: Spacing.xl,
  },
  statusContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
    paddingHorizontal: Spacing.lg,
  },
  statusText: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
});
