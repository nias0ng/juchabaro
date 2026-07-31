import { StyleSheet } from 'react-native';

import { FontWeight, Palette, Spacing } from '@/styles';

export const styles = StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: Spacing.lg,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: FontWeight.bold,
    color: Palette.gray975,
  },
  statusContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxl,
  },
  statusText: {
    fontSize: 13.5,
    color: Palette.gray500,
    textAlign: 'center',
  },
});
